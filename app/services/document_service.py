"""
Simplified document upload and processing service.

This module provides functions for:
- Converting documents to text chunks
- Processing URLs (including YouTube transcripts)
- Creating vector stores from text chunks
- Storing documents in Elasticsearch
"""

import logging
import os
import threading
import time
import io
from typing import Dict, Any, List, Tuple

from pdf2image import convert_from_path
from langchain.schema import Document

from controllers.sql_db import create_database_with_tables, store_table_info, add_tables_to_existing_db
from controllers.mongodb_db import create_mongo_collections, add_collections_to_existing_db
from controllers.doc_summary import create_abstractive_summary
from controllers.upload import store_vector
from controllers.delete_session import delete_session
from controllers.database import delete_session_from_db, rename_session, update_session_timestamp, create_session, get_user_sessions, add_files_to_session, remove_file_from_session
from utils.extractText import get_text_from_files, clean_text, clean_filename
from app.services.url_content_service import get_url_content_service
from app.services.file_storage_service import get_file_storage_service
from app.services.vision_service import get_vision_service
from app.core.config import settings
from elastic.document_manager import ElasticDocumentManager

logger = logging.getLogger(__name__)

def classify_files(file_list) -> Tuple[List, List, List, List]:
    """
    Separate files into document files, SQL data files, Mongo data files,
    and unsupported files.

    Returns:
        Tuple of (document_files, data_files, mongo_files, unsupported_files)
    """
    document_extensions = {'.pdf', '.docx', '.txt', '.pptx', '.doc'}
    data_extensions = {'.csv', '.xlsx', '.xls'}
    mongo_extensions = {'.json'}

    document_files = []
    data_files = []
    mongo_files = []
    unsupported_files = []

    for file in file_list:
        if not file.filename:
            unsupported_files.append(file)
            continue

        ext = os.path.splitext(file.filename)[1].lower()

        if ext in document_extensions:
            document_files.append(file)
        elif ext in data_extensions:
            data_files.append(file)
        elif ext in mongo_extensions:
            mongo_files.append(file)
        else:
            unsupported_files.append(file)

    return document_files, data_files, mongo_files, unsupported_files

def extract_pdf_with_vision(file_path: str, filename: str) -> List[Document]:
    """Extract text from PDF using NuMarkdown vision-based parser."""
    logger.info(f"Extracting PDF with NuMarkdown vision parser: {file_path}")
    
    # Convert PDF pages to images
    images = convert_from_path(file_path, dpi=150)
    images = images[:50]  # Hard limit to 50 pages
    
    documents = []
    vision_service = get_vision_service()
    
    for page_num, image in enumerate(images):
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()
        
        # Call vision service to parse page
        markdown = vision_service.parse_document_image(image_bytes)
        
        if markdown and markdown.strip():
            cleaned = clean_text(markdown)
            if cleaned.strip():
                documents.append(Document(
                    page_content=cleaned,
                    metadata={
                        "source": filename,
                        "filename": filename,
                        "page": page_num,
                        "content_type": "text",
                    }
                ))
                
    return documents

