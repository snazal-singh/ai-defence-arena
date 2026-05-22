import shutil
from pathlib import Path
from werkzeug.utils import secure_filename
import logging

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # go up from app/service/
UPLOADS_DIR = PROJECT_ROOT / "files"

class FileStorageService:
    def __init__(self, base_upload_dir=UPLOADS_DIR):
        """Initialize the file storage service with a base directory."""
        self.base_upload_dir = Path(base_upload_dir)
        self.base_upload_dir.mkdir(exist_ok=True, parents=True)
    
    def clean_filename(self, filename: str) -> str:
        """Clean filename by removing temporary path prefixes and securing it."""
        if not filename:
            return filename
        
        # Handle both Windows and Unix paths
        if '\\' in filename:
            filename = filename.split('\\')[-1]
        if '/' in filename:
            filename = filename.split('/')[-1]
        
        # Use secure_filename for additional security
        return secure_filename(filename)
    
    def get_session_directory(self, user_session: str) -> Path:
        """Get the directory path for a specific session."""
        # session_dir = self.base_upload_dir / "carnot_test1758108569065sfspo89r6"
        session_dir = self.base_upload_dir / user_session
        session_dir.mkdir(exist_ok=True)
        return session_dir
    
    def save_single_file(self, file, user_session: str) -> dict:
        """Save a single file to the session directory."""
        try:
            if not file or not file.filename:
                return {"status": "error", "message": "Invalid file"}
            
            # Clean the filename
            clean_name = self.clean_filename(file.filename)
            if not clean_name:
                return {"status": "error", "message": "Invalid filename"}
            
            # Get session directory
            session_dir = self.get_session_directory(user_session)
            file_path = session_dir / clean_name
            
            # Handle duplicate filenames by adding a counter
            counter = 1
            original_name = clean_name
            name_parts = original_name.rsplit('.', 1)
            
            while file_path.exists():
                if len(name_parts) == 2:
                    clean_name = f"{name_parts[0]}_{counter}.{name_parts[1]}"
                else:
                    clean_name = f"{original_name}_{counter}"
                file_path = session_dir / clean_name
                counter += 1
            
            # Save the file
            file.save(str(file_path))
            
            logger.info(f"File saved: {file_path}")
            return {
                "status": "success",
                "filename": clean_name,
                "original_filename": file.filename,
                "path": str(file_path),
                "size": file_path.stat().st_size
            }
            
        except Exception as e:
            logger.exception(f"Error saving file: {e}")
            return {"status": "error", "message": f"Failed to save file: {str(e)}"}
    
    def save_files(self, files, user_session: str) -> dict:
        """Save multiple files to the session directory."""
        results = []
        errors = []
        
        uploaded_files = files.getlist("files")  
        for file in uploaded_files:
            result = self.save_single_file(file, user_session)
            if result["status"] == "success":
                results.append(result)
            else:
                errors.append(result)
        
        return {
            "status": "success" if len(errors) == 0 else "partial" if len(results) > 0 else "error",
            "saved_files": results,
            "errors": errors,
            "total_saved": len(results),
            "total_errors": len(errors)
        }
    
    def get_file_path(self, user_session: str, filename: str) -> Path:
        """Get the full path to a specific file."""
        session_dir = self.get_session_directory(user_session)
        clean_name = self.clean_filename(filename)
        return session_dir / clean_name
    
    def file_exists(self, user_session: str, filename: str) -> bool:
        """Check if a file exists in the session directory."""
        file_path = self.get_file_path(user_session, filename)
        logger.info(f'checking for file: {file_path}')
        return file_path.exists() and file_path.is_file()
    
    def list_files(self, user_session: str) -> list:
        """List all files in a session directory."""
        try:
            session_dir = self.get_session_directory(user_session)
            if not session_dir.exists():
                return []
            
            files = []
            for file_path in session_dir.iterdir():
                if file_path.is_file():
                    files.append({
                        "filename": file_path.name,
                        "size": file_path.stat().st_size,
                        "modified": file_path.stat().st_mtime
                    })
            return files
        except Exception as e:
            logger.exception(f"Error listing files: {e}")
            return []
    
    def delete_file(self, user_session: str, filename: str) -> bool:
        """Delete a specific file from the session directory."""
        try:
            file_path = self.get_file_path(user_session, filename)
            if file_path.exists():
                file_path.unlink()
                logger.info(f"File deleted: {file_path}")
                return True
            return False
        except Exception as e:
            logger.exception(f"Error deleting file: {e}")
            return False
    
    def delete_session(self, user_session: str) -> bool:
        """Delete an entire session directory and all its files."""
        try:
            session_dir = self.get_session_directory(user_session)
            if session_dir.exists():
                shutil.rmtree(session_dir)
                logger.info(f"Session directory deleted: {session_dir}")
                return True
            return False
        except Exception as e:
            logger.exception(f"Error deleting session directory: {e}")
            return False

# Create a singleton instance
_file_storage_service = None

def get_file_storage_service() -> FileStorageService:
    """Get the file storage service singleton instance"""
    global _file_storage_service
    if _file_storage_service is None:
        _file_storage_service = FileStorageService()
    return _file_storage_service