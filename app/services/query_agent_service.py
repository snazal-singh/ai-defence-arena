"""
This module implements both standard and creative query processing modes,
automatically selecting the appropriate approach based on user preferences.
"""

import logging
import re
import time
import os
from typing import Dict, Any, List, Optional, Tuple
from werkzeug.utils import secure_filename
import os
import glob
import json

from app.services.query_intent_service import get_query_intent_service, QueryIntent
from app.services.context_provider_service import get_context_provider_service
from app.services.response_generator_service import get_response_generator_service

# Import chat history services
from app.services.chat_history_manager import get_chat_history_manager
from app.services.chat_context_service import get_chat_context_service

# Import creative reasoning service
try:
    from app.services.creative_reasoning_service import get_creative_reasoning_service
    CREATIVE_MODE_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Creative reasoning service not available: {e}")
    CREATIVE_MODE_AVAILABLE = False

# Configure logging
logger = logging.getLogger(__name__)

class QueryAgentService:
    """Query processing service with chat context integration and adaptive creative mode."""
    
    def __init__(self):
        """Initialize the query agent service."""
        logger.info("Initializing query agent service")
        self.intent_service = get_query_intent_service()
        self.context_service = get_context_provider_service()
        self.response_service = get_response_generator_service()
        self.chat_history_manager = get_chat_history_manager()
        self.chat_context_service = get_chat_context_service()
        
        # Initialize creative reasoning service if available
        if CREATIVE_MODE_AVAILABLE:
            try:
                self.creative_service = get_creative_reasoning_service()
                logger.info("Creative reasoning service initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize creative reasoning service: {e}")
                self.creative_service = None
        else:
            self.creative_service = None
            logger.info("Creative reasoning service not available")
    
    def process_no_context_query(self, user_query: str, user_email: str,
                          input_language: str = 'en', output_language: str = 'en',
                          original_query: str = None) -> Dict[str, Any]:
        """
        Process a query when no document context is available.
        """
        # Get language name for response
        language = self._get_language(output_language)
        logger.info(f'Processing no-context query: "{user_query}" for user {user_email}')
        
        # Get list of available sessions for this user
        available_sessions = self._get_available_sessions(user_email)
        
        # Generate a response that guides the user to upload files or select a session
        return self._generate_no_context_response(user_query, user_email, available_sessions, language)
        
    def process_query(self, user_query: str, user_session: str,
                    input_language: str = 'en', output_language: str = 'en',
                    filenames: Optional[List[str]] = None,
                    has_csvxl: bool = False, mode: str = 'default',
                    is_trial: bool = False, chat_id: str = None,
                    image_url: str = None, image_caption: str = None,
                    original_query: str = None) -> Dict[str, Any]:
        """
        Process a user query with support for both standard and creative modes.
        
        Args:
            user_query: The user's query text
            user_session: User's session identifier
            input_language: Input language code
            output_language: Output language code
            filenames: List of filenames to filter results by
            has_csvxl: Flag for CSV/Excel data
            mode: Processing mode ('default' or 'creative')
            is_trial: Whether this is a trial user
            chat_id: Chat identifier within the session
            
        Returns:
            Response data
        """
        start_time = time.time()
        logger.info(f'Processing query: "{user_query}" for session {user_session}, chat {chat_id}, mode: {mode}')
        
        # Get language name for response
        language = self._get_language(output_language)
        
        # Parse user session to get email and session_id
        user_email, session_id = self._parse_user_session(user_session)
        
        # Check available resources for this session
        resources = self.context_service.check_resources_exist(user_session)
        logger.info(f"Available resources: {resources}")
        
        # Always update has_csvxl based on actual resource availability
        has_csvxl = has_csvxl or resources.get('has_data_tables', False)
        
        # Get chat context if needed
        chat_context = self._get_chat_context_if_needed(user_query, user_session, resources, chat_id)
        
        # Determine if creative mode should be used
        if self._should_use_creative_mode(mode, user_query, resources, is_trial):
            logger.info("Using creative reasoning mode")
            response = self._process_creative_query(
                user_query, user_session, resources, 
                input_language, output_language, filenames, chat_context
            )
        else:
            # Use standard processing mode
            logger.info("Using standard processing mode")
            response = self._process_standard_query(
                user_query, user_session, resources, language, 
                filenames, has_csvxl, chat_context
            )

        # Save conversation turn to chat history with chat_id
        assistant_response_text = response.get("answer", "")
        # Save conversation turn to chat history with chat_id
        # assistant_response_text = response.get("answer", "")
        response["image_url"] = image_url
        response["image_caption"] = image_caption
        
        # Determine query type based on response structure
        query_type = "general"
        
        # Determine query type based on response structure
        query_type = "general"
        if "fileName" in response:
            query_type = "document"
        elif "Data Context" in assistant_response_text:
            query_type = "data"
        elif response.get("creative_reasoning"):
            query_type = "creative"

        # Save and get assistant message ID
        # Use original_query (pre-translation Indic text) if provided, so chat history
        # shows the user's language rather than the translated English version.
        stored_user_query = original_query if original_query else user_query
        assistant_message_id = self.chat_history_manager.save_conversation_turn(
            user_session=user_session,
            user_query=stored_user_query,
            assistant_response=assistant_response_text,
            chat_id=chat_id,
            query_type=query_type,
            context_used=chat_context.get("context_used", False) if chat_context else False,
            image_url=response.get("image_url"),
            image_caption=response.get("image_caption"),
            metadata={
                "processing_time": response.get("processing_metadata", {}).get("processing_time"),
                "mode": response.get("creative_reasoning", {}).get("strategy_used", "standard")
            }
        )

        # Add assistant message ID to response
        if assistant_message_id:
            response["assistant_message_id"] = assistant_message_id
        
        # Add chat context metadata to response if used
        if chat_context and chat_context.get("context_used"):
            response["chat_context_used"] = {
                "context_type": chat_context.get("context_type", "unknown"),
                "confidence": chat_context.get("confidence", 0.0),
                "messages_referenced": chat_context.get("messages_used", 0),
                "chat_id": chat_id
            }
        
        return response
    
    def _get_chat_context_if_needed(self, user_query: str, user_session: str, 
                                   resources: Dict[str, bool], chat_id: str = None) -> Optional[Dict[str, Any]]:
        """Determine if chat context is needed and extract it if necessary."""
        try:
            # Check if session has chat history for this specific chat
            session_stats = self.chat_history_manager.get_session_stats(user_session, chat_id)
            
            # Handle error cases from session stats
            if "error" in session_stats:
                logger.warning(f"Chat history error: {session_stats['error']}")
                return {
                    "context_used": False,
                    "reasoning": f"Chat history unavailable: {session_stats['error']}"
                }
            
            if not session_stats.get("exists", False) or session_stats.get("total_messages", 0) == 0:
                logger.debug(f"No chat history available for context in chat {chat_id}")
                return {
                    "context_used": False,
                    "reasoning": "No chat history available"
                }
            
            # Detect if context is needed
            context_detection = self.chat_context_service.detect_context_need(
                user_query, session_history_available=True
            )
            
            if not context_detection.get("needs_context", False):
                logger.debug("Query doesn't need chat context")
                return {
                    "context_used": False,
                    "reasoning": context_detection.get("reasoning", "No context needed")
                }
            
            # Extract relevant context for this specific chat
            chat_session = self.chat_history_manager._get_session(user_session, chat_id)
            if not chat_session:
                logger.warning("Could not retrieve chat session despite stats indicating existence")
                return {
                    "context_used": False,
                    "reasoning": "Failed to retrieve chat session"
                }
            
            # Convert chat messages to simple format for context extraction
            try:
                chat_history = [msg.to_dict() for msg in chat_session.messages]
            except Exception as e:
                logger.error(f"Error converting chat messages to dict: {e}")
                return {
                    "context_used": False,
                    "reasoning": f"Error processing chat history: {str(e)}"
                }
            
            context_info = self.chat_context_service.extract_relevant_context(
                chat_history, user_query, context_detection["context_type"]
            )
            
            logger.info(f"Extracted chat context for chat {chat_id}: {context_info['messages_used']} messages, "
                       f"{context_info['token_count']} tokens")
            
            return {
                "context_used": True,
                "context": context_info["context"],
                "context_type": context_detection["context_type"],
                "confidence": context_detection["confidence"],
                "token_count": context_info["token_count"],
                "messages_used": context_info["messages_used"],
                "reasoning": context_detection["reasoning"],
                "chat_id": chat_id
            }
            
        except Exception as e:
            logger.error(f"Error getting chat context: {e}")
            return {
                "context_used": False,
                "reasoning": f"Error processing chat context: {str(e)}"
            }
    
    def _should_use_creative_mode(self, mode: str, user_query: str, 
                                resources: Dict[str, bool], is_trial: bool) -> bool:
        """Determine if creative mode should be used for this query."""
        # Creative mode is explicitly requested
        if mode != 'creative':
            return False
        
        # Check if creative service is available
        if not CREATIVE_MODE_AVAILABLE or self.creative_service is None:
            logger.warning("Creative mode requested but service not available")
            return False
        
        # Don't use creative mode for trial users (could be resource intensive)
        if is_trial:
            logger.info("Creative mode disabled for trial users")
            return False
        
        # Need some resources available for creative mode to be useful
        if not any(resources.values()):
            logger.info("No resources available, skipping creative mode")
            return False
        
        # Check if query is substantial enough for creative mode
        if len(user_query.split()) < 3:
            logger.info("Query too simple for creative mode")
            return False
        
        return True
    
    def _process_creative_query(self, user_query: str, user_session: str,
                              resources: Dict[str, bool],
                              input_language: str, output_language: str,
                              filenames: Optional[List[str]] = None,
                              chat_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Process query using creative reasoning mode with adaptive search."""
        try:
            response = self.creative_service.process_creative_query(
                user_query=user_query,
                user_session=user_session,
                available_resources=resources,
                input_language=input_language,
                output_language=output_language,
                filenames=filenames,
                chat_context=chat_context
            )
            
            return response
            
        except Exception as e:
            logger.error(f'Error in creative mode processing: {e}')
            
            # Fallback to standard processing
            logger.info("Falling back to standard processing mode")
            language = self._get_language(output_language)
            return self._process_standard_query(
                user_query, user_session, resources, language, filenames, 
                resources.get('has_data_tables', False), chat_context
            )
    
    def _process_standard_query(self, user_query: str, user_session: str,
                          resources: Dict[str, bool], language: Optional[str],
                          filenames: Optional[List[str]], has_csvxl: bool,
                          chat_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    
        enhanced_query = user_query
        if chat_context and chat_context.get("context_used"):
            context_text = chat_context.get("context", "")
            enhanced_query = f"{user_query}\n\nContext from previous conversation:\n{context_text}"

        # ADD THIS - Force DOCUMENT intent if image description present
        if "\n\nImage Description:" in user_query:
            logger.info("Image query detected - forcing DOCUMENT intent")
            return self._process_document_query(enhanced_query, user_session, language, chat_context)

        # Classify query intent
        intent, confidence = self.intent_service.classify_intent(
            enhanced_query,
            has_documents=resources.get('has_documents', False),
            has_data_tables=has_csvxl
        )
        logger.info(f'Query intent classification: {intent.name} with confidence {confidence}')

    
        
        # For general chat queries when documents are available, use document-aware chat
        if intent == QueryIntent.GENERAL_CHAT and resources.get('has_documents', False):
            return self._process_document_aware_chat(enhanced_query, user_session, language, filenames, chat_context)
        
        # Process based on query intent
        if intent == QueryIntent.GENERAL_CHAT:
            return self._process_general_chat(enhanced_query, language, chat_context)
            
        elif intent == QueryIntent.SUMMARY:
            return self._process_summary_query(enhanced_query, user_session, language, filenames, chat_context)
            
        elif intent == QueryIntent.DOCUMENT:
            return self._process_document_query(enhanced_query, user_session, language, chat_context)
            
        elif intent == QueryIntent.DATA_QUERY:
            return self._process_data_query(enhanced_query, user_session, language, chat_context)
            
        elif intent == QueryIntent.HYBRID:
            return self._process_hybrid_query(enhanced_query, user_session, language, chat_context)
            
        # Fallback to general response if no specific handler
        return self._process_general_chat(enhanced_query, language, chat_context)
    
    def _process_general_chat(self, user_query: str, language: Optional[str] = None,
                            chat_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Process a general chat query with optional chat context."""
        return self.response_service.generate_general_chat_response(user_query, language, chat_context)
        
    def _process_summary_query(self, user_query: str, user_session: str, 
                             language: Optional[str] = None,
                             filenames: Optional[List[str]] = None,
                             chat_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Process a summary query with chat context."""
        # Convert filenames to folder names if provided
        folder_names = []
        if filenames and len(filenames) > 0:
            for filename in filenames:
                # Convert filename to secure folder name format
                safe_folder_name = secure_filename(os.path.splitext(filename)[0])
                if safe_folder_name:
                    folder_names.append(safe_folder_name)
                    
        logger.info(f"Using folder names for summary: {folder_names}")
                    
        # Get summary context
        try:
            summary = self.context_service.get_summary_context(
                user_session, user_query, language, folder_names
            )
            return {
                "answer": summary,
                "questions": [
                    "What are the most important takeaways from this summary?",
                    "Can you elaborate on any specific findings mentioned?",
                    "What are the practical implications of these insights?"
                ]
            }
        except Exception as e:
            logger.error(f'Error generating summary: {e}')
            return {
                "answer": self.response_service._translate_response(
                    "I encountered an error while generating the summary. Please try again later.",
                    language,
                ),
                "questions": []
            }
            
    def _process_document_query(self, user_query: str, user_session: str, 
                              language: Optional[str] = None,
                              chat_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Process a document query with chat context."""
        try:
            # Get document context
            context = self.context_service.get_document_context(
                user_session, user_query, chat_context=chat_context
            )
            
            # If no context found, return a message about no relevant documents
            if not context:
                return {
                    "answer": self.response_service._translate_response(
                        "I couldn't find any relevant information in your documents to answer this question. Could you try rephrasing your query or asking about another topic?",
                        language,
                    ),
                }
                
            # Generate response with chat context
            response = self.response_service.generate_document_response(
                user_query, context, language, chat_context
            )

            chunks = []
            for m in re.finditer(
                r'\[(\d+)\]\s+"(.*?)"\s*\n\(Source:\s*(.*?),\s*Page\s*(\S+)\)',
                context,
                re.DOTALL,
            ):
                chunks.append({
                    "index": int(m.group(1)),
                    "text": m.group(2).strip(),
                    "source": m.group(3).strip(),
                    "page": m.group(4).rstrip(")").strip(),
                })
            response["context"] = chunks
            return response
        except Exception as e:
            logger.error(f'Error processing document query: {e}')
            return {
                "answer": self.response_service._translate_response(
                    f"I encountered an error while processing your document: {str(e)}. Please try a different question or contact support if the issue persists.",
                    language,
                ),
            }
        
    def _process_data_query(self, user_query: str, user_session: str, 
                          language: Optional[str] = None,
                          chat_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Process a data query with chat context."""
        # Get SQL context
        sql_context = self.context_service.get_data_context(user_session, user_query)
        
        # If no SQL context found, return a message about no relevant data
        if not sql_context:
            return {
                "answer": self.response_service._translate_response(
                    "I couldn't find any relevant data in your spreadsheets or CSV files to answer this question. Could you try rephrasing your query or asking about another topic?",
                    language,
                ),
                "questions": []
            }
            
        # Generate response with chat context
        response = self.response_service.generate_data_response(
            user_query, sql_context, language, chat_context
        )
        
        return response
        
    def _process_hybrid_query(self, user_query: str, user_session: str, 
                            language: Optional[str] = None,
                            chat_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Process a hybrid query needing both document and data contexts."""
        # Get both document and SQL contexts
        document_context = self.context_service.get_document_context(
            user_session, user_query, chat_context=chat_context
        )
        
        sql_context = self.context_service.get_data_context(user_session, user_query)
        
        # If neither context found, return a message about no relevant information
        if not document_context and not sql_context:
            return {
                "answer": self.response_service._translate_response(
                    "I couldn't find any relevant information in your documents or data to answer this question. Could you try rephrasing your query or asking about another topic?",
                    language,
                ),
                "questions": []
            }
            
        # Generate response with chat context
        response = self.response_service.generate_hybrid_response(
            user_query, document_context, sql_context, language, chat_context
        )
        
        return response
        
    def _process_document_aware_chat(self, user_query: str, user_session: str,
                               language: Optional[str] = None,
                               filenames: Optional[List[str]] = None,
                               chat_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Process a general chat query when documents are available."""
        logger.info(f"Processing document-aware general chat: {user_query}")
        
        # Get basic information about the available documents
        documents_info = self._get_documents_info(user_session, filenames)
        
        # Generate response with chat context
        response = self.response_service.generate_document_aware_chat_response(
            user_query, documents_info, language, chat_context
        )
        
        return response
    
    def _parse_user_session(self, user_session: str) -> Tuple[str, str]:
        """Parse user_session to extract email and session_id."""
        try:
            # Assuming format: email + session_id
            # Find the last occurrence of @ to split properly
            at_index = user_session.rfind('@')
            if at_index == -1:
                # Fallback: treat as session_id only
                return user_session, "default"
            
            # Find the next part after domain to get session_id
            parts = user_session[at_index:].split('.')
            if len(parts) >= 2:
                # Find where email ends and session starts
                domain_part = parts[1] if len(parts) > 1 else parts[0]
                session_start = user_session.find(domain_part) + len(domain_part)
                email = user_session[:session_start]
                session_id = user_session[session_start:]
                return email, session_id
            
            # Fallback
            return user_session, "default"
            
        except Exception as e:
            logger.error(f"Error parsing user session: {e}")
            return user_session, "default"
    
    def _get_available_sessions(self, user_email: str) -> List[str]:
        """Get a list of available sessions for a user."""
        try:            
            # Pattern to match user sessions - adjust as needed based on your storage structure
            pattern = f'users/{user_email}*'
            sessions = glob.glob(pattern)
            
            # Extract session identifiers
            return [os.path.basename(s) for s in sessions]
        except Exception as e:
            logger.error(f'Error getting available sessions: {e}')
            return []
    
    def _generate_no_context_response(self, user_query: str, user_email: str,
                                   available_sessions: List[str], language: str) -> Dict[str, Any]:
        """Generate a response for a user who hasn't selected a document context."""
        prompt = f"""You are a chat bot called icarKno created by Carnot Research Pvt Ltd, which answers queries related to documents.
        
        The user is currently in the main chat interface but hasn't selected any specific documents or knowledge containers.
        
        Answer the user's question in a helpful, conversational tone. Since no documents are currently selected, you should:
        
        1. Respond naturally to general questions
        2. For document-specific questions, politely remind them to select a knowledge container from the left sidebar or upload new files
        3. Mention that they have {len(available_sessions)} existing knowledge containers they can choose from (if they have any)
        4. Be specific about how to upload new files (click the "New Container" button) or select existing containers (from the left menu)
        
        User's question: {user_query}
        
        Keep your response concise, helpful and focused on guiding the user without being overly repetitive or robotic.
        """
        
        # Add language in prompt if not English
        if language:
            prompt = prompt + f"\n\nAnswer in the user's preferred language - {language}."
        else:
            prompt = prompt + f"\n\nAnswer in the same language as the user's question"
            
        # Generate response
        try:
            llm_response = self.response_service.llm.invoke(prompt)
            response = str(llm_response.content)
            
            return {
                "answer": response,
                "questions": []
            }
        except Exception as e:
            logger.error(f'Error generating no-context response: {e}')
            return {
                "answer": self.response_service._translate_response(
                    "I'm here to help you explore your documents. Please select a knowledge container from the left sidebar or upload new documents to get started.",
                    language,
                ),
                "questions": []
            }
    
    def _get_documents_info(self, user_session: str, 
                          filenames: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get basic information about available documents."""
        try:
            # Get information about available files
            file_count = 0
            file_types = set()
            topics = "various"
            
            # Check files directory
            files_dir = os.path.join('users', user_session, 'files')
            if os.path.exists(files_dir):
                # If filenames are provided, filter to those specific files
                if filenames and len(filenames) > 0:
                    for filename in filenames:
                        # Extract file extension
                        ext = os.path.splitext(filename)[1].lower()
                        if ext:
                            file_types.add(ext[1:])  # Remove the dot
                    file_count = len(filenames)
                else:
                    # Count all files in the directory
                    file_dirs = glob.glob(os.path.join(files_dir, '*'))
                    file_count = len(file_dirs)
                    
                    # Get file types
                    for file_dir in file_dirs:
                        metadata_path = os.path.join(file_dir, 'metadata.json')
                        if os.path.exists(metadata_path):
                            with open(metadata_path, 'r') as f:
                                metadata = json.load(f)
                                filename = metadata.get('filename', '')
                                if filename:
                                    ext = os.path.splitext(filename)[1].lower()
                                    if ext:
                                        file_types.add(ext[1:])  # Remove the dot
            
            # Check for legacy content.txt
            legacy_content = os.path.join('users', user_session, 'content.txt')
            if os.path.exists(legacy_content):
                file_count += 1
                file_types.add('txt')
            
            # Check for SQL/Excel files
            sheet_metadata_path = os.path.join('users', user_session, "files", "sheet_metadata.json")
            if os.path.exists(sheet_metadata_path):
                with open(sheet_metadata_path, 'r') as f:
                    metadata = json.load(f)
                    for filename in metadata:
                        ext = os.path.splitext(filename)[1].lower()
                        if ext:
                            file_types.add(ext[1:])  # Remove the dot
                        file_count += 1
            
            return {
                "file_count": file_count,
                "file_types": list(file_types) if file_types else ["document"],
                "topics": topics
            }
        except Exception as e:
            logger.error(f"Error getting document info: {e}")
            return {
                "file_count": "multiple",
                "file_types": ["document"],
                "topics": "various"
            }
            
    def _get_language(self, lang_code: str) -> str:
        """Get the language display name from an ISO 639-1/3 code."""
        from utils.translation import ISO_TO_NAME
        return ISO_TO_NAME.get(str(lang_code).lower(), 'English')
    
    def get_supported_modes(self) -> Dict[str, Any]:
        """Get information about supported query processing modes."""
        modes = {
            "default": {
                "name": "Standard Mode",
                "description": "Fast, efficient query processing with intent classification and chat history support",
                "processing_time": "1-5 seconds",
                "best_for": ["Simple questions", "Quick lookups", "Direct answers", "Follow-up questions"]
            }
        }
        
        if CREATIVE_MODE_AVAILABLE and self.creative_service is not None:
            modes["creative"] = self.creative_service.get_creative_mode_info()
        
        return modes
    
    def get_chat_history_stats(self, user_session: str, chat_id: str = None) -> Dict[str, Any]:
        """Get chat history statistics for a session and specific chat."""
        try:
            return self.chat_history_manager.get_session_stats(user_session, chat_id)
        except Exception as e:
            logger.error(f"Error getting chat history stats: {e}")
            return {"exists": False, "error": str(e)}
    
    def clear_chat_history(self, user_session: str, chat_id: str = None) -> bool:
        """Clear chat history for a specific chat in a session."""
        try:
            return self.chat_history_manager.delete_session(user_session, chat_id)
        except Exception as e:
            logger.error(f"Error clearing chat history: {e}")
            return False


# Create a singleton instance
_query_agent_service = None

def get_query_agent_service() -> QueryAgentService:
    """Get the query agent service singleton instance."""
    global _query_agent_service
    if _query_agent_service is None:
        _query_agent_service = QueryAgentService()
    return _query_agent_service