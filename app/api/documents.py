"""
Document management API routes.

This module defines routes for document upload, processing, and container management.
"""

import logging
from flask import Blueprint, request, jsonify, send_file
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
import mimetypes
import json
from app.services.auth_service import get_auth_service
from app.services.document_service import get_document_service

# Configure logging
logger = logging.getLogger(__name__)

# Create blueprint
documents_bp = Blueprint('documents', __name__)

# Get service instances
auth_service = get_auth_service()
document_service = get_document_service()

# ----------------------------------------
# Free Trial Routes (keeping existing code)
# ----------------------------------------

@documents_bp.route('/freeTrial', methods=['POST', 'OPTIONS'])
def free_trial(): 
    """
    Handle file uploads for users in free trial mode.
    
    This endpoint processes files and URLs for users without authentication:
    1. Validates the user's fingerprint
    2. Processes uploaded files and URLs
    3. Stores the extracted text as vector embeddings
    4. Creates summaries asynchronously
    
    Request Format:
    - Form fields: fingerprint
    - Files: files (optional)
    - JSON field: urls (optional, array of strings)
    
    Returns:
        JSON response with status, message, and processing details
    """
    try:
        # Extract and validate fingerprint
        fingerprint = request.form.get('fingerprint')
        if not fingerprint:
            return jsonify({'message': 'Fingerprint is missing'}), 400
        
        # Extract URLs from request
        urls = []
        try:
            urls_json = request.form.get('urls')
            if urls_json:
                urls = json.loads(urls_json)
                if not isinstance(urls, list):
                    return jsonify({'message': 'URLs must be provided as an array'}), 400
        except json.JSONDecodeError:
            return jsonify({'message': 'Invalid URLs format. Must be valid JSON array.'}), 400
        
        # Validate URLs
        if urls:
            valid_urls = []
            for url in urls:
                if isinstance(url, str) and url.strip():
                    # Basic URL validation
                    url = url.strip()
                    if not url.startswith(('http://', 'https://')):
                        url = 'https://' + url
                    valid_urls.append(url)
            urls = valid_urls
        
        # Process files and URLs
        result = document_service.process_files_and_urls(
            request.files, urls, fingerprint, is_new_container=True, is_trial=True
        )
        
        if result.get("status") == "error":
            return jsonify({'message': result.get("message")}), 400
            
        return jsonify(result), 200
    except Exception as e:
        logger.exception(f'Error in free trial: {e}')
        return jsonify({'message': f'Error processing content: {str(e)}'}), 500

# ----------------------------------------
# Authenticated User Routes (keeping existing upload routes)
# ----------------------------------------

@documents_bp.route('/upload', methods=['POST', 'OPTIONS'])
def upload(): 
    """Handle file uploads and URLs for authenticated users to create a new container."""
    # Authenticate user
    try:
        token = request.form.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = request.form.get('sessionId')
        user_session = user_email + str(session_id.lower())
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError as e:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.exception(f'Authentication error: {e}')
        return jsonify({'message': 'Token decoding failed!'}), 401
    
    # Extract URLs from request
    urls = []
    try:
        urls_json = request.form.get('urls')
        if urls_json:
            urls = json.loads(urls_json)
            if not isinstance(urls, list):
                return jsonify({'message': 'URLs must be provided as an array'}), 400
    except json.JSONDecodeError:
        return jsonify({'message': 'Invalid URLs format. Must be valid JSON array.'}), 400
    
    # Validate URLs
    if urls:
        valid_urls = []
        for url in urls:
            if isinstance(url, str) and url.strip():
                # Basic URL validation
                url = url.strip()
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url
                valid_urls.append(url)
        urls = valid_urls
    
    # Process files and URLs
    result = document_service.process_files_and_urls(
        request.files, urls, user_session, is_new_container=True, is_trial=False,
        session_id=session_id, email=user_email
    )
    
    if result.get("status") == "error":
        return jsonify({'message': result.get("message")}), 400
        
    return jsonify(result), 200

