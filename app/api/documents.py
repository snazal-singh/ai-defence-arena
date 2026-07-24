import json
import logging
import mimetypes
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.api.adapters import UploadFileList
from app.api.deps import get_current_user
from app.schemas.document import MongoServerConnectRequest, MongoCollectionSelectRequest, RenameContainerBody
from app.services.document_service import get_document_service
from controllers import external_mongo_connection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Documents"])

document_service = get_document_service()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_urls(urls_json: Optional[str]) -> List[str]:
    """Parse and validate a JSON-encoded list of URLs from form data."""
    if not urls_json:
        return []
    try:
        urls = json.loads(urls_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid URLs format — must be a valid JSON array.")
    if not isinstance(urls, list):
        raise HTTPException(status_code=400, detail="URLs must be provided as an array.")
    valid: List[str] = []
    for url in urls:
        if isinstance(url, str) and url.strip():
            url = url.strip()
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            valid.append(url)
    return valid


# ---------------------------------------------------------------------------
# Free-trial upload (no token)
# ---------------------------------------------------------------------------

@router.post("/free-trial")
def free_trial(
    fingerprint: str = Form(...),
    files: List[UploadFile] = File(default=[]),
    urls: Optional[str] = Form(default=None),
):
    """Upload documents for a fingerprint-identified trial user (no account required)."""
    parsed_urls = _parse_urls(urls)
    file_list = UploadFileList(files)

    result = document_service.process_files_and_urls(
        file_list, parsed_urls, fingerprint, is_new_container=True, is_trial=True
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


# ---------------------------------------------------------------------------
# Authenticated upload — create new container
# ---------------------------------------------------------------------------

@router.post("/upload")
def upload(
    sessionId: str = Form(...),
    files: List[UploadFile] = File(default=[]),
    urls: Optional[str] = Form(default=None),
    user_email: str = Depends(get_current_user),
):
    """Create a new container and upload documents / URLs into it."""
    session_id = sessionId
    parsed_urls = _parse_urls(urls)
    user_session = user_email + session_id.lower()
    file_list = UploadFileList(files)

    result = document_service.process_files_and_urls(
        file_list, parsed_urls, user_session,
        is_new_container=True, is_trial=False,
        session_id=session_id, email=user_email,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


# ---------------------------------------------------------------------------
# Authenticated upload — add to existing container
# ---------------------------------------------------------------------------

@router.post("/upload/{session_id}")
def add_upload(
    session_id: str,
    files: List[UploadFile] = File(default=[]),
    urls: Optional[str] = Form(default=None),
    user_email: str = Depends(get_current_user),
):
    """Add more documents / URLs to an existing container."""
    parsed_urls = _parse_urls(urls)
    user_session = user_email + session_id.lower()
    file_list = UploadFileList(files)

    result = document_service.process_files_and_urls(
        file_list, parsed_urls, user_session,
        is_new_container=False, is_trial=False,
        session_id=session_id, email=user_email,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


# ---------------------------------------------------------------------------
# List containers
# ---------------------------------------------------------------------------

@router.get("/containers")
def get_containers(user_email: str = Depends(get_current_user)):
    """Return all containers belonging to the authenticated user."""
    containers = document_service.fetch_user_sessions(user_email)
    return {"data": containers}


# ---------------------------------------------------------------------------
# Rename container
# ---------------------------------------------------------------------------

@router.patch("/containers/{session_id}")
def rename_container(
    session_id: str,
    body: RenameContainerBody,
    user_email: str = Depends(get_current_user),
):
    """Rename a container by session ID."""
    new_name = body.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="New container name cannot be empty.")
    success = document_service.rename_container(session_id, new_name)
    if not success:
        raise HTTPException(status_code=500, detail="Error renaming container.")
    return {"message": "Container renamed successfully"}


# ---------------------------------------------------------------------------
# Update timestamp
# ---------------------------------------------------------------------------

@router.put("/containers/{session_id}/timestamp")
def update_timestamp(
    session_id: str,
    user_email: str = Depends(get_current_user),
):
    """Refresh the last-accessed timestamp of a container."""
    success = document_service.update_container_timestamp(user_email, session_id)
    if not success:
        raise HTTPException(status_code=500, detail="Error updating timestamp.")
    return {"message": "Timestamp updated successfully"}


# ---------------------------------------------------------------------------
# Delete container
# ---------------------------------------------------------------------------

@router.delete("/containers/{session_id}")
def delete_container(
    session_id: str,
    user_email: str = Depends(get_current_user),
):
    """Permanently delete a container and all its associated data."""
    user_session = user_email + session_id.lower()
    success = document_service.delete_container(user_session, user_email, session_id)
    if not success:
        raise HTTPException(status_code=500, detail="Error deleting container.")
    return {"message": "Container deleted successfully"}


# ---------------------------------------------------------------------------
# External MongoDB servers (multi-server)
#
# Lets a user attach one or more of their own externally-hosted MongoDB
# servers (e.g. Atlas) to a container, as an additional structured data
# source alongside data ingested from uploaded JSON files. Only publicly
# reachable Mongo servers are supported -- this backend has no network path
# to a server on the user's own local machine/LAN. See
# controllers/external_mongo_connection.py for the connection/validation/
# introspection logic; once attached, schema-aware SQL-vs-Mongo intent
# routing and query generation for this container automatically include
# every attached server's cached schema catalog.
# ---------------------------------------------------------------------------

@router.post("/containers/{session_id}/mongodb/connect")
def connect_mongo_server(
    session_id: str,
    body: MongoServerConnectRequest,
    user_email: str = Depends(get_current_user),
):
    """Verify connectivity, introspect every database/collection on the
    server, and attach it to this container."""
    user_session = user_email + session_id.lower()

    ok, message, server = external_mongo_connection.attach_server(
        user_session, body.connectionUri, body.serverName
    )
    if not ok:
        raise HTTPException(status_code=400, detail=message)

    return {"message": message, "server": server}


@router.get("/containers/{session_id}/mongodb/servers")
def list_mongo_servers(
    session_id: str,
    user_email: str = Depends(get_current_user),
):
    """List every external MongoDB server attached to this container
    (metadata + cached schema catalog only, never the connection string)."""
    user_session = user_email + session_id.lower()
    return {"servers": external_mongo_connection.list_servers(user_session)}


@router.delete("/containers/{session_id}/mongodb/servers/{server_id}")
def remove_mongo_server(
    session_id: str,
    server_id: str,
    user_email: str = Depends(get_current_user),
):
    """Detach a single external MongoDB server from this container."""
    user_session = user_email + session_id.lower()
    removed = external_mongo_connection.remove_server(user_session, server_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No server '{server_id}' attached to this container")
    return {"message": "Server removed successfully"}


@router.get("/containers/{session_id}/mongodb/servers/{server_id}/collections")
def list_mongo_server_collections(
    session_id: str,
    server_id: str,
    user_email: str = Depends(get_current_user),
):
    """Database name (taken from the connection URI) + every collection in
    it, for populating a collection-selection dropdown after connecting.
    Read from the schema catalog cached at attach-time -- no live server
    round-trip."""
    user_session = user_email + session_id.lower()
    ok, message, database_name, collections = external_mongo_connection.list_collections_for_server(
        user_session, server_id
    )
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"database": database_name, "collections": collections}


@router.put("/containers/{session_id}/mongodb/servers/{server_id}/collection")
def select_mongo_server_collections(
    session_id: str,
    server_id: str,
    body: MongoCollectionSelectRequest,
    user_email: str = Depends(get_current_user),
):
    """Lock this server to one or more collections the user picked from the
    dropdown, replacing any previous selection. All subsequent queries
    against this server target only these collections. Pass an empty list
    to clear the lock and put every collection back in scope."""
    user_session = user_email + session_id.lower()
    ok, message = external_mongo_connection.select_collections(
        user_session, server_id, body.collections
    )
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"message": message}


# ---------------------------------------------------------------------------
# Delete a source from a container
# ---------------------------------------------------------------------------

@router.delete("/containers/{session_id}/sources/{filename}")
def delete_source(
    session_id: str,
    filename: str,
    user_email: str = Depends(get_current_user),
):
    """Remove a single source file from a container."""
    user_session = user_email + session_id.lower()
    success = document_service.delete_source(user_session, session_id, filename)
    if not success:
        raise HTTPException(status_code=500, detail="Error deleting source.")
    return {"message": "Source deleted successfully"}


# ---------------------------------------------------------------------------
# Download a file
# ---------------------------------------------------------------------------

@router.get("/files/{session_id}/{filename}")
def fetch_file(
    session_id: str,
    filename: str,
    user_email: str = Depends(get_current_user),
):
    """Download a specific file from a container."""
    user_session = user_email + session_id.lower()
    file_path = document_service.fetch_file_path(user_session, filename)
    if not file_path:
        raise HTTPException(status_code=404, detail="File not found.")

    content_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(
        path=str(file_path),
        media_type=content_type or "application/octet-stream",
        filename=filename,
    )
