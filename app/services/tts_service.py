"""
Text-to-Speech service module for backend TTS processing.

This module handles TTS operations using Eleven Labs API and provides
fallback mechanisms for audio generation.
"""

import logging
import requests
import io
import re
from typing import Optional, Generator
from config import Config

logger = logging.getLogger(__name__)

class TTSService:
    """Service for handling text-to-speech operations."""
    
    def __init__(self):
        """Initialize TTS service."""
        self.api_key = Config.ELEVENLABS_API_KEY
        self.base_url = "https://api.elevenlabs.io/v1"
        self.default_voice_id = "21m00Tcm4TlvDq8ikWAM"  # Rachel voice
        self.model_id = "eleven_monolingual_v1"
        
    def _get_voice_id(self, language: str = "english") -> str:
        """
        Get appropriate voice ID based on language.
        
        Args:
            language: Language preference
            
        Returns:
            Voice ID string
        """
        # Voice mapping based on language
        voice_map = {
            "english": "21m00Tcm4TlvDq8ikWAM",  # Rachel
            "hindi": "21m00Tcm4TlvDq8ikWAM",    # Same voice, multilingual
            "1": "21m00Tcm4TlvDq8ikWAM",        # Hindi numeric code
        }
        
        return voice_map.get(language.lower(), self.default_voice_id)
    
    def _clean_text_for_tts(self, text: str) -> str:
        """
        Clean text for better TTS pronunciation.
        
        Args:
            text: Raw text to clean
            
        Returns:
            Cleaned text suitable for TTS
        """
        if not text:
            return ""
                
        # Remove complex citations with filenames and page numbers
        text = re.sub(
            r'\[([^,\]]+\.(?:pdf|doc|docx|txt|xls|xlsx|ppt|pptx|csv))[,\s]+Page\s*[\d\s,-]+\]',
            '', text, flags=re.IGNORECASE
        )
        
        # Remove citations [1], [2], etc.
        text = re.sub(r'\[\d+\]', '', text)
        
        # Remove any remaining brackets with source-like content
        text = re.sub(
            r'\[[^\]]*\.(?:pdf|doc|docx|txt|xls|xlsx|ppt|pptx|csv)[^\]]*\]',
            '', text, flags=re.IGNORECASE
        )
        
        # Remove markdown formatting
        text = re.sub(r'#{1,6}\s+', '', text)  # Headers
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # Bold
        text = re.sub(r'\*([^*]+)\*', r'\1', text)  # Italic
        text = re.sub(r'```[\s\S]*?```', '', text)  # Code blocks
        text = re.sub(r'`([^`]+)`', r'\1', text)  # Inline code
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # Links
        
        # Remove special symbols
        text = re.sub(r'[?>]+', '', text)
        
        # Replace abbreviations for better speech
        text = re.sub(r'\bDr\.', 'Doctor', text)
        text = re.sub(r'\bMr\.', 'Mister', text)
        text = re.sub(r'\bMrs\.', 'Misses', text)
        text = re.sub(r'\bMs\.', 'Miss', text)
        
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
    
    def _split_text_for_streaming(self, text: str, max_length: int = 200) -> list:
        """
        Split text into chunks suitable for streaming TTS.
        
        Args:
            text: Text to split
            max_length: Maximum length per chunk
            
        Returns:
            List of text chunks
        """        
        # Split by sentences first
        sentences = re.split(r'[.!?]+', text)
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
                
            # If adding this sentence would exceed max length, save current chunk
            if current_chunk and len(current_chunk) + len(sentence) > max_length:
                chunks.append(current_chunk.strip())
                current_chunk = sentence
            else:
                if current_chunk:
                    current_chunk += ". " + sentence
                else:
                    current_chunk = sentence
        
        # Add remaining chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        return [chunk for chunk in chunks if len(chunk.strip()) > 0]
    
    def test_connection(self) -> bool:
        """
        Test connection to Eleven Labs API.
        
        Returns:
            True if connection successful, False otherwise
        """
        if not self.api_key:
            logger.error("No API key available for testing")
            return False
        
        try:
            response = requests.get(
                f"{self.base_url}/voices",
                headers={"xi-api-key": self.api_key},
                timeout=5
            )
            
            if response.status_code == 200:
                voices = response.json().get('voices', [])
                logger.info(f"Eleven Labs connection successful, {len(voices)} voices available")
                return True
            else:
                logger.error(f"Eleven Labs API test failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Eleven Labs connection test error: {e}")
            return False
    
    def generate_audio_stream(self, text: str, language: str = "english") -> Generator[bytes, None, None]:
        """
        Generate audio stream from text using Eleven Labs API.
        
        Args:
            text: Text to convert to speech
            language: Language preference
            
        Yields:
            Audio chunks as bytes
        """
        if not self.api_key:
            logger.error("Eleven Labs API key not configured")
            raise ValueError("TTS service not configured")
        
        # Clean text for TTS
        cleaned_text = self._clean_text_for_tts(text)
        if not cleaned_text:
            logger.warning("No text to convert after cleaning")
            return
        
        logger.info(f"Generating TTS for text length: {len(cleaned_text)}")
        
        # Split text into manageable chunks for streaming
        chunks = self._split_text_for_streaming(cleaned_text)
        voice_id = self._get_voice_id(language)
        
        for i, chunk in enumerate(chunks):
            try:
                logger.debug(f"Processing TTS chunk {i+1}/{len(chunks)}: {chunk[:50]}...")
                
                # Make API request for this chunk
                response = requests.post(
                    f"{self.base_url}/text-to-speech/{voice_id}",
                    headers={
                        "Accept": "audio/mpeg",
                        "Content-Type": "application/json",
                        "xi-api-key": self.api_key
                    },
                    json={
                        "text": chunk,
                        "model_id": self.model_id,
                        "voice_settings": {
                            "stability": 0.5,
                            "similarity_boost": 0.75
                        }
                    },
                    timeout=30,
                    stream=True
                )
                
                if response.status_code == 200:
                    # Stream the audio data
                    for audio_chunk in response.iter_content(chunk_size=8192):
                        if audio_chunk:
                            yield audio_chunk
                    logger.debug(f"Successfully processed chunk {i+1}")
                else:
                    logger.error(f"TTS API error for chunk {i+1}: {response.status_code}")
                    # Continue with next chunk rather than failing completely
                    continue
                    
            except Exception as e:
                logger.error(f"Error processing TTS chunk {i+1}: {e}")
                # Continue with next chunk
                continue
        
        logger.info("TTS audio generation completed")
    
    def generate_audio_buffer(self, text: str, language: str = "english") -> Optional[bytes]:
        """
        Generate complete audio buffer from text.
        
        Args:
            text: Text to convert to speech
            language: Language preference
            
        Returns:
            Complete audio data as bytes, or None if failed
        """
        try:
            audio_buffer = io.BytesIO()
            
            for chunk in self.generate_audio_stream(text, language):
                audio_buffer.write(chunk)
            
            audio_data = audio_buffer.getvalue()
            audio_buffer.close()
            
            if len(audio_data) > 0:
                return audio_data
            else:
                logger.warning("No audio data generated")
                return None
                
        except Exception as e:
            logger.error(f"Error generating audio buffer: {e}")
            return None

# Singleton instance
_tts_service = None

def get_tts_service() -> TTSService:
    """
    Get the TTS service singleton instance.
    
    Returns:
        TTSService: The TTS service instance
    """
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service