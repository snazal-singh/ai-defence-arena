"""
Blueprint API routes for Speech-to-Text (STT) processing.
"""

import os
import uuid
import logging
from flask import Blueprint, request, jsonify
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from app.services.auth_service import get_auth_service
from app.services.stt_service import get_stt_service

logger = logging.getLogger(__name__)

# Create blueprint
stt_bp = Blueprint('stt', __name__)

# Get service instances
auth_service = get_auth_service()
stt_service = get_stt_service()

ALLOWED_EXTENSIONS = {'wav', 'mp3', 'm4a', 'ogg', 'webm', 'aac', 'flac'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@stt_bp.route('/transcribe', methods=['POST'])
def transcribe():
    """
    Handle speech-to-text transcription of uploaded audio files.
    
    Accepts multipart/form-data with:
    - 'audio': The audio file to transcribe
    - 'language': The name of the language (e.g. 'Hindi', 'Tamil')
    - 'strategy': The decoding strategy 'rnnt' or 'ctc' (optional, defaults to 'rnnt')
    - 'token': JWT authentication token (optional in form, can be in headers/args)
    """
    # 1. Authentication Check
    token = request.form.get('token') or request.args.get('token') or request.headers.get('Authorization')
    if token and token.startswith('Bearer '):
        token = token[7:]
        
    if not token:
        logger.warning("Transcription request missing auth token.")
        return jsonify({'message': 'Token is missing!'}), 401
        
    try:
        user_email = auth_service.authenticate(token)
        logger.info(f"Authenticated user {user_email} for audio transcription")
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.exception(f"Authentication failed: {e}")
        return jsonify({'message': 'Authentication failed!'}), 401

    # 2. Input Payload Parsing
    if 'audio' not in request.files:
        return jsonify({'message': 'No audio file provided'}), 400
        
    audio_file = request.files['audio']
    language = request.form.get('language', 'Hindi')
    strategy = request.form.get('strategy', 'rnnt')
    
    if audio_file.filename == '':
        return jsonify({'message': 'Empty audio file filename'}), 400
        
    if not allowed_file(audio_file.filename):
        return jsonify({'message': f'Unsupported file format. Allowed: {", ".join(ALLOWED_EXTENSIONS)}'}), 400

    # 3. Process transcription safely
    temp_dir = os.path.abspath("temp_stt_uploads")
    os.makedirs(temp_dir, exist_ok=True)
    
    ext = audio_file.filename.rsplit('.', 1)[1].lower()
    temp_filename = f"stt_{uuid.uuid4().hex}.{ext}"
    temp_path = os.path.join(temp_dir, temp_filename)
    
    try:
        # Save file to temp path
        audio_file.save(temp_path)
        logger.debug(f"Saved temp audio file to: {temp_path}")
        
        # Call STT service
        transcript = stt_service.transcribe(temp_path, language, strategy)
        
        if transcript is None:
            return jsonify({'message': 'Transcription failed. Please check the model configuration.'}), 500
            
        return jsonify({
            'status': 'success',
            'transcription': transcript,
            'language': language,
            'strategy': strategy
        }), 200
        
    except Exception as e:
        logger.exception(f"Exception during transcribe endpoint execution: {e}")
        return jsonify({'message': 'Internal error during transcription processing'}), 500
        
    finally:
        # Guarantee cleanup of uploaded file
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                logger.debug(f"Deleted temp file: {temp_path}")
            except Exception as e:
                logger.error(f"Failed to delete temp file {temp_path}: {e}")