def process_document_files(doc_files: List, user_session: str, is_new_container: bool) -> Dict[str, Any]:
    """
    Process document files using the enhanced extractText.py system or NuMarkdown vision parser.
    Automatically falls back to PyMuPDF if NuMarkdown vision parsing fails.
    
    Returns:
        Dict with processing results
    """
    if not doc_files:
        return {"success": True, "files_processed": 0, "file_details": []}
    
    logger.info(f"Processing {len(doc_files)} document files")
    all_docs = []
    file_infos = []
    
    for file in doc_files:
        filename = clean_filename(file.filename)
        file_path = f"files/{user_session}/{filename}"
        
        is_pdf = filename.lower().endswith(".pdf")
        use_numarkdown = settings.USE_NUMARKDOWN_PARSER and is_pdf
        
        documents = []
        success = False
        error_msg = ""
        
        if use_numarkdown:
            try:
                documents = extract_pdf_with_vision(file_path, filename)
                if documents:
                    logger.info(f"Successfully parsed {filename} with NuMarkdown vision parser.")
                    success = True
                else:
                    logger.warning(f"NuMarkdown returned empty content for {filename}. Falling back to standard parser.")
                    error_msg = "NuMarkdown returned empty content. Fell back to PyMuPDF."
            except Exception as e:
                logger.error(f"NuMarkdown vision parser failed for {filename}: {e}. Falling back to standard parser.")
                error_msg = f"NuMarkdown failed: {e}. Fell back to PyMuPDF."
        
        # Parse via standard local parser if not processed yet (or if NuMarkdown failed/is disabled)
        if not success:
            try:
                docs, infos = get_text_from_files([file], user_session)
                if docs:
                    documents = docs
                    success = True
                    if error_msg:
                        logger.info(f"Fallback successful for {filename}")
                else:
                    error_msg = f"{error_msg}; Standard parser returned no text content." if error_msg else "No text content extracted."
            except Exception as e:
                logger.error(f"Standard parser failed for {filename}: {e}")
                error_msg = f"{error_msg}; Standard parser failed: {e}" if error_msg else f"Standard parser failed: {e}"
        
        if success:
            all_docs.extend(documents)
            page_count = len(documents)
            content_length = sum(len(d.page_content) for d in documents)
            
            info = {
                "filename": file.filename,
                "success": True,
                "page_count": page_count,
                "content_length": content_length
            }
            if error_msg:
                info["warning"] = error_msg
            file_infos.append(info)
        else:
            file_infos.append({
                "filename": file.filename,
                "success": False,
                "error": error_msg or "Failed to extract content."
            })
            
    try:
        if not all_docs:
            return {
                "success": False,
                "message": "No text content could be extracted from document files",
                "files_processed": len(doc_files),
                "file_details": file_infos
            }
        
        user_session_dir = os.path.join('users', user_session)
        os.makedirs(user_session_dir, exist_ok=True)
        
        store_vector([all_docs], user_session, is_new_container, file_infos)
        
        threading.Thread(target=create_abstractive_summary, args=(user_session,)).start()
        
        successful_files = sum(1 for info in file_infos if info.get('success', False))
        
        return {
            "success": True,
            "files_processed": len(doc_files),
            "files_successful": successful_files,
            "file_details": file_infos
        }
        
    except Exception as e:
        logger.error(f"Error storing vector / creating summary: {e}")
        return {
            "success": False,
            "message": f"Error storing extracted documents: {str(e)}",
            "files_processed": len(doc_files),
            "file_details": file_infos
        }

def process_data_files(data_files: List, user_session: str, is_new_container: bool) -> Dict[str, Any]:
    """
    Process CSV/Excel files using existing SQL table creation
    
    Returns:
        Dict with processing results
    """
    if not data_files:
        return {"success": True, "files_processed": 0, "file_details": []}
    
    try:
        logger.info(f"Processing {len(data_files)} data files")
        
        # Use existing SQL table creation logic
        if is_new_container:
            success, message = create_database_with_tables(user_session, data_files)
        else:
            success, message = add_tables_to_existing_db(user_session, data_files)
        
        if not success:
            return {
                "success": False,
                "message": f"Failed to create database tables: {message}",
                "files_processed": len(data_files),
                "file_details": []
            }
        
        # Create summaries asynchronously
        for file in data_files:
            threading.Thread(target=store_table_info, args=(user_session, file.filename)).start()
        
        file_details = [{"filename": f.filename, "success": True} for f in data_files]
        
        return {
            "success": True,
            "files_processed": len(data_files),
            "files_successful": len(data_files),
            "file_details": file_details
        }
        
    except Exception as e:
        logger.error(f"Error processing data files: {e}")
        return {
            "success": False,
            "message": f"Error processing data files: {str(e)}",
            "files_processed": len(data_files),
            "file_details": []
        }

