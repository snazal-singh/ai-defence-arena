"""
Updated delete session module with chat history integration.

This module extends the existing delete_session functionality to also handle
chat history cleanup when sessions are deleted.
"""

import os
import shutil
import logging
from typing import Dict, Any

from elastic.client import ElasticClient
from app.services.chat_history_manager import get_chat_history_manager

# Configure logging
logger = logging.getLogger(__name__)

def delete_directory(directory):
    """
    Delete a directory and its contents.
    
    Args:
        directory (str): Path to the directory to be deleted
    """
    # Check if the directory exists
    if os.path.exists(directory):
        # Remove the directory and its contents
        shutil.rmtree(directory)
        logging.info(f"Deleted directory: {directory}")
    else:
        logging.warning(f"Directory not found: {directory}")

def delete_elastic_index(index_name):
    """
    Delete an Elasticsearch index.
    
    Args:
        index_name (str): Name of the Elasticsearch index to be deleted
    """
    try:
        # Check if the index exists
        if ElasticClient().client.indices.exists(index=index_name):
            # Delete the index
            ElasticClient().client.indices.delete(index=index_name)
            logging.info(f"Deleted index: {index_name}")
        else:
            logging.warning(f"Index not found: {index_name}")
    except Exception as e:
        logging.error(f"Error deleting Elasticsearch index {index_name}: {e}")

def delete_chat_history(user_session: str) -> bool:
    """
    Delete chat history for a session.
    
    Args:
        user_session (str): User's session identifier
        
    Returns:
        bool: True if deletion was successful, False otherwise
    """
    try:        
        chat_manager = get_chat_history_manager()
        result = chat_manager.delete_session(user_session)
        
        if result:
            logging.info(f"Deleted chat history for session: {user_session}")
        else:
            logging.warning(f"Chat history not found for session: {user_session}")
        
        return result
        
    except Exception as e:
        logging.error(f"Error deleting chat history for session {user_session}: {e}")
        return False

def delete_session(user_session: str) -> Dict[str, Any]:
    """
    Delete a complete user session including documents, Elasticsearch index, and chat history.
    
    Args:
        user_session (str): User's session identifier
        
    Returns:
        Dict with deletion results for each component
    """
    results = {
        "session": user_session,
        "document_directory": False,
        "elasticsearch_index": False,
        "chat_history": False,
        "overall_success": False
    }
    
    try:
        # Construct the path to the directory
        session_path = os.path.join('users', user_session)
        
        # Delete the document directory
        try:
            delete_directory(session_path)
            results["document_directory"] = True
        except Exception as e:
            logging.error(f"Error deleting document directory for {user_session}: {e}")
        
        # Delete the Elasticsearch index
        try:
            delete_elastic_index(user_session)
            results["elasticsearch_index"] = True
        except Exception as e:
            logging.error(f"Error deleting Elasticsearch index for {user_session}: {e}")
        
        # Delete chat history
        try:
            results["chat_history"] = delete_chat_history(user_session)
        except Exception as e:
            logging.error(f"Error deleting chat history for {user_session}: {e}")
        
        # Determine overall success
        results["overall_success"] = all([
            results["document_directory"],
            results["elasticsearch_index"],
            results["chat_history"]
        ])
        
        if results["overall_success"]:
            logging.info(f"Successfully deleted complete session: {user_session}")
        else:
            logging.warning(f"Partial deletion for session {user_session}: {results}")
        
        return results
        
    except Exception as e:
        logging.error(f"Unexpected error deleting session {user_session}: {e}")
        results["error"] = str(e)
        return results

# Backward compatibility - maintain the original function signature
def delete_session_legacy(user_session: str) -> None:
    """
    Legacy delete session function for backward compatibility.
    
    Args:
        user_session (str): User's session identifier
    """
    try:
        # Use the new function but don't return the detailed results
        result = delete_session(user_session)
        
        if not result["overall_success"]:
            # Log any issues but don't raise exceptions for backward compatibility
            logging.warning(f"Partial deletion for session {user_session}")
    except Exception as e:
        logging.error(f"Error in legacy delete session for {user_session}: {e}")

# For backward compatibility, keep the original function name available
# but use the new implementation
def delete_session_original(user_session):
    """Original delete_session function - now enhanced with chat history cleanup."""
    return delete_session_legacy(user_session)

# Export both the new and legacy functions
__all__ = [
    'delete_session',
    'delete_session_legacy', 
    'delete_chat_history',
    'delete_directory',
    'delete_elastic_index'
]