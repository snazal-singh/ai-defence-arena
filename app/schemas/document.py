from pydantic import BaseModel
from typing import Any, Dict, List, Optional


class RenameContainerBody(BaseModel):
    new_name: str


class ExternalMongoConnectionRequest(BaseModel):
    connectionUri: str
    databaseName: str
    # Optional allowlist restricting which collections in databaseName this
    # container can see/query. Omitted or empty means "all collections in
    # databaseName are visible" -- see controllers/external_mongo_connection.py.
    collections: Optional[List[str]] = None


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