def process_mongo_files(mongo_files: List, user_session: str, is_new_container: bool) -> Dict[str, Any]:
    """
    Process uploaded JSON files into this session's own MongoDB database
    (mirrors process_data_files, but for MongoDB instead of MySQL).

    Returns:
        Dict with processing results
    """
    if not mongo_files:
        return {"success": True, "files_processed": 0, "file_details": []}

    try:
        logger.info(f"Processing {len(mongo_files)} Mongo data files")

        if is_new_container:
            success, message = create_mongo_collections(user_session, mongo_files)
        else:
            success, message = add_collections_to_existing_db(user_session, mongo_files)

        if not success:
            return {
                "success": False,
                "message": f"Failed to create Mongo collections: {message}",
                "files_processed": len(mongo_files),
                "file_details": []
            }

        file_details = [{"filename": f.filename, "success": True} for f in mongo_files]

        return {
            "success": True,
            "files_processed": len(mongo_files),
            "files_successful": len(mongo_files),
            "file_details": file_details
        }

    except Exception as e:
        logger.error(f"Error processing Mongo files: {e}")
        return {
            "success": False,
            "message": f"Error processing Mongo files: {str(e)}",
            "files_processed": len(mongo_files),
            "file_details": []
        }

def process_urls(urls: List[str], user_session: str, is_new_container: bool) -> Dict[str, Any]:
    """
    Process URLs using the new URL content service.
    
    Args:
        urls: List of URL strings to process
        user_session: User session identifier
        is_new_container: Whether to create a new container or add to existing
        
    Returns:
        Dict with processing results
    """
    if not urls:
        return {"success": True, "urls_processed": 0, "url_details": []}
    
    try:
        logger.info(f"Processing {len(urls)} URLs")
        
        # Get URL content service
        url_service = get_url_content_service()
        
        # Process URLs
        result = url_service.process_urls(urls, user_session)
        
        if not result["success"]:
            return {
                "success": False,
                "message": "URL processing failed",
                "urls_processed": len(urls),
                "url_details": result.get("url_details", [])
            }
        
        # Store URL documents if any were extracted
        if result["url_documents"]:
            user_session_dir = os.path.join('users', user_session)
            os.makedirs(user_session_dir, exist_ok=True)
            
            # Create file info list for URL documents
            url_file_infos = []
            for detail in result["url_details"]:
                if detail["success"]:
                    url_file_infos.append({
                        "filename": f"url_{hash(detail['url']) % 10000}.txt",
                        "success": True,
                        "url": detail["url"],
                        "title": detail.get("title", "Unknown"),
                        "extraction_method": detail.get("extraction_method", "unknown")
                    })
            
            # Store as vectors
            store_vector([result["url_documents"]], user_session, is_new_container, url_file_infos)
            
            # Create summaries asynchronously
            threading.Thread(target=create_abstractive_summary, args=(user_session,)).start()
        
        return {
            "success": True,
            "urls_processed": result["urls_processed"],
            "urls_successful": result["urls_successful"],
            "url_details": result["url_details"]
        }
        
    except Exception as e:
        logger.error(f"Error processing URLs: {e}")
        return {
            "success": False,
            "message": f"Error processing URLs: {str(e)}",
            "urls_processed": len(urls),
            "url_details": []
        }

