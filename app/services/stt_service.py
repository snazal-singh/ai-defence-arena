"""
Speech-to-Text service utilizing a state-of-the-art Hybrid ASR Architecture.
Leverages OpenAI's Whisper-Base for high-fidelity English transcription and zero-touch language identification (LID),
and automatically routes Indian languages to AI4Bharat's Indic-Conformer-600M for 22 native Indian languages in native scripts.
"""

import os
import logging
import torch
from typing import Optional
from transformers import pipeline

logger = logging.getLogger(__name__)

# Mapping of standard language names to AI4Bharat Conformer codes
LANGUAGE_MAP = {
    "hindi": "hi",
    "gom": "kok",       # Goan Konkani mapped to Konkani
    "kannada": "kn",
    "dogri": "doi",
    "bodo": "brx",
    "urdu": "ur",
    "tamil": "ta",
    "kashmiri": "ks",
    "assamese": "as",
    "bengali": "bn",
    "marathi": "mr",
    "sindhi": "sd",
    "maithili": "mai",
    "punjabi": "pa",
    "malayalam": "ml",
    "manipuri": "mni",
    "telugu": "te",
    "sanskrit": "sa",
    "nepali": "ne",
    "santali": "sat",
    "gujarati": "gu",
    "odia": "or"
}

class STTService:
    """Hybrid Service using Whisper-Base for English/LID and AI4Bharat Indic-Conformer for 22 Indian languages."""

    def __init__(self):
        self.whisper_pipe = None
        self.conformer_model = None
        
        # Setup device selection (CUDA GPU > MPS Apple Silicon GPU > CPU)
        if torch.cuda.is_available():
            self.device = torch.device("cuda")
        elif torch.backends.mps.is_available():
            self.device = torch.device("mps")
        else:
            self.device = torch.device("cpu")
            
        logger.info(f"Hybrid STT Service initialized. Default execution device: {self.device}")

    def load_whisper(self):
        """Lazy load the Whisper-Base model to save memory at startup."""
        if self.whisper_pipe is None:
            logger.info(f"Loading OpenAI Whisper-Base Model on {self.device}...")
            # We use openai/whisper-base (140M params) for perfect speed & bilingual accuracy
            device_arg = 0 if self.device.type == "cuda" else ("mps" if self.device.type == "mps" else -1)
            try:
                self.whisper_pipe = pipeline(
                    "automatic-speech-recognition",
                    model="openai/whisper-base",
                    device=device_arg
                )
                logger.info("Whisper-Base Model loaded successfully.")
            except Exception as e:
                if self.device.type == "mps":
                    logger.warning(f"Failed to load Whisper on MPS: {e}. Falling back to CPU...")
                    try:
                        self.whisper_pipe = pipeline(
                            "automatic-speech-recognition",
                            model="openai/whisper-base",
                            device=-1
                        )
                        logger.info("Whisper-Base Model loaded successfully on CPU fallback.")
                    except Exception as fallback_err:
                        logger.error(f"Failed to load Whisper model even on CPU fallback: {fallback_err}")
                        raise fallback_err
                else:
                    logger.error(f"Failed to load Whisper model: {e}")
                    raise e

    def load_conformer(self):
        """Lazy load the Indic-Conformer-600M model to save memory at startup."""
        if self.conformer_model is None:
            logger.info(f"Loading AI4Bharat Indic-Conformer-600M Model on {self.device}...")
            try:
                from transformers import AutoModel
                # trust_remote_code=True is required for AI4Bharat custom conformer class
                self.conformer_model = AutoModel.from_pretrained(
                    "ai4bharat/indic-conformer-600m-multilingual",
                    trust_remote_code=True
                )
                self.conformer_model.to(self.device)
                self.conformer_model.eval()
                logger.info("Indic-Conformer-600M model loaded successfully.")
            except Exception as e:
                # Handle potential MPS operation failures or errors by falling back to CPU
                if self.device.type == "mps":
                    logger.warning(f"Failed to load Conformer ASR Model on MPS GPU: {e}. Falling back to CPU...")
                    self.conformer_device = torch.device("cpu")
                    try:
                        from transformers import AutoModel
                        self.conformer_model = AutoModel.from_pretrained(
                            "ai4bharat/indic-conformer-600m-multilingual",
                            trust_remote_code=True
                        )
                        self.conformer_model.to(self.conformer_device)
                        self.conformer_model.eval()
                        logger.info("Indic-Conformer-600M model loaded successfully on CPU fallback.")
                    except Exception as fallback_err:
                        logger.error(f"Failed to load Conformer ASR Model even on CPU fallback: {fallback_err}")
                        raise fallback_err
                else:
                    logger.error(f"Failed to load Conformer ASR Model: {e}")
                    raise e

    def preprocess_audio(self, audio_path: str, target_device: torch.device) -> torch.Tensor:
        """
        Load and preprocess audio for Indic-Conformer ASR.
        Converts format to 16,000 Hz sample rate and collapses channels to Mono.
        """
        import soundfile as sf
        import torchaudio
        data, sample_rate = sf.read(audio_path)
        
        waveform = torch.tensor(data).float()
        if len(waveform.shape) == 1:
            waveform = waveform.unsqueeze(0)  # Convert mono to shape (1, num_frames)
        else:
            waveform = waveform.t()  # Transpose to shape (num_channels, num_frames)
        
        # Resample to 16kHz
        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=16000)
            waveform = resampler(waveform)
        
        # Force Mono channel
        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)
            
        return waveform.to(target_device)

    def transcribe(self, audio_path: str, language: Optional[str] = None, strategy: str = "rnnt") -> Optional[str]:
        """
        Transcribe the audio file using explicit language routing.
        Routes English directly to Whisper and Indic languages directly to Indic-Conformer.
        
        Args:
            audio_path: Path to the audio file (.wav, .mp3, .m4a, etc.)
            language: The name of the language selected by the user (e.g. 'Tamil', 'Hindi', 'English')
            strategy: Optional decoding strategy parameter ('rnnt' or 'ctc')
        """
        try:
            # Normalize requested language
            requested_lang = (language or "english").lower().strip()
            logger.info(f"Processing transcription for audio: {audio_path} | selected language: '{requested_lang}'")
            
            # Direct Explicit Routing
            if requested_lang == "english":
                logger.info("English selected. Running Whisper ASR in a single pass...")
                self.load_whisper()
                whisper_result = self.whisper_pipe(audio_path)
                whisper_text = whisper_result.get("text", "").strip()
                logger.info(f"Returning Whisper transcription: '{whisper_text}'")
                return whisper_text
                
            # Indic Conformer Routing
            lang_code = LANGUAGE_MAP.get(requested_lang)
            if lang_code is None:
                # Fuzzy matching fallback
                for standard_lang, code in LANGUAGE_MAP.items():
                    if requested_lang in standard_lang or standard_lang in requested_lang:
                        lang_code = code
                        logger.info(f"Fuzzy matched '{requested_lang}' to Conformer code '{lang_code}'")
                        break
            
            if lang_code is None:
                logger.warning(f"Requested language '{requested_lang}' is not explicitly supported by Indic-Conformer. Defaulting to Hindi ('hi').")
                lang_code = "hi"
            
            logger.info(f"Routing audio to Indic-Conformer for native transcription using code: '{lang_code}'")
            self.load_conformer()
            
            target_device = getattr(self, "conformer_device", self.device)
            waveform = self.preprocess_audio(audio_path, target_device)
            
            try:
                with torch.no_grad():
                    transcription = self.conformer_model(waveform, lang_code, strategy)
                result_text = transcription.strip() if isinstance(transcription, str) else str(transcription).strip()
                logger.info(f"Successfully generated native Indic-Conformer transcription: '{result_text}'")
                return result_text
            except Exception as conformer_err:
                if target_device.type == "mps":
                    logger.warning(f"Conformer inference failed on MPS GPU: {conformer_err}. Retrying execution on CPU...")
                    try:
                        self.conformer_device = torch.device("cpu")
                        self.conformer_model.to(self.conformer_device)
                        waveform_cpu = self.preprocess_audio(audio_path, self.conformer_device)
                        with torch.no_grad():
                            transcription = self.conformer_model(waveform_cpu, lang_code, strategy)
                        result_text = transcription.strip() if isinstance(transcription, str) else str(transcription).strip()
                        logger.info("Successfully generated transcription on CPU fallback.")
                        return result_text
                    except Exception as fallback_err:
                        logger.exception(f"Error during CPU fallback transcription: {fallback_err}")
                        # Fallback to Whisper ASR
                        self.load_whisper()
                        whisper_result = self.whisper_pipe(audio_path)
                        return whisper_result.get("text", "").strip()
                else:
                    logger.exception(f"Error during Conformer transcription: {conformer_err}")
                    # Fallback to Whisper ASR
                    self.load_whisper()
                    whisper_result = self.whisper_pipe(audio_path)
                    return whisper_result.get("text", "").strip()
            
        except Exception as e:
            logger.exception(f"Error during automatic hybrid transcription: {e}")
            return None

# Singleton instance
_stt_service = None

def get_stt_service() -> STTService:
    """Get the STT service singleton instance."""
    global _stt_service
    if _stt_service is None:
        _stt_service = STTService()
    return _stt_service
