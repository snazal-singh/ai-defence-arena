from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class RenameContainerBody(BaseModel):
    new_name: str


class MongoServerConnectRequest(BaseModel):
    connectionUri: str
    serverName: str


class ContainerItem(BaseModel):
    session_id: str
    name: str
    file_names: List[str] = []
    timestamp: str = ""


class ContainerListResponse(BaseModel):
    data: List[Dict[str, Any]]


class UploadResponse(BaseModel):
    status: str
    message: str
    files_processed: Optional[int] = None
    files_successful: Optional[int] = None
    urls_processed: Optional[int] = None
    urls_successful: Optional[int] = None
    details: Optional[List[Dict[str, Any]]] = None
    processing_time: Optional[float] = None