@documents_bp.route('/add-upload', methods=['POST', 'OPTIONS'])
def add_upload():
    """Handle additional file uploads and URLs for authenticated users."""
    # Authenticate user
    try:
        token = request.form.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = request.form.get('sessionId')
        user_session = user_email + str(session_id.lower())
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError as e:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.exception(f'Authentication error: {e}')
        return jsonify({'message': 'Token decoding failed!'}), 401
    
    # Extract URLs from request
    urls = []
    try:
        urls_json = request.form.get('urls')
        if urls_json:
            urls = json.loads(urls_json)
            if not isinstance(urls, list):
                return jsonify({'message': 'URLs must be provided as an array'}), 400
    except json.JSONDecodeError:
        return jsonify({'message': 'Invalid URLs format. Must be valid JSON array.'}), 400
    
    # Validate URLs
    if urls:
        valid_urls = []
        for url in urls:
            if isinstance(url, str) and url.strip():
                # Basic URL validation
                url = url.strip()
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url
                valid_urls.append(url)
        urls = valid_urls
    
    # Process files and URLs
    result = document_service.process_files_and_urls(
        request.files, urls, user_session, is_new_container=False, is_trial=False,
        session_id=session_id, email=user_email
    )
    
    if result.get("status") == "error":
        return jsonify({'message': result.get("message")}), 400
        
    return jsonify(result), 200

@documents_bp.route('/files/<session_id>/<filename>', methods=['GET'])
def fetch_file(session_id, filename):
    """Fetch a file from local storage based on sessionId and filename."""
    # Authenticate user
    try:        
        token = request.headers.get('Authorization')
        if not token:
            # Also check query params as fallback
            token = request.args.get('token')
        
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        user_session = user_email + str(session_id.lower())
        
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError as e:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.exception(f'Authentication error: {e}')
        return jsonify({'message': 'Token decoding failed!'}), 401
    
    try:        
        # Get file path
        file_path = document_service.fetch_file_path(user_session, filename)

        if not file_path:
            return jsonify({'message': 'File not found'}), 404
        
        # Guess content type
        content_type, _ = mimetypes.guess_type(str(file_path))
        if not content_type:
            content_type = 'application/octet-stream'
        
        logger.info(f"Serving file: {file_path} for user: {user_email}")
        
        # Send file
        return send_file(
            str(file_path),
            mimetype=content_type,
            as_attachment=False,
            download_name=filename
        )
        
    except Exception as e:
        logger.exception(f"Error fetching file {filename} for session {session_id}: {e}")
        return jsonify({'message': 'Failed to fetch file'}), 500

@documents_bp.route('/timestamp', methods=['PUT'])
def update_timestamp():
    """Update the timestamp of a user's container."""
    # Authenticate user
    try:
        data = request.get_json()
        token = data.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = data.get('sessionId')
        user_session = user_email + str(session_id.lower())
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError as e:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.exception(f'Authentication error: {e}')
        return jsonify({'message': 'Token decoding failed!'}), 401
    
    # Update the timestamp in the database
    success = document_service.update_container_timestamp(user_email, session_id)
    if success:
        return jsonify({'message': 'Timestamp updated successfully'}), 200
    else:
        return jsonify({'message': 'Error updating timestamp'}), 500

@documents_bp.route('/rename-container', methods=['PUT'])
def rename_container_route():
    """Rename a user's container."""
    # Extract request parameters
    try:
        data = request.get_json()
        token = data.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = data.get('sessionId')
        new_name = data.get('newName')
        
        if not new_name or not new_name.strip():
            return jsonify({'message': 'New container name is missing or empty!'}), 400
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError as e:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.exception(f'Authentication error: {e}')
        return jsonify({'message': 'Token decoding failed!'}), 401
    
    # Rename the user's container in the database
    success = document_service.rename_container(session_id, new_name.strip())
    if success:
        return jsonify({'message': 'Container renamed successfully'}), 200
    else:
        return jsonify({'message': 'Error renaming container'}), 500

@documents_bp.route('/get-containers', methods=['GET'])
def get_containers():
    """Retrieve recent containers for an authenticated user."""
    # Authenticate user
    try:
        token = request.headers.get("Authorization").split(" ")[1]
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError as e:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.exception(f'Authentication error: {e}')
        return jsonify({'message': 'Token decoding failed!'}), 401
    
    # Fetch containers from the database
    containers = document_service.fetch_user_sessions(user_email)
    return jsonify({'data': containers}), 200

@documents_bp.route('/delete-container', methods=['DELETE'])
def delete_container_route():
    """Delete a user's container and associated data."""
    # Extract request parameters
    try:
        data = request.get_json()
        token = data.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = data.get('sessionId')
        user_session = user_email + str(session_id.lower())
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError as e:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.exception(f'Authentication error: {e}')
        return jsonify({'message': 'Token decoding failed!'}), 401
    
    # Delete the user's container from the database
    success = document_service.delete_container(user_session, user_email, session_id)
    if success:
        return jsonify({'message': 'Container deleted successfully'}), 200
    else:
        return jsonify({'message': 'Error deleting container'}), 500