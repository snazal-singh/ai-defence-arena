import json
import logging
import mimetypes
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from app.api.adapters import UploadFileList
from app.api.deps import get_current_user
from app.schemas.document import ExternalMongoConnectionRequest, RenameContainerBody
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
# External MongoDB connection
#
# Lets a user attach their own externally-hosted MongoDB server (e.g. Atlas)
# to a container instead of only querying data ingested from uploaded JSON
# files. Only publicly reachable Mongo servers are supported -- this backend
# has no network path to a server on the user's own local machine/LAN. See
# controllers/external_mongo_connection.py for the connection/validation
# logic; once attached, schema introspection and query routing for this
# container work exactly as they do for uploaded JSON data.
# ---------------------------------------------------------------------------

@router.post("/containers/{session_id}/mongo-connection")
def attach_external_mongo(
    session_id: str,
    body: ExternalMongoConnectionRequest,
    user_email: str = Depends(get_current_user),
):
    """Test and attach an external MongoDB connection to this container."""
    user_session = user_email + session_id.lower()

    ok, message, collections = external_mongo_connection.test_connection(
        body.connectionUri, body.databaseName
    )
    if not ok:
        raise HTTPException(status_code=400, detail=message)

    if body.collections:
        unknown = set(body.collections) - set(collections)
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Collection(s) not found in database '{body.databaseName}': {', '.join(sorted(unknown))}",
            )

    external_mongo_connection.save_external_connection(
        user_session, body.connectionUri, body.databaseName, body.collections
    )
    return {
        "message": "External MongoDB connection attached successfully",
        "databaseName": body.databaseName,
        "availableCollections": collections,
        "exposedCollections": body.collections or collections,
    }


@router.get("/containers/{session_id}/mongo-connection")
def get_external_mongo_status(
    session_id: str,
    user_email: str = Depends(get_current_user),
):
    """Return this container's external MongoDB connection config, if any
    (never returns the connection string itself)."""
    user_session = user_email + session_id.lower()
    config = external_mongo_connection.load_external_connection(user_session)
    if config is None:
        return {"connected": False}
    return {
        "connected": True,
        "databaseName": config["database_name"],
        "exposedCollections": config.get("collections") or [],
    }


@router.delete("/containers/{session_id}/mongo-connection")
def remove_external_mongo(
    session_id: str,
    user_email: str = Depends(get_current_user),
):
    """Detach this container's external MongoDB connection."""
    user_session = user_email + session_id.lower()
    external_mongo_connection.remove_external_connection(user_session)
    return {"message": "External MongoDB connection removed"}


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
