"""
Chat History Manager Service with Chat Names.

This module handles storage, retrieval, and management of chat history using MongoDB.
Added support for chat names stored in a separate collection.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import re
import json
from pymongo import MongoClient, IndexModel, ASCENDING, DESCENDING
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from app.core.config import settings
from app.services.llm_service import get_fast_llm
from app.models.chat_models import ChatSession, ChatMessage, ChatContext, MessageRole, QueryType

# Configure logging
logger = logging.getLogger(__name__)

class ChatHistoryManager:
    """Manages chat history storage and retrieval using MongoDB with multiple chat support."""
    
    def __init__(self):
        """Initialize the chat history manager."""
        self.client = None
        self.db = None
        self.collection = None
        self.chat_names_collection = None  # New collection for chat names
        self.llm = get_fast_llm()
        
        # Configuration limits
        self.MAX_MESSAGES_PER_SESSION = 200
        self.MAX_TOKENS_PER_SESSION = 50000
        self.MAX_SESSION_AGE_DAYS = 30
        self.CONTEXT_DETECTION_THRESHOLD = 0.7
        self.DEFAULT_CHAT_ID = "default"
        
        # Initialize MongoDB connection
        self._initialize_mongodb()
        logger.info("Chat history manager initialized with multiple chat support")
    
    def _initialize_mongodb(self):
        """Initialize MongoDB connection with proper error handling."""
        try:
            # Create MongoDB client with timeout settings
            self.client = MongoClient(
                settings.MONGO_URL,
                serverSelectionTimeoutMS=5000,  # 5 second timeout
                connectTimeoutMS=5000,
                socketTimeoutMS=5000,
                maxPoolSize=10
            )
            
            # Test the connection
            self.client.admin.command('ping')
            
            # Use a dedicated database for chat history
            self.db = self.client.chat_history
            self.collection = self.db.sessions
            self.chat_names_collection = self.db.chat_names  # New collection for chat names
            
            # Create indexes for efficient queries
            self._create_indexes()
            
            logger.info("MongoDB connection established successfully")
            
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.error(f"Failed to connect to MongoDB at {settings.MONGO_URL}: {e}")
            logger.warning("Chat history will be disabled")
            self.client = None
            self.db = None
            self.collection = None
            self.chat_names_collection = None
        except Exception as e:
            logger.error(f"Unexpected MongoDB init error (type={type(e).__name__}): {e}")
            self.client = None
            self.db = None
            self.collection = None
            self.chat_names_collection = None
    
    def _create_indexes(self):
        """Create MongoDB indexes for efficient queries."""
        if not self._is_available():
            return
            
        try:
            # Drop existing conflicting indexes first
            try:
                self.collection.drop_index("user_session_1")
            except:
                pass  # Index might not exist
                
            indexes = [
                IndexModel([("chat_key", ASCENDING)], unique=True, name="chat_key_unique"),
                IndexModel([("user_session", ASCENDING)], name="user_session_index"),
                IndexModel([("chat_id", ASCENDING)], name="chat_id_index"),
                IndexModel([("updated_at", DESCENDING)], name="updated_at_desc"),
                IndexModel([("messages.timestamp", DESCENDING)], name="messages_timestamp_desc")
            ]
            self.collection.create_indexes(indexes)
            
            # Create indexes for chat names collection
            if self.chat_names_collection is not None:
                chat_name_indexes = [
                    IndexModel([("chat_key", ASCENDING)], unique=True, name="chat_name_key_unique"),
                    IndexModel([("user_session", ASCENDING)], name="chat_name_user_session_index"),
                    IndexModel([("chat_id", ASCENDING)], name="chat_name_chat_id_index"),
                    IndexModel([("updated_at", DESCENDING)], name="chat_name_updated_at_desc")
                ]
                self.chat_names_collection.create_indexes(chat_name_indexes)
            
            logger.debug("MongoDB indexes created successfully with chat_id support")
        except Exception as e:
            logger.error(f"Error creating indexes: {e}")
    
    def _get_chat_key(self, user_session: str, chat_id: str = None) -> str:
        """Generate composite key for user_session and chat_id."""
        if chat_id is None:
            chat_id = self.DEFAULT_CHAT_ID
        return f"{user_session}:{chat_id}"
    
    def _is_available(self) -> bool:
        """Check if MongoDB is available, attempting reconnect if needed."""
        if self.client is not None and self.db is not None and self.collection is not None:
            return True
        # Attempt reconnect if previously failed
        if settings.MONGO_URL:
            logger.info("MongoDB unavailable — attempting reconnect...")
            self._initialize_mongodb()
        return (self.client is not None and 
                self.db is not None and 
                self.collection is not None)

    def _generate_default_chat_name(self) -> str:
        """Generate a default chat name based on current time."""
        now = datetime.utcnow()
        return f"Chat {now.strftime('%Y-%m-%d %H:%M')}"

    def _create_chat_name_entry(self, user_session: str, chat_id: str, chat_name: str = None) -> bool:
        """Create a chat name entry in the chat_names collection."""
        if not self._is_available() or self.chat_names_collection is None:
            return False
            
        try:
            if chat_name is None:
                chat_name = self._generate_default_chat_name()
                
            chat_key = self._get_chat_key(user_session, chat_id)
            doc = {
                "chat_key": chat_key,
                "user_session": user_session,
                "chat_id": chat_id,
                "chat_name": chat_name,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            self.chat_names_collection.replace_one(
                {"chat_key": chat_key},
                doc,
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error creating chat name entry: {e}")
            return False

    def _get_chat_name(self, user_session: str, chat_id: str) -> Optional[str]:
        """Get chat name for a specific chat."""
        if not self._is_available() or self.chat_names_collection is None:
            return None
            
        try:
            chat_key = self._get_chat_key(user_session, chat_id)
            doc = self.chat_names_collection.find_one({"chat_key": chat_key})
            if doc:
                return doc.get("chat_name")
            return None
        except Exception as e:
            logger.error(f"Error getting chat name: {e}")
            return None

    def _get_all_chat_names(self, user_session: str) -> Dict[str, str]:
        """Get all chat names for a user session."""
        if not self._is_available() or self.chat_names_collection is None:
            return {}
            
        try:
            cursor = self.chat_names_collection.find(
                {"user_session": user_session},
                {"chat_id": 1, "chat_name": 1}
            )
            
            chat_names = {}
            for doc in cursor:
                chat_id = doc.get("chat_id")
                chat_name = doc.get("chat_name")
                if chat_id and chat_name:
                    chat_names[chat_id] = chat_name
            
            return chat_names
        except Exception as e:
            logger.error(f"Error getting all chat names: {e}")
            return {}

    # -------------------------------------------------
    # NEW – public API used by the /ask endpoint
    def store_user_message(self,
                           user_session: str,
                           chat_id: str,
                           role: MessageRole,
                           content: str,
                           image_caption: Optional[str] = None,
                           image_url: Optional[str] = None) -> bool:  # NEW param
        """
        Store a user message (or system-generated message) in the current chat session.
        The optional ``image_caption`` is persisted so later queries can reference it.
        The optional ``image_url`` stores the path to the saved image for chat history display.
        """
        try:
            # Load or create a session
            session = self._get_or_create_session(user_session, chat_id)

            # Build the ChatMessage object
            msg = ChatMessage(
                role=role,
                content=content,
                image_caption=image_caption,
                image_url=image_url,  # NEW
                timestamp=datetime.utcnow()
            )

            # Append and apply limits
            session.add_message(msg)
            self._apply_session_limits(session)
            return self._save_session(session)
        except Exception as e:
            logger.error(f"Error storing user message: {e}")
            return False

    def save_conversation_turn(self, user_session: str, user_query: str, assistant_response: str,
                              chat_id: str = None, query_type: str = "general",
                              context_used: bool = False, image_url: str = None,
                              image_caption: str = None, metadata: Dict = None) -> str:
        """
        Save a complete conversation turn (user query + assistant response).
        
        Returns:
            str: Assistant message ID if successful, None if failed
        """
        if not self._is_available():
            logger.warning("MongoDB not available, skipping chat history save")
            return None
            
        if chat_id is None:
            chat_id = self.DEFAULT_CHAT_ID
            
        try:
            # Calculate token counts (rough estimate)
            user_tokens = len(user_query.split()) * 1.3
            assistant_tokens = len(assistant_response.split()) * 1.3
            
            # Validate query_type
            try:
                query_type_enum = QueryType(query_type) if query_type in [q.value for q in QueryType] else QueryType.GENERAL
            except (ValueError, TypeError):
                query_type_enum = QueryType.GENERAL
            
            # Create messages
            user_message = ChatMessage(
                role=MessageRole.USER,
                content=user_query,
                query_type=query_type_enum,
                token_count=int(user_tokens),
                image_url=image_url,
                image_caption=image_caption,
                metadata=metadata or {}
            )
            
            assistant_message = ChatMessage(
                role=MessageRole.ASSISTANT,
                content=assistant_response,
                context_used=context_used,
                token_count=int(assistant_tokens),
                metadata=metadata or {}
            )
            
            # Get or create session
            session = self._get_or_create_session(user_session, chat_id)
            
            # Add messages
            session.add_message(user_message)
            session.add_message(assistant_message)
            
            # Apply limits before saving
            self._apply_session_limits(session)
            
            # Save to MongoDB
            success = self._save_session(session)
            
            if success:
                logger.debug(f"Saved conversation turn for chat {self._get_chat_key(user_session, chat_id)}")
                return assistant_message.message_id  # Return assistant message ID
            else:
                logger.warning(f"Failed to save conversation turn for chat {self._get_chat_key(user_session, chat_id)}")
                return None
                
        except Exception as e:
            logger.error(f"Error saving conversation turn: {e}")
            return None
    
    def get_chat_context(self, user_session: str, current_query: str, chat_id: str = None) -> ChatContext:
        """
        Get relevant chat context for the current query.
        
        Args:
            user_session: User session identifier
            current_query: Current user query
            chat_id: Chat identifier within the session
            
        Returns:
            ChatContext with relevant information
        """
        if not self._is_available():
            logger.warning("MongoDB not available, returning empty context")
            return ChatContext(context_type="none")
            
        if chat_id is None:
            logger.error(f"Chat ID is required for context retrieval")
            return ChatContext(context_type="error")
            
        try:
            # Check if query needs context
            needs_context, context_type = self._analyze_context_need(current_query)
            
            if not needs_context:
                return ChatContext(context_type="none")
            
            # Get session history
            session = self._get_session(user_session, chat_id)
            if not session or not session.messages:
                return ChatContext(context_type="none")
            
            # Extract relevant context based on type
            if context_type == "recent":
                return self._get_recent_context(session, current_query)
            elif context_type == "reference":
                return self._get_reference_context(session, current_query)
            else:
                return self._get_adaptive_context(session, current_query)
                
        except Exception as e:
            logger.error(f"Error getting chat context: {e}")
            return ChatContext(context_type="error")
    
    def get_latest_empty_chat(self, user_session: str) -> Optional[Dict[str, str]]:
        """
        Get the most recently created empty chat for a user session.
        
        Args:
            user_session: User session identifier
            
        Returns:
            Dict with chat_id and chat_name if found, None otherwise
        """
        if not self._is_available():
            return None
            
        try:
            # Find chats with 0 messages, sorted by creation date (most recent first)
            cursor = self.collection.find(
                {
                    "user_session": user_session,
                    "total_messages": 0
                },
                {"chat_id": 1, "created_at": 1}
            ).sort("created_at", DESCENDING).limit(1)
            
            latest_empty = None
            for doc in cursor:
                latest_empty = doc
                break
            
            if latest_empty:
                chat_id = latest_empty.get("chat_id")
                if chat_id:
                    # Get the chat name
                    chat_name = self._get_chat_name(user_session, chat_id)
                    if not chat_name:
                        chat_name = self._generate_default_chat_name()
                        self._create_chat_name_entry(user_session, chat_id, chat_name)
                    
                    return {
                        "chat_id": chat_id,
                        "chat_name": chat_name
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting latest empty chat: {e}")
            return None

    def list_chats(self, user_session: str) -> List[Dict[str, Any]]:
        """
        List all chats for a user session.
        
        Args:
            user_session: User session identifier
            
        Returns:
            List of chat information dictionaries
        """
        if not self._is_available():
            return []
            
        try:
            # Find all chats for this user session
            cursor = self.collection.find(
                {"user_session": user_session},
                {"chat_id": 1, "total_messages": 1, "updated_at": 1, "created_at": 1}
            ).sort("updated_at", DESCENDING)
            
            # Get all chat names for this user session
            chat_names = self._get_all_chat_names(user_session)
            
            chats = []
            for doc in cursor:
                chat_id = doc.get("chat_id", self.DEFAULT_CHAT_ID)
                chat_name = chat_names.get(chat_id, self._generate_default_chat_name())
                
                chats.append({
                    "chat_id": chat_id,
                    "chat_name": chat_name,
                    "total_messages": doc.get("total_messages", 0),
                    "created_at": doc.get("created_at"),
                    "updated_at": doc.get("updated_at")
                })
            
            return chats
            
        except Exception as e:
            logger.error(f"Error listing chats for session {user_session}: {e}")
            return []
    
    def update_chat_name(self, user_session: str, chat_id: str, new_chat_name: str) -> bool:
        """Update chat name for a specific chat."""
        if not self._is_available() or self.chat_names_collection is None:
            return False
            
        try:
            chat_key = self._get_chat_key(user_session, chat_id)
            
            # Check if chat name entry exists
            existing_doc = self.chat_names_collection.find_one({"chat_key": chat_key})
            
            if existing_doc:
                # Update existing entry
                result = self.chat_names_collection.update_one(
                    {"chat_key": chat_key},
                    {
                        "$set": {
                            "chat_name": new_chat_name,
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
                return result.modified_count > 0
            else:
                # Create new entry if it doesn't exist
                return self._create_chat_name_entry(user_session, chat_id, new_chat_name)
                
        except Exception as e:
            logger.error(f"Error updating chat name: {e}")
            return False
    
    def toggle_message_note(self, user_session: str, chat_id: str, message_id: str) -> bool:
        """Toggle the note state of a specific message."""
        if not self._is_available():
            return False
            
        try:
            session = self._get_session(user_session, chat_id)
            if not session:
                return False
            
            # Find and toggle the message
            message_found = False
            for message in session.messages:
                if message.message_id == message_id:
                    message.save_to_note = not getattr(message, 'save_to_note', False)
                    message_found = True
                    break
            
            if not message_found:
                return False
            
            # Save the updated session
            return self._save_session(session)
            
        except Exception as e:
            logger.error(f"Error toggling message note: {e}")
            return False

    def get_saved_notes(self, user_session: str) -> List[Dict[str, Any]]:
        """Get all saved notes for a user session across all chats."""
        if not self._is_available():
            return []
            
        try:
            # Find all chats for this user session
            cursor = self.collection.find(
                {"user_session": user_session},
                {"chat_id": 1, "messages": 1}
            )
            
            # Get all chat names for this user session
            chat_names = self._get_all_chat_names(user_session)
            
            saved_notes = []
            for doc in cursor:
                chat_id = doc.get("chat_id", self.DEFAULT_CHAT_ID)
                chat_name = chat_names.get(chat_id, self._generate_default_chat_name())
                messages = doc.get("messages", [])
                
                for msg_data in messages:
                    if msg_data.get("save_to_note", False):
                        saved_notes.append({
                            "message_id": msg_data.get("message_id"),
                            "chat_id": chat_id,
                            "chat_name": chat_name,
                            "timestamp": msg_data.get("timestamp"),
                            "role": msg_data.get("role"),
                            "content": msg_data.get("content"),
                            "query_type": msg_data.get("query_type"),
                            "save_to_note": msg_data.get("save_to_note", True)
                        })
            
            # Sort by timestamp (most recent first)
            saved_notes.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            return saved_notes
            
        except Exception as e:
            logger.error(f"Error getting saved notes: {e}")
            return []

    def _analyze_context_need(self, query: str) -> Tuple[bool, str]:
        """
        Analyze if query needs chat context and what type.
        
        Args:
            query: User query to analyze
            
        Returns:
            Tuple of (needs_context: bool, context_type: str)
        """
        try:
            # Quick pattern-based detection
            reference_patterns = [
                r'\b(this|that|it|they|them|these|those)\b',
                r'\b(previous|earlier|before|above|mentioned)\b',
                r'\b(as (I|we) (said|discussed|mentioned|talked))\b',
                r'\b(from (our|the) (conversation|discussion|chat))\b',
                r'\b(what (did|do) (I|you) (say|mean|ask))\b',
                r'\b(clarify|explain (more|further|better))\b',
                r'\b(continue|more details?|elaborate)\b'
            ]
            
            query_lower = query.lower()
            
            # Check for reference patterns
            for pattern in reference_patterns:
                if re.search(pattern, query_lower):
                    return True, "reference"
            
            # Check for recent context needs (short queries often need context)
            if len(query.split()) <= 5:
                return True, "recent"
            
            # Use LLM for complex cases
            try:
                llm_result = self._llm_context_analysis(query)
                if llm_result.get("needs_context", False):
                    return True, llm_result.get("context_type", "adaptive")
            except Exception as e:
                logger.warning(f"LLM context analysis failed: {e}")
            
            return False, "none"
        except Exception as e:
            logger.error(f"Error in context need analysis: {e}")
            return False, "none"
    
    def _llm_context_analysis(self, query: str) -> Dict[str, Any]:
        """
        Use LLM to analyze if query needs chat context.
        
        Args:
            query: User query
            
        Returns:
            Analysis result dictionary
        """
        prompt = f"""Analyze if this user query refers to previous conversation context.

