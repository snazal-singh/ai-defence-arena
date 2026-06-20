import os
import uuid
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse

from app.api.deps import get_current_user
from app.core.config import settings
from app.services.stt_service import get_stt_service

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter(tags=["STT"])

stt_service = get_stt_service()

ALLOWED_EXTENSIONS = {'wav', 'mp3', 'm4a', 'ogg', 'webm', 'aac', 'flac'}

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@router.post("/transcribe")
async def transcribe(
    request: Request,
    audio: UploadFile = File(...),
    language: str = Form("Hindi"),
    strategy: str = Form("rnnt"),
    user_email: str = Depends(get_current_user),
):
    """
    Handle speech-to-text transcription of uploaded audio files.
    
    Accepts multipart/form-data with:
    - 'audio': The audio file to transcribe
    - 'language': The name of the language (e.g. 'Hindi', 'Tamil')
    - 'strategy': The decoding strategy 'rnnt' or 'ctc' (optional, defaults to 'rnnt')
    """
    # 1. Authentication
    logger.info(f"Authenticated user {user_email} for audio transcription")

    # 2. Validation
    if not audio.filename:
        raise HTTPException(status_code=400, detail="Empty audio file filename")
        
    if not allowed_file(audio.filename):
        raise HTTPException(
            status_code=400, 
            detail=f'Unsupported file format. Allowed: {", ".join(ALLOWED_EXTENSIONS)}'
        )

    # 3. Process transcription safely
    temp_dir = os.path.abspath("temp_stt_uploads")
    os.makedirs(temp_dir, exist_ok=True)
    
    ext = audio.filename.rsplit('.', 1)[1].lower()
    temp_filename = f"stt_{uuid.uuid4().hex}.{ext}"
    temp_path = os.path.join(temp_dir, temp_filename)
    
    try:
        # Save file to temp path
        content = await audio.read()
        with open(temp_path, "wb") as f:
            f.write(content)
        logger.debug(f"Saved temp audio file to: {temp_path}")
        
        # Call STT service
        transcript = stt_service.transcribe(temp_path, language, strategy)
        
        if transcript is None:
            raise HTTPException(
                status_code=500, 
                detail="Transcription failed. Please check the model configuration."
            )
            
        return {
            'status': 'success',
            'transcription': transcript,
            'language': language,
            'strategy': strategy
        }
        
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception(f"Exception during transcribe endpoint execution: {e}")
        raise HTTPException(status_code=500, detail="Internal error during transcription processing")
        
    finally:
        # Guarantee cleanup of uploaded file
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.debug(f"Deleted temp file: {temp_path}")
            except Exception as e:
                logger.error(f"Failed to delete temp file {temp_path}: {e}")
