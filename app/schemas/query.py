from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class TrialQueryRequest(BaseModel):
    fingerprint: str
    message: str
    inputLanguage: Optional[str] = "en"
    outputLanguage: Optional[str] = "en"
    hasCsvOrXlsx: Optional[bool] = False
    mode: Optional[str] = "default"
    filenames: Optional[List[str]] = []


class QueryRequest(BaseModel):
    message: str
    chatId: str
    sessionId: Optional[str] = None
    context: Optional[str] = ""
    inputLanguage: Optional[str] = "en"
    outputLanguage: Optional[str] = "en"
    hasCsvOrXlsx: Optional[bool] = False
    mode: Optional[str] = "default"
    filenames: Optional[List[str]] = []


class DemoQueryRequest(BaseModel):
    message: str


class ToggleNoteRequest(BaseModel):
    sessionId: str
    chatId: Optional[str] = "default"
    messageId: str


class RenameChatRequest(BaseModel):
    sessionId: str
    chatId: Optional[str] = "default"
    newChatName: str


class AnalyzeContextRequest(BaseModel):
    sessionId: str
    chatId: Optional[str] = "default"
    query: str


class ChatHistoryMessage(BaseModel):
    message_id: str
    timestamp: str
    role: str
    content: str
    query_type: Optional[str] = None
    save_to_note: Optional[bool] = False


class ChatHistoryResponse(BaseModel):
    success: bool
    messages: List[ChatHistoryMessage]
    total_messages: int
    session_exists: bool
    chatId: str
    chatName: Optional[str] = None


class ChatListResponse(BaseModel):
    success: bool
    chats: List[Dict[str, Any]]
    total_chats: int


class ChatStatsResponse(BaseModel):
    success: bool
    stats: Dict[str, Any]


class NoteListResponse(BaseModel):
    success: bool
    notes: List[Dict[str, Any]]
    total_notes: int


class ToggleNoteResponse(BaseModel):
    success: bool
    message: str
    message_id: Optional[str] = None


class RenameChatResponse(BaseModel):
    success: bool
    message: str
    chat_id: Optional[str] = None
    new_chat_name: Optional[str] = None
