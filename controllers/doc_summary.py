"""
Document summarization module.

This module provides functions for:
- Extracting important sentences from documents
- Creating abstractive summaries using LLMs
- Managing summaries for individual files
"""

# Standard library imports
import json
import logging
import os
import re
import glob
import time
from typing import List, Optional

# Third-party imports
from summarizer import Summarizer

# Local imports
from app.services.llm_service import get_fast_llm
from app.core.config import settings
from utils.translation import translate_to_indic

# Configure logging
logger = logging.getLogger(__name__)

class DocumentSummaryService:
    """Service for document summarization and management."""
    
    def __init__(self):
        """Initialize the document summary service."""
        logger.info("Initializing document summary service")
        self.bert_model = Summarizer()
        # Use fast LLM for summary generation
        self.llm = get_fast_llm()
        
        # Default character limit for fallback content
        self.fallback_char_limit = settings.SUMMARY_FALLBACK_CHAR_LIMIT
        # Dynamic summary configuration
        self.min_sentences = settings.SUMMARY_MIN_SENTENCES
        self.max_sentences = settings.SUMMARY_MAX_SENTENCES
        self.extraction_ratio = settings.SUMMARY_EXTRACTION_RATIO
        self.BASE_USERS_DIR = settings.BASE_USERS_DIR
    
    def create_abstractive_summary(self, user_session: str) -> None:
        """
        Create abstractive summaries for all files in a session.
        
        Args:
            user_session (str): User's session identifier
        """
        logger.info(f'Creating abstractive summaries for user session: {user_session}')
        
        # Define the files directory path
        files_dir = os.path.join(self.BASE_USERS_DIR, user_session, 'files')
        
        # Check if files directory exists
        if not os.path.exists(files_dir):
            logger.info(f"{files_dir} files directory not found for session {user_session}")
            return
        
        # Get all file directories
        file_dirs = glob.glob(os.path.join(files_dir, '*'))
        logger.info(f"Found {len(file_dirs)} file directories")
        
        # Process each file directory
        for file_dir in file_dirs:
            # Get folder_name from directory name
            folder_name = os.path.basename(file_dir)
            
            # Try to create summary for this file
            try:
                self._create_file_summary(user_session, folder_name)
                logger.info(f'Created summary for file in folder {folder_name}')
            except Exception as e:
                logger.error(f'Error creating summary for file in folder {folder_name}: {e}')
    
    def _count_sentences(self, text: str) -> int:
        """
        Count the number of sentences in the text using multiple methods.
        
        Args:
            text (str): Text to analyze
            
        Returns:
            int: Number of sentences
        """
        if not text:
            return 0
        
        # Method 1: More sophisticated sentence boundary detection
        # Handle abbreviations and decimal numbers
        sentences = re.split(r'(?<![A-Z][a-z]\.)|(?<=\d)\.(?!\d)|(?<=[a-z])\.(?=\s[A-Z])|[!?]+', text)
        sentence_count = len([s for s in sentences if s.strip() and len(s.strip()) > 10])
        
        # Method 2: Simple line-based counting for structured content
        lines = text.split('\n')
        meaningful_lines = [line for line in lines if line.strip() and len(line.strip()) > 20]
        line_count = len(meaningful_lines)
        
        estimated_sentences = max(sentence_count, line_count // 2)
        
        return estimated_sentences
    
    def _calculate_dynamic_sentence_count(self, text: str) -> int:
        """
        Calculate the optimal number of sentences to extract based on content length.
        
        Args:
            text (str): Full text content
            
        Returns:
            int: Number of sentences to extract
        """
        total_sentences = self._count_sentences(text)
        
        # Calculate target extraction count
        target_sentences = max(
            self.min_sentences,  # At least minimum sentences
            min(
                int(total_sentences * self.extraction_ratio),  # 35% of total
                self.max_sentences  # But not more than maximum
            )
        )
        
        # Adjust based on content characteristics
        avg_sentence_length = len(text) / max(total_sentences, 1)
        
        # If sentences are very long (technical content), extract fewer
        if avg_sentence_length > 200:
            target_sentences = int(target_sentences * 0.8)
        # If sentences are short (bullet points, lists), extract more
        elif avg_sentence_length < 80:
            target_sentences = int(target_sentences * 1.2)
        
        # Final bounds checking
        final_count = max(
            self.min_sentences,
            min(target_sentences, self.max_sentences, total_sentences)
        )
        
        logger.info(f"Dynamic sentence calculation: total={total_sentences}, "
                   f"target={target_sentences}, final={final_count}, "
                   f"avg_length={avg_sentence_length:.1f}")
        
        return final_count
    
    def _create_file_summary(self, user_session: str, folder_name: str) -> None:
        """
        Create summary for a specific file.
        
        Args:
            user_session (str): User's session identifier
            folder_name (str): Name of the folder containing the file
        """
        # Define file paths
        file_dir = os.path.join(self.BASE_USERS_DIR, user_session, 'files', folder_name)
        content_path = os.path.join(file_dir, 'content.txt')
        summary_path = os.path.join(file_dir, 'imp_sents.txt')
        
        # Check if content file exists
        if not os.path.exists(content_path):
            logger.warning(f'Content file not found for file {folder_name}')
            raise FileNotFoundError(f'Content file not found for file {folder_name}')
        
        # Read the text from file
        with open(content_path, "r", encoding='utf8') as file:
            full_text = file.read()
        
        # Calculate dynamic sentence count based on content
        sentence_count = self._calculate_dynamic_sentence_count(full_text)
        
        # Use BERT extractive summarizer model with calculated count
        most_important_sents = self.bert_model(full_text, num_sentences=sentence_count)
        
        # Save the most important sentences to a file
        with open(summary_path, 'w', encoding='utf8') as file:
            file.write(''.join(most_important_sents))
        
        # Update metadata to include summary status
        self._update_file_metadata(file_dir, summary_path, sentence_count, len(full_text))
        
        logger.info(f'Created summary with {sentence_count} sentences for file {folder_name}')

    
    def _update_file_metadata(self, file_dir: str, summary_path: str, 
                            sentence_count: int, content_length: int) -> None:
        """
        Update file metadata with summary information.
        
        Args:
            file_dir (str): Directory containing the file
            summary_path (str): Path to the summary file
        """
        metadata_path = os.path.join(file_dir, 'metadata.json')
        if os.path.exists(metadata_path):
            with open(metadata_path, 'r', encoding='utf8') as file:
                metadata = json.load(file)
        else:
            metadata = {}
        
        metadata.update({
            'has_summary': True,
            'summary_created_at': os.path.getmtime(summary_path),
            'summary_sentence_count': sentence_count,
            'original_content_length': content_length
        })
        
        with open(metadata_path, 'w', encoding='utf8') as file:
            json.dump(metadata, file)
            
        logger.debug(f"Updated metadata with summary information")
    
    def summarize_document(self, query: str, user_session: str, language: Optional[str] = None, 
                           folder_names: Optional[List[str]] = None) -> str:
        """
        Create a detailed abstractive summary from important sentences based on a query.
        
        Args:
            query (str): User's query for the summary
            user_session (str): User's session identifier
            language (str, optional): Language for the summary
            folder_names (list, optional): List of folder names to include in the summary
            
        Returns:
            str: Enhanced abstractive summary of the document
            
        Raises:
            Exception: If no text can be found for summarization
        """
        logger.info(f"Starting document summarization process with arguments: query, user_session, language, folder_names: {query}, {user_session}, {language}, {folder_names}")
        start_time = time.time()
        logger.info(f"Generating document summary for query: {query}")
        
        # Get important sentences from specified files or all files
        combined_text = self._get_combined_important_sentences(user_session, folder_names)
        
        if not combined_text:
            logger.warning("No text found for summarization")
            raise Exception("No text found for summarization. Please check if the files exist.")
        
        # Create abstractive summary using LLM (always in English, translate after)
        try:
            prompt = self._create_summary_prompt(query, combined_text)
            logger.info(f"Approx token count for prompt: {len(prompt.split()) * 1.33}")

            summary = self.llm.invoke(prompt)
            logger.info(f'Generated summary in {time.time() - start_time:.2f} seconds')

            content = summary.content
            if language and language.strip().lower() != "english":
                content = translate_to_indic(content, language)
            return content
        except Exception as e:
            logger.error(f'Error creating enhanced abstractive summary with LLM: {e}')
            raise Exception("Cannot create abstractive summary")
    
    def _get_combined_important_sentences(self, user_session: str, 
                                         folder_names: Optional[List[str]] = None) -> str:
        """
        Get combined important sentences from specified files or all files.
        Falls back to using direct content when important sentences are not available.
        
        Args:
            user_session (str): User's session identifier
            folder_names (list, optional): List of folder names to include
            
        Returns:
            str: Combined important sentences or document content
        """
        combined_text = ""
        
        # If specific folder names are provided, use only those files' important sentences
        if folder_names and isinstance(folder_names, list) and len(folder_names) > 0:
            logger.info(f"Getting important sentences from specified folders: {folder_names}")
            combined_text = self._get_sentences_from_specified_folders(user_session, folder_names)
        
        # If no specific folder name is provided or fallback is triggered, use all available files
        if not combined_text:
            logger.info("Getting important sentences from all files")
            combined_text = self._get_sentences_from_all_files(user_session)
        
        return combined_text
    
    def _get_sentences_from_specified_folders(self, user_session: str, folder_names: List[str]) -> str:
        """
        Get important sentences from specified folders.
        Falls back to content.txt if imp_sents.txt is not available.
        
        Args:
            user_session (str): User's session identifier
            folder_names (list): List of folder names to include
            
        Returns:
            str: Combined important sentences or document content
        """
        combined_text = ""
        files_dir = os.path.join(self.BASE_USERS_DIR, user_session, 'files')
        logger.info(f'_____________ files dir: {files_dir} ')
        found_any = False
        
        if os.path.exists(files_dir):
            # Process each provided folder name
            for folder_name in folder_names:
                imp_sents_path = os.path.join(self.BASE_USERS_DIR, user_session, 'files', folder_name, 'imp_sents.txt')
                content_path = os.path.join(self.BASE_USERS_DIR, user_session, 'files', folder_name, 'content.txt')
                metadata_path = os.path.join(self.BASE_USERS_DIR, user_session, 'files', folder_name, 'metadata.json')
                
                logger.info(f'Processing folder: {folder_name}')
                logger.info(f'Important sentences path: {imp_sents_path}')
                # Get filename from metadata or default to folder name
                filename = folder_name
                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, 'r', encoding='utf8') as meta_file:
                            metadata = json.load(meta_file)
                            filename = metadata.get('filename', folder_name)
                    except Exception as e:
                        logger.error(f"Error reading metadata for {folder_name}: {e}")
                
                # Try important sentences first
                if os.path.exists(imp_sents_path):
                    with open(imp_sents_path, "r", encoding='utf8') as file:
                        file_sentences = file.read()
                        if file_sentences:
                            combined_text += f"\n--- {filename} ---\n{file_sentences}\n"
                            logger.info(f"Added important sentences for {filename}")
                            found_any = True
                        else:
                            logger.warning(f"Empty important sentences file for {folder_name}")
                
                # Fall back to content.txt if imp_sents.txt doesn't exist or is empty
                elif os.path.exists(content_path):
                    file_content = self._get_content_from_file(content_path)
                    if file_content:
                        combined_text += f"\n--- {filename} (Direct Content) ---\n{file_content}\n"
                        logger.info(f"Added direct content for {filename} (fallback)")
                        found_any = True
                    else:
                        logger.warning(f"Empty content file for {folder_name}")
        
        # If no files were found with the specified folder names, return empty string
        if not found_any:
            logger.warning(f"No content found for specified folder names: {folder_names}")
            return ""
            
        return combined_text
    
    def _get_sentences_from_all_files(self, user_session: str) -> str:
        """
        Get important sentences from all files.
        Falls back to content.txt if imp_sents.txt is not available.
        
        Args:
            user_session (str): User's session identifier
            
        Returns:
            str: Combined important sentences or document content
        """
        # Check for legacy mode
        legacy_imp_sents_path = os.path.join(self.BASE_USERS_DIR, user_session, 'imp_sents.txt')
        legacy_content_path = os.path.join(self.BASE_USERS_DIR, user_session, 'content.txt')
        
        # Check legacy mode - session-level summary
        if os.path.exists(legacy_imp_sents_path):
            with open(legacy_imp_sents_path, "r", encoding='utf8') as file:
                return file.read()
        # Fall back to legacy content if important sentences don't exist
        elif os.path.exists(legacy_content_path):
            file_content = self._get_content_from_file(legacy_content_path)
            logger.info(f"Using direct content from legacy file (fallback)")
            return file_content
        
        # New approach: Combine important sentences from all files
        combined_text = ""
        files_dir = os.path.join(self.BASE_USERS_DIR, user_session, 'files')
        if os.path.exists(files_dir):
            file_dirs = glob.glob(os.path.join(files_dir, '*'))
            logger.info(f"Found {len(file_dirs)} file directories for summarization")
            
            # If no files found, return empty string
            if not file_dirs:
                logger.warning("No files found for summarization.")
                return ""
            
            # Process each file directory
            for file_dir in file_dirs:
                curr_folder_name = os.path.basename(file_dir)
                imp_sents_path = os.path.join(file_dir, 'imp_sents.txt')
                content_path = os.path.join(file_dir, 'content.txt')
                metadata_path = os.path.join(file_dir, 'metadata.json')
                
                # Filename from metadata or default to folder name
                filename = curr_folder_name
                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, 'r', encoding='utf8') as meta_file:
                            metadata = json.load(meta_file)
                            filename = metadata.get('filename', curr_folder_name)
                    except Exception as e:
                        logger.error(f"Error reading metadata for {curr_folder_name}: {e}")
                
                # Try important sentences first
                if os.path.exists(imp_sents_path):
                    with open(imp_sents_path, "r", encoding='utf8') as file:
                        file_sentences = file.read()
                        if not file_sentences:
                            logger.warning(f"Empty important sentences file for {curr_folder_name}")
                            continue
                            
                        # Add file identifier and its content
                        combined_text += f"\n--- {filename} ---\n{file_sentences}\n"
                        logger.info(f"Added important sentences for {filename}")
                
                # Fall back to content.txt if imp_sents.txt doesn't exist or is empty
                elif os.path.exists(content_path):
                    file_content = self._get_content_from_file(content_path)
                    if not file_content:
                        logger.warning(f"Empty content file for {curr_folder_name}")
                        continue
                        
                    # Add file identifier and its content
                    combined_text += f"\n--- {filename} (Direct Content) ---\n{file_content}\n"
                    logger.info(f"Added direct content for {filename} (fallback)")
        
        return combined_text
    
    def _get_content_from_file(self, content_path: str, max_chars: int = None) -> str:
        """
        Get a limited amount of content from a file.
        
        Args:
            content_path (str): Path to the content file
            max_chars (int, optional): Maximum number of characters to read
            
        Returns:
            str: Limited content from the file
        """
        if max_chars is None:
            max_chars = self.fallback_char_limit
            
        try:
            with open(content_path, "r", encoding='utf8') as file:
                content = file.read(max_chars)
                if len(content) >= max_chars:
                    # Add an ellipsis to indicate truncation
                    content = content + "..."
                return content
        except Exception as e:
            logger.error(f'Error reading content from {content_path}: {e}')
            return ""
            
    def _create_summary_prompt(self, query: str, sentences: str) -> str:
        """
        Create a prompt for the LLM to generate a summary.

        Args:
            query (str): User's query for the summary
            sentences (str): Important sentences to summarize

        Returns:
            str: Prompt for the LLM
        """
        prompt = f'''You are an expert document analyst tasked with creating comprehensive, detailed summaries from extracted important content.

Your goal is to provide a thorough, analytical summary that covers key aspects of the content while being well-organized and insightful.

INSTRUCTIONS:
• Analyze the provided content thoroughly and create a comprehensive summary
• Covermajor topics and themes present in the content
• Organize information logically with clear structure and natural formatting
• Highlight critical points with **bold text** and italics for emphasis, do not use headings
• Include specific details, numbers, percentages, dates, and examples where relevant
• Identify patterns, trends, and relationships within the content
• Use clear, professional language that demonstrates deep understanding
• When content spans multiple files, provide separate sections for each file with any similarities or differences noted

CONTENT TO ANALYZE:
{sentences}

USER'S SPECIFIC REQUEST:
{query}

ANALYSIS REQUIREMENTS:
• Ensure the summary is comprehensive yet focused on the user's request
• Do not mention about important sentences or extraction methods
• If multiple documents are involved, synthesize information across sources'''

        prompt += "\n\nProvide your analysis in English with professional clarity and depth."

        return prompt

# Create a singleton instance
_summary_service = None

def get_summary_service() -> DocumentSummaryService:
    """
    Get the document summary service singleton instance.
    
    Returns:
        DocumentSummaryService: The document summary service instance
    """
    global _summary_service
    if _summary_service is None:
        _summary_service = DocumentSummaryService()
    return _summary_service

# Keep these functions for backward compatibility
def create_abstractive_summary(user_session: str) -> None:
    """Legacy function to maintain backward compatibility."""
    return get_summary_service().create_abstractive_summary(user_session)

def summarize_document(query: str, user_session: str, language: Optional[str] = None, 
                      folder_names: Optional[List[str]] = None) -> str:
    """Legacy function to maintain backward compatibility."""
    return get_summary_service().summarize_document(query, user_session, language, folder_names)