Query: "{query}"

Consider:
1. Does it contain pronouns without clear referents (this, that, it, etc.)?
2. Does it reference previous discussion ("as we discussed", "from before", etc.)?
3. Does it ask for clarification or continuation?
4. Is it a follow-up question that builds on previous context?

Respond with JSON:
{{
    "needs_context": true/false,
    "context_type": "none/recent/reference/adaptive",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}"""

        try:
            response = self.llm.invoke(prompt)
            return json.loads(response.content.strip())
        except Exception as e:
            logger.error(f"LLM context analysis error: {e}")
            return {"needs_context": False, "context_type": "none", "confidence": 0.0}
    
    def _get_recent_context(self, session: ChatSession, query: str) -> ChatContext:
        """Get recent conversation context."""
        try:
            recent_messages = session.get_recent_messages(6)  # Last 3 pairs
            if not recent_messages:
                return ChatContext(context_type="none")
            
            total_tokens = sum(getattr(msg, 'token_count', 0) for msg in recent_messages)
            
            return ChatContext(
                relevant_messages=recent_messages,
                token_count=total_tokens,
                confidence_score=0.8,
                context_type="recent"
            )
        except Exception as e:
            logger.error(f"Error getting recent context: {e}")
            return ChatContext(context_type="error")
    
    def _get_reference_context(self, session: ChatSession, query: str) -> ChatContext:
        """Get context based on specific references in the query."""
        try:
            # Look for messages that might be referenced
            relevant_messages = []
            
            # Simple keyword matching for now - could be enhanced with embeddings
            query_words = set(query.lower().split())
            
            for msg in session.messages[-20:]:  # Look at recent messages
                if msg.role == MessageRole.ASSISTANT:
                    msg_words = set(msg.content.lower().split())
                    # Simple overlap scoring
                    overlap = len(query_words & msg_words)
                    if overlap > 2:  # Arbitrary threshold
                        relevant_messages.append(msg)
            
            if not relevant_messages:
                return self._get_recent_context(session, query)
            
            total_tokens = sum(getattr(msg, 'token_count', 0) for msg in relevant_messages[-4:])
            
            return ChatContext(
                relevant_messages=relevant_messages[-4:],  # Last 2 pairs max
                token_count=total_tokens,
                confidence_score=0.9,
                context_type="reference"
            )
        except Exception as e:
            logger.error(f"Error getting reference context: {e}")
            return ChatContext(context_type="error")
    
    def _get_adaptive_context(self, session: ChatSession, query: str) -> ChatContext:
        """Get adaptive context based on conversation flow."""
        try:
            # For now, use recent context with summary
            recent_pairs = session.get_conversation_pairs(3)
            
            if not recent_pairs:
                return ChatContext(context_type="none")
            
            # Create summary of recent conversation
            summary_content = []
            total_tokens = 0
            
            for user_msg, assistant_msg in recent_pairs:
                summary_content.append(f"User asked about: {user_msg.content[:100]}")
                summary_content.append(f"Assistant explained: {assistant_msg.content[:150]}")
                total_tokens += getattr(user_msg, 'token_count', 0) + getattr(assistant_msg, 'token_count', 0)
            
            context_summary = " | ".join(summary_content)
            
            return ChatContext(
                context_summary=context_summary,
                token_count=total_tokens // 3,  # Compressed representation
                confidence_score=0.7,
                context_type="adaptive"
            )
        except Exception as e:
            logger.error(f"Error getting adaptive context: {e}")
            return ChatContext(context_type="error")
    
    def _get_or_create_session(self, user_session: str, chat_id: str = None) -> ChatSession:
        """Get existing session or create new one."""
        if chat_id is None:
            chat_id = self.DEFAULT_CHAT_ID
            
        session = self._get_session(user_session, chat_id)
        
        if session:
            return session
        
        # Create new session
        return ChatSession(
            user_session=user_session,
            chat_id=chat_id
        )
    
    def _get_session(self, user_session: str, chat_id: str = None) -> Optional[ChatSession]:
        """Get session from MongoDB using composite key."""
        if not self._is_available():
            return None
            
        if chat_id is None:
            chat_id = self.DEFAULT_CHAT_ID
            
        try:
            chat_key = self._get_chat_key(user_session, chat_id)
            doc = self.collection.find_one({"chat_key": chat_key})
            if doc:
                return ChatSession.from_dict(doc)
            return None
        except Exception as e:
            logger.error(f"Error getting session: {e}")
            return None
    
    def _save_session(self, session: ChatSession) -> bool:
        """Save session to MongoDB using composite key."""
        if not self._is_available():
            return False
            
        try:
            doc = session.to_dict()
            chat_key = self._get_chat_key(session.user_session, session.chat_id)
            doc["chat_key"] = chat_key
            
            self.collection.replace_one(
                {"chat_key": chat_key},
                doc,
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Error saving session: {e}")
            return False
    
    def _apply_session_limits(self, session: ChatSession) -> None:
        """Apply limits to session to prevent unlimited growth."""
        try:
            # Limit number of messages
            if session.total_messages > self.MAX_MESSAGES_PER_SESSION:
                # Keep most recent messages
                messages_to_keep = self.MAX_MESSAGES_PER_SESSION // 2
                session.messages = session.messages[-messages_to_keep:]
                session.total_messages = len(session.messages)
                session.total_tokens = sum(getattr(msg, 'token_count', 0) for msg in session.messages)
                logger.info(f"Trimmed session {session.user_session}:{session.chat_id} to {messages_to_keep} messages")
            
            # Limit total tokens
            if session.total_tokens > self.MAX_TOKENS_PER_SESSION:
                # Remove oldest messages until under limit
                while session.total_tokens > self.MAX_TOKENS_PER_SESSION and session.messages:
                    removed_msg = session.messages.pop(0)
                    session.total_tokens -= getattr(removed_msg, 'token_count', 0)
                    session.total_messages -= 1
                logger.info(f"Trimmed session {session.user_session}:{session.chat_id} to {session.total_tokens} tokens")
        except Exception as e:
            logger.error(f"Error applying session limits: {e}")
    
    def cleanup_old_sessions(self) -> int:
        """Clean up old sessions."""
        if not self._is_available():
            return 0
            
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=self.MAX_SESSION_AGE_DAYS)
            result = self.collection.delete_many({"updated_at": {"$lt": cutoff_date}})
            logger.info(f"Cleaned up {result.deleted_count} old chat sessions")
            return result.deleted_count
        except Exception as e:
            logger.error(f"Error cleaning up old sessions: {e}")
            return 0
    
    def get_session_stats(self, user_session: str, chat_id: str = None) -> Dict[str, Any]:
        """Get statistics for a specific chat session."""
        if not self._is_available():
            return {"exists": False, "error": "MongoDB not available"}
            
        if chat_id is None:
            chat_id = self.DEFAULT_CHAT_ID
            
        try:
            session = self._get_session(user_session, chat_id)
            if not session:
                return {"exists": False}
            
            return {
                "exists": True,
                "chat_id": session.chat_id,
                "total_messages": session.total_messages,
                "total_tokens": session.total_tokens,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "last_query_type": session.messages[-1].query_type.value if session.messages and session.messages[-1].query_type else None
            }
        except Exception as e:
            logger.error(f"Error getting session stats: {e}")
            return {"exists": False, "error": str(e)}
    
    def delete_session(self, user_session: str, chat_id: str = None) -> bool:
        """Delete a specific chat session."""
        if not self._is_available():
            return False
            
        if chat_id is None:
            return True
            
        try:
            chat_key = self._get_chat_key(user_session, chat_id)
            
            # Delete from both collections
            session_result = self.collection.delete_one({"chat_key": chat_key})
            
            # Also delete the chat name entry
            if self.chat_names_collection is not None:
                self.chat_names_collection.delete_one({"chat_key": chat_key})
            
            logger.info(f"Deleted chat session {chat_key}")
            return session_result.deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting session: {e}")
            return False
    
    def delete_all_chats_for_session(self, user_session: str) -> int:
        """Delete all chats for a user session."""
        if not self._is_available():
            return 0
            
        try:
            # Delete from sessions collection
            result = self.collection.delete_many({"user_session": user_session})
            
            # Also delete all chat name entries for this user session
            if self.chat_names_collection is not None:
                self.chat_names_collection.delete_many({"user_session": user_session})
            
            logger.info(f"Deleted {result.deleted_count} chats for session {user_session}")
            return result.deleted_count
        except Exception as e:
            logger.error(f"Error deleting all chats for session: {e}")
            return 0


# Singleton instance
_chat_history_manager = None

def get_chat_history_manager() -> ChatHistoryManager:
    """Get the chat history manager singleton instance."""
    global _chat_history_manager
    if _chat_history_manager is None:
        _chat_history_manager = ChatHistoryManager()
    return _chat_history_manager
