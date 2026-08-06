from pydantic import BaseModel, Field, AliasChoices
from typing import Any, Dict, List, Optional, Union


class TrialQueryRequest(BaseModel):
    fingerprint: str
    message: str
    inputLanguage: Optional[Union[str, int]] = Field(default="en", validation_alias=AliasChoices('inputLanguage', 'input_language'))
    outputLanguage: Optional[Union[str, int]] = Field(default="en", validation_alias=AliasChoices('outputLanguage', 'output_language'))
    hasCsvOrXlsx: Optional[bool] = Field(default=False, validation_alias=AliasChoices('hasCsvOrXlsx', 'has_csv_or_xlsx'))
    mode: Optional[str] = "default"
    filenames: Optional[List[str]] = []


class QueryRequest(BaseModel):
    message: str
    chatId: Optional[str] = Field(default=None, validation_alias=AliasChoices('chatId', 'chat_id'))
    sessionId: Optional[str] = Field(default=None, validation_alias=AliasChoices('sessionId', 'session_id'))
    context: Optional[Union[str, bool]] = ""
    inputLanguage: Optional[Union[str, int]] = Field(default="en", validation_alias=AliasChoices('inputLanguage', 'input_language'))
    outputLanguage: Optional[Union[str, int]] = Field(default="en", validation_alias=AliasChoices('outputLanguage', 'output_language'))
    hasCsvOrXlsx: Optional[bool] = Field(default=False, validation_alias=AliasChoices('hasCsvOrXlsx', 'has_csv_or_xlsx'))
    mode: Optional[str] = "default"
    filenames: Optional[List[str]] = []


class DemoQueryRequest(BaseModel):
    message: str


class ToggleNoteRequest(BaseModel):
    sessionId: str = Field(validation_alias=AliasChoices('sessionId', 'session_id'))
    chatId: Optional[str] = Field(default="default", validation_alias=AliasChoices('chatId', 'chat_id'))
    messageId: str = Field(validation_alias=AliasChoices('messageId', 'message_id'))


class RenameChatRequest(BaseModel):
    sessionId: str = Field(validation_alias=AliasChoices('sessionId', 'session_id'))
    chatId: Optional[str] = Field(default="default", validation_alias=AliasChoices('chatId', 'chat_id'))
    newChatName: str = Field(validation_alias=AliasChoices('newChatName', 'new_chat_name'))


class AnalyzeContextRequest(BaseModel):
    sessionId: str = Field(validation_alias=AliasChoices('sessionId', 'session_id'))
    chatId: Optional[str] = Field(default="default", validation_alias=AliasChoices('chatId', 'chat_id'))
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

