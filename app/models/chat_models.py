"""
Chat history data models and schemas.

This module defines the data structures for storing and managing chat history.
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import uuid
import logging

logger = logging.getLogger(__name__)

class QueryType(Enum):
    """Types of queries processed by the system."""
    DOCUMENT = "document"
    DATA = "data"
    SUMMARY = "summary"
    HYBRID = "hybrid"
    GENERAL = "general"
    CREATIVE = "creative"

class MessageRole(Enum):
    """Roles in the conversation."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

@dataclass
class ChatMessage:
    """Individual message in a conversation."""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    role: MessageRole = MessageRole.USER
    content: str = ""
    query_type: Optional[QueryType] = None
    context_used: bool = False
    token_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    save_to_note: bool = False
    image_caption: Optional[str] = None
    image_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary for storage."""
        try:
            return {
                "message_id": self.message_id,
                "timestamp": self.timestamp.isoformat() if isinstance(self.timestamp, datetime) else str(self.timestamp),
                "role": self.role.value if self.role else "user",
                "content": self.content or "",
                "query_type": self.query_type.value if self.query_type else None,
                "context_used": bool(self.context_used),
                "token_count": int(self.token_count) if self.token_count else 0,
                "metadata": self.metadata or {},
                "save_to_note": bool(self.save_to_note),
                "image_caption": self.image_caption or "",
                "image_url": self.image_url or ""
            }
        except Exception as e:
            logger.error(f"Error converting ChatMessage to dict: {e}")
            # Return a safe fallback
            return {
                "message_id": str(self.message_id) if self.message_id else str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat(),
                "role": "user",
                "content": str(self.content) if self.content else "",
                "query_type": None,
                "context_used": False,
                "token_count": 0,
                "metadata": {},
                "save_to_note": False,
                "image_caption": "",
                "image_url": ""
            }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChatMessage':
        """Create message from dictionary with improved error handling."""
        try:
            # Parse timestamp
            timestamp = data.get("timestamp", datetime.utcnow())
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except ValueError:
                    timestamp = datetime.utcnow()
            elif not isinstance(timestamp, datetime):
                timestamp = datetime.utcnow()
            
            # Parse role with fallback
            role_value = data.get("role", "user")
            try:
                role = MessageRole(role_value)
            except (ValueError, TypeError):
                logger.warning(f"Invalid role value: {role_value}, defaulting to USER")
                role = MessageRole.USER
            
            # Parse query_type with fallback
            query_type = None
            query_type_value = data.get("query_type")
            if query_type_value:
                try:
                    query_type = QueryType(query_type_value)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid query_type value: {query_type_value}")
                    query_type = None
            
            return cls(
                message_id=data.get("message_id", str(uuid.uuid4())),
                timestamp=timestamp,
                role=role,
                content=data.get("content", ""),
                query_type=query_type,
                context_used=bool(data.get("context_used", False)),
                token_count=int(data.get("token_count", 0)),
                metadata=data.get("metadata", {}),
                save_to_note=bool(data.get("save_to_note", False)),
                image_caption=data.get("image_caption", None),
                image_url=data.get("image_url", None)
            )
        except Exception as e:
            logger.error(f"Error creating ChatMessage from dict: {e}")
            # Return a safe fallback
            return cls(
                content=str(data.get("content", "")),
                role=MessageRole.USER
            )

@dataclass
class ChatSession:
    """Complete chat session with all messages for a specific chat within a user session."""
    user_session: str
    chat_id: str
    messages: List[ChatMessage] = field(default_factory=list)
    total_messages: int = 0
    total_tokens: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_message(self, message: ChatMessage) -> None:
        """Add a message to the session."""
        try:
            self.messages.append(message)
            self.total_messages = len(self.messages)
            self.total_tokens += getattr(message, 'token_count', 0)
            self.updated_at = datetime.utcnow()
        except Exception as e:
            logger.error(f"Error adding message to session: {e}")

    def get_recent_messages(self, count: int = 10) -> List[ChatMessage]:
        """Get the most recent messages."""
        try:
            return self.messages[-count:] if self.messages else []
        except Exception as e:
            logger.error(f"Error getting recent messages: {e}")
            return []

    def get_messages_since(self, since: datetime) -> List[ChatMessage]:
        """Get messages since a specific timestamp."""
        try:
            return [msg for msg in self.messages if msg.timestamp >= since]
        except Exception as e:
            logger.error(f"Error getting messages since timestamp: {e}")
            return []

    def get_conversation_pairs(self, count: int = 5) -> List[tuple[ChatMessage, ChatMessage]]:
        """Get recent user-assistant conversation pairs."""
        try:
            pairs = []
            user_msg = None
            
            # Look through recent messages for user-assistant pairs
            recent_messages = self.get_recent_messages(count * 2)
            
            for msg in recent_messages:
                if msg.role == MessageRole.USER:
                    user_msg = msg
                elif msg.role == MessageRole.ASSISTANT and user_msg:
                    pairs.append((user_msg, msg))
                    user_msg = None
                    if len(pairs) >= count:
                        break
            
            return pairs
        except Exception as e:
            logger.error(f"Error getting conversation pairs: {e}")
            return []

    def to_dict(self) -> Dict[str, Any]:
        """Convert session to dictionary for storage."""
        try:
            return {
                "user_session": self.user_session,
                "chat_id": self.chat_id,
                "messages": [msg.to_dict() for msg in self.messages],
                "total_messages": self.total_messages,
                "total_tokens": self.total_tokens,
                "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
                "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else str(self.updated_at),
                "metadata": self.metadata
            }
        except Exception as e:
            logger.error(f"Error converting ChatSession to dict: {e}")
            return {
                "user_session": str(self.user_session),
                "chat_id": str(self.chat_id),
                "messages": [],
                "total_messages": 0,
                "total_tokens": 0,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "metadata": {}
            }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ChatSession':
        """Create session from dictionary with improved error handling."""
        try:
            # Parse timestamps
            created_at = data.get("created_at", datetime.utcnow())
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                except ValueError:
                    created_at = datetime.utcnow()
            
            updated_at = data.get("updated_at", datetime.utcnow())
            if isinstance(updated_at, str):
                try:
                    updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
                except ValueError:
                    updated_at = datetime.utcnow()
            
            # Handle backward compatibility for existing data without chat_id
            chat_id = data.get("chat_id", "default")
            
            session = cls(
                user_session=data.get("user_session", ""),
                chat_id=chat_id,
                total_messages=int(data.get("total_messages", 0)),
                total_tokens=int(data.get("total_tokens", 0)),
                created_at=created_at,
                updated_at=updated_at,
                metadata=data.get("metadata", {})
            )
            
            # Load messages with error handling
            for msg_data in data.get("messages", []):
                try:
                    session.messages.append(ChatMessage.from_dict(msg_data))
                except Exception as e:
                    logger.error(f"Error loading message: {e}")
                    continue
            
            return session
        except Exception as e:
            logger.error(f"Error creating ChatSession from dict: {e}")
            # Return a safe fallback
            return cls(
                user_session=str(data.get("user_session", "")),
                chat_id=str(data.get("chat_id", "default"))
            )

@dataclass
class ChatContext:
    """Context extracted from chat history for query processing."""
    relevant_messages: List[ChatMessage] = field(default_factory=list)
    context_summary: str = ""
    token_count: int = 0
    confidence_score: float = 0.0
    context_type: str = "none"  # none, recent, reference, full

    def has_context(self) -> bool:
        """Check if context contains useful information."""
        return bool(self.relevant_messages or self.context_summary)

    def get_formatted_context(self) -> str:
        """Format context for inclusion in prompts."""
        try:
            if not self.has_context():
                return ""
            
            if self.context_summary:
                return f"Previous conversation context: {self.context_summary}"
            
            # Format messages as conversation
            formatted = "Previous conversation:\n"
            for msg in self.relevant_messages[-6:]:  # Last 3 pairs max
                try:
                    role = "User" if msg.role == MessageRole.USER else "Assistant"
                    content = msg.content[:200] + "..." if len(msg.content) > 200 else msg.content
                    formatted += f"{role}: {content}\n"
                except Exception as e:
                    logger.error(f"Error formatting message: {e}")
                    continue
            
            return formatted
        except Exception as e:
            logger.error(f"Error formatting context: {e}")
            return ""