class DocumentService:
    """Enhanced document service with clean URL support."""
    
    def __init__(self):
        logger.info("Initializing enhanced DocumentService")
    
    def process_files_and_urls(self, files: Any, urls: List[str], user_session: str, 
                             is_new_container: bool = True, is_trial: bool = False, session_id: str | None = None, email: str = "") -> Dict[str, Any]:
        """
        Process uploaded files and URLs with automatic type detection and routing.
        
        Args:
            files: The files from the request
            urls: List of URL strings to process
            user_session: User session identifier
            is_new_container: Whether to create a new container or add to existing
            is_trial: Whether this is for a trial user
            
        Returns:
            Dict containing processing results and status
        """
        start_time = time.time()
        logger.info(f"Processing files and URLs for session {user_session}")

        # Store files locally using FileStorageService
        file_storage_service = get_file_storage_service()
        file_storage_service.save_files(files, user_session)
        
        # Extract file list
        file_list = files.getlist("files") if files else []
        
        # Check if any files or URLs were provided
        if (not file_list or file_list[0].filename == '') and not urls:
            return {
                "status": "error",
                "message": "Please upload files or provide URLs to process."
            }
        
        # Log incoming files and URLs for debugging
        logger.info(f"Received {len(file_list)} files and {len(urls)} URLs for processing")
        for i, file in enumerate(file_list):
            logger.info(f"File {i+1}: {file.filename} (type: {file.content_type})")
        for i, url in enumerate(urls):
            logger.info(f"URL {i+1}: {url}")

        # Classify files by type (no more URL files)
        document_files, data_files, mongo_files, unsupported_files = classify_files(file_list)

        logger.info(f"File classification: {len(document_files)} documents, {len(data_files)} data files, {len(mongo_files)} Mongo (JSON) files, {len(unsupported_files)} unsupported")

        # Check for unsupported files
        if unsupported_files:
            unsupported_names = [f.filename for f in unsupported_files]
            logger.warning(f"Unsupported files: {unsupported_names}")

        # Validate trial restrictions
        if is_trial and (data_files or mongo_files):
            return {
                "status": "error",
                "message": "CSV/JSON data files are not supported in free trial mode."
            }

        # Check if we have any processable content
        if not document_files and not data_files and not mongo_files and not urls:
            return {
                "status": "error",
                "message": "No valid files or URLs found. Please upload files in PDF, DOC, DOCX, TXT, CSV, XLSX, JSON format or provide valid URLs."
            }

        # Delete previous session if needed for trial users
        if is_trial and is_new_container:
            try:
                logger.info(f"Deleting previous trial session for {user_session}")
                delete_session(user_session)
            except Exception as e:
                logger.warning(f"Error deleting previous session: {e}")

        # Process data files first (CSV/Excel)
        data_result = process_data_files(data_files, user_session, is_new_container)

        # Process Mongo data files (JSON)
        mongo_result = process_mongo_files(mongo_files, user_session, is_new_container)

        # Process document files (PDF, DOCX, TXT)
        doc_result = process_document_files(document_files, user_session,
                                          is_new_container and not data_result.get("files_successful", 0)
                                          and not mongo_result.get("files_successful", 0))

        # Process URLs
        url_result = process_urls(urls, user_session,
                                is_new_container and not data_result.get("files_successful", 0)
                                and not mongo_result.get("files_successful", 0)
                                and not doc_result.get("files_successful", 0))

        # Log processing results
        logger.info(f"Processing results - Data: {data_result['success']}, Mongo: {mongo_result['success']}, Documents: {doc_result['success']}, URLs: {url_result['success']}")

        # Combine results
        total_files_processed = data_result["files_processed"] + mongo_result["files_processed"] + doc_result["files_processed"]
        total_files_successful = data_result.get("files_successful", 0) + mongo_result.get("files_successful", 0) + doc_result.get("files_successful", 0)
        total_urls_processed = url_result.get("urls_processed", 0)
        total_urls_successful = url_result.get("urls_successful", 0)

        all_details = (data_result["file_details"] + mongo_result["file_details"] + doc_result["file_details"] +
                      url_result.get("url_details", []))
        
        # Add unsupported files to details
        for unsupported_file in unsupported_files:
            all_details.append({
                "filename": unsupported_file.filename,
                "success": False,
                "error": "Unsupported file type"
            })
        
        # Determine overall success
        overall_success = data_result["success"] and mongo_result["success"] and doc_result["success"] and url_result["success"]
        
        if overall_success and (total_files_successful > 0 or total_urls_successful > 0):
            response_data = {
                "status": "ok",
                "message": "Content successfully processed.",
                "files_processed": total_files_processed,
                "files_successful": total_files_successful,
                "urls_processed": total_urls_processed,
                "urls_successful": total_urls_successful,
                "details": all_details,
                "processing_time": time.time() - start_time
            }

            # create_session(email="carnot_test", session_id=session_id, files=file_list)
            if is_new_container:
                create_session(email=email, session_id=session_id, files=file_list)
            else:
                add_files_to_session(email=email, session_id=session_id,
                                    file_names=[f.filename for f in file_list])
            
            return response_data
        else:
            error_messages = []
            if not data_result["success"]:
                error_messages.append(data_result.get("message", "Data file processing failed"))
            if not mongo_result["success"]:
                error_messages.append(mongo_result.get("message", "Mongo file processing failed"))
            if not doc_result["success"]:
                error_messages.append(doc_result.get("message", "Document file processing failed"))
            if not url_result["success"]:
                error_messages.append(url_result.get("message", "URL processing failed"))
            
            return {
                "status": "error",
                "message": "; ".join(error_messages) if error_messages else "Processing failed",
                "files_processed": total_files_processed,
                "files_successful": total_files_successful,
                "urls_processed": total_urls_processed,
                "urls_successful": total_urls_successful,
                "details": all_details
            }
    
    def fetch_file_path(self, user_session: str, filename: str) -> str:
        """Retrieve file path for the requested user file"""
        try:
            file_service = get_file_storage_service()
            # Check if file exists
            if not file_service.file_exists(user_session, filename):
                return ""
            logger.info(f'file exists: {filename}')
            
            return file_service.get_file_path(user_session, filename)
        except Exception as e:
            logger.error(f'Error getting filename: {e}')
            return ""

    def delete_container(self, user_session: str, email: str, session_id: str) -> bool:
        """Delete a user's container and associated data"""
        try:
            logger.info(f"Deleting container for session {user_session}")
            delete_session(user_session)
            delete_session_from_db(email, session_id)
            return True
        except Exception as e:
            logger.error(f'Error deleting container: {e}')
            return False
    
    def rename_container(self, session_id: str, new_name: str) -> bool:
        """Rename a user's container"""
        try:            
            logger.info(f"Renaming container for session {session_id} to {new_name}")
            result = rename_session(session_id, new_name)
            return result
        except Exception as e:
            logger.error(f'Error renaming container: {e}')
            return False
    
    def update_container_timestamp(self, email: str, session_id: str) -> bool:
        """Update the timestamp of a user's container"""
        try:            
            logger.info(f"Updating timestamp for user {email}, session {session_id}")
            update_session_timestamp(email, session_id)
            return True
        except Exception as e:
            logger.error(f'Error updating container timestamp: {e}')
            return False
    
    def delete_source(self, user_session: str, session_id: str, filename: str) -> bool:
        """Remove a single source file from a container (Elasticsearch + DB + local storage)."""
        try:
            logger.info(f"Deleting source '{filename}' from session {user_session}")
            ElasticDocumentManager(user_session).delete_documents_by_filename(filename)
            remove_file_from_session(session_id, filename)
            get_file_storage_service().delete_file(user_session, filename)
            return True
        except Exception as e:
            logger.error(f"Error deleting source '{filename}' from session {user_session}: {e}")
            return False

    def fetch_user_sessions(self, email: str) -> List[Dict[str, Any]]:
        """Fetch all sessions for a user"""
        try:
            logger.info(f"Fetching sessions for user {email}")
            sessions = get_user_sessions(email)
            return sessions
        except Exception as e:
            logger.error(f'Error fetching user sessions: {e}')
            return []

# Create a singleton instance
_document_service = None

def get_document_service() -> DocumentService:
    """Get the document service singleton instance"""
    global _document_service
    if _document_service is None:
        _document_service = DocumentService()
    return _document_service