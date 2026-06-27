"""
Document querying API routes.

This module defines routes for document querying and LLM interactions.
"""

import logging
from flask import Blueprint, request, jsonify, current_app, Response, stream_with_context
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
import json
import time
import os
from flask import send_from_directory

from app.services.auth_service import get_auth_service
from app.services.query_service import get_query_service
from app.services.chat_history_manager import get_chat_history_manager
from app.services.tts_service import get_tts_service
from app.services.stt_service import get_stt_service
from app.models.chat_models import MessageRole

# Configure logging
logger = logging.getLogger(__name__)

# Create blueprint
queries_bp = Blueprint('queries', __name__)

# Get service instances
auth_service = get_auth_service()
query_service = get_query_service()
chat_history_manager = get_chat_history_manager()

# Get limiter extension
def get_limiter():
    return current_app.extensions.get("limiter")

@queries_bp.route('/chat_images/<path:filepath>')
def serve_file(filepath):
    base_dir = os.path.abspath("chat_images")
    return send_from_directory(base_dir, filepath)
# ----------------------------------------
# Gemma 4 Image Captioning
# ----------------------------------------

import requests
import base64
import uuid
import os
GEMMA_SERVER_BASE_URL = os.getenv("GEMMA_SERVER_BASE_URL") 
GEMMA4_API_KEY = os.getenv("GEMMA4_API_KEY") 
GEMMA4_MODEL = os.getenv("GEMMA4_MODEL") 

def get_image_caption(image_path):
    try:
        with open(image_path, "rb") as f:
            image_base64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "model": GEMMA4_MODEL,
            "messages": [{
                "role": "user",
                "content": "Describe this image in detail. Mention all objects, text, charts, or any relevant content you see.",
                "images": [image_base64]
            }],
            "stream": False
        }

        headers = {
            "Authorization": f"Bearer {GEMMA4_API_KEY}",
            "Content-Type": "application/json"
        }

        response = requests.post(
            f"{GEMMA_SERVER_BASE_URL}/cdot/ollama2/api/chat",
            json=payload,
            headers=headers,
            timeout=60
        )
        response.raise_for_status()
        caption = response.json()["message"]["content"]
        logger.info(f" Gemma 4 Caption: {caption}")
        print(f"[CAPTION] {caption}")
        return caption

    except Exception as e:
        logger.error(f"Gemma 4 captioning error: {e}")
        return ""

# ----------------------------------------
# Trial User Query Routes
# ----------------------------------------


@queries_bp.route('/trialAsk', methods=['POST'])
def trial_ask():
    limiter = get_limiter()
    if limiter:
        limiter.limit("20 per minute")(trial_ask)

    # Fix: check for multipart first using request.files
    if request.files.get('image') or request.form:
        data = {
            'fingerprint': request.form.get('fingerprint'),
            'message': request.form.get('message', '')
        }
        image = request.files.get('image')

        if image:
            image_path = f"/tmp/{image.filename}"
            image.save(image_path)

            caption = get_image_caption(image_path)

            if data['message']:
                data['message'] = f"{data['message']}\n\nImage Description: {caption}"
            else:
                data['message'] = f"Image Description: {caption}"
            print(f"📨 FINAL MESSAGE SENT TO RAG:\n{data['message']}")
            print(f"{'='*50}")
            os.remove(image_path)
    else:
        data = request.get_json()

    response, status_code = query_service.process_trial_query(data)
    return jsonify(response), status_code

# ----------------------------------------
# Authenticated User Query Routes
# ----------------------------------------

@queries_bp.route('/ask', methods=['POST'])
def ask():
    print(f"DEBUG: request.files = {request.files}")
    print(f"DEBUG: request.form = {request.form}")
    print(f"DEBUG: request.content_type = {request.content_type}")
    """
    Handle document queries for authenticated users.
    
    This endpoint:
    1. Authenticates the user using a JWT token
    2. Checks if the user has exceeded query limits
    3. Processes the user's question with chat history context
    4. Generates a response using vector search and LLMs
    5. Saves the conversation to chat history
    
    Returns:
        JSON response with answer
    """
    image = None
    caption = None
    image_url = None  # NEW

    #  ADDED - Handle image if present
    if request.files.get('image') or request.form:
        data = {
            'token': request.form.get('token'),
            'message': request.form.get('message', ''),
            'context': request.form.get('context', False),
            'chatId': request.form.get('chatId', 'default'),
            'sessionId': request.form.get('sessionId'),
            'inputLanguage': request.form.get('inputLanguage', 'en'),
            'outputLanguage': request.form.get('outputLanguage', 'en'),
            'filenames': request.form.getlist('filenames'),
            'hasCsvOrXlsx': request.form.get('hasCsvOrXlsx', False),
            'mode': request.form.get('mode', 'default'),
        }
        image = request.files.get('image')
        if image:
            # NEW - Save image permanently to files directory instead of /tmp/
            BASE_USERS_DIR = "chat_images"
            session_id_for_path = data.get('sessionId', 'default')
            ext = os.path.splitext(image.filename)[1] or ".jpg"
            image_filename = f"img_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
            image_dir = os.path.join(BASE_USERS_DIR, session_id_for_path)
            os.makedirs(image_dir, exist_ok=True)
            image_save_path = os.path.join(image_dir, image_filename)
            image.save(image_save_path)

            # Get caption from Gemma4
            caption = get_image_caption(image_save_path)

            # Build URL for frontend to fetch image
            image_url = f"/chat_images/{session_id_for_path}/{image_filename}"

            if data['message']:
                data['message'] = f"{data['message']}\n\nImage Description: {caption}"
            else:
                data['message'] = f"Image Description: {caption}"
            print(f"FINAL MESSAGE SENT TO RAG:\n{data['message']}")
            # NOTE: image is NOT deleted — kept for chat history display
    else:
        data = request.get_json()

    # ---- Authentication ----

    try:
        token = data.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_name = user_email
        context = data.get('context', False)
        chat_id = data.get('chatId', 'default')
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError as e:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.exception(f'Authentication error: {e}')
        return jsonify({'message': 'Authentication failed!'}), 401
    
    # We only need session_id when context is True
    if context:
        session_id = data.get('sessionId')
        if not session_id:
            return jsonify({'message': 'Session ID is required for context queries!'}), 400
            
        session_name = user_email + str(session_id.lower())

    # -------------------------------------------------
    # Store the user request (including any caption) before processing
    data['image_url'] = image_url
    data['image_caption'] = caption
    data['skip_user_message_storage'] = False  # let query_agent handle it

    # Now run the normal query pipeline
    response, status_code = query_service.process_authenticated_query(data, user_email, session_name, chat_id)
    # data['image_url'] = image_url
    # data['image_caption'] = caption
    # # Now run the normal query pipeline
    # response, status_code = query_service.process_authenticated_query(data, user_email, session_name, chat_id)
    return jsonify(response), status_code

@queries_bp.route('/ask-stream', methods=['GET'])
def ask_stream():
    """
    Handle document queries with streaming for creative mode.
    
    This endpoint streams progress updates and the final answer for better UX.
    """
    data = request.args
    
    # Authenticate user
    try:
        token = data.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = data.get('sessionId')
        chat_id = data.get('chatId')  # Extract chat_id from query parameters
        
        if not session_id:
            return jsonify({'message': 'Session ID is required!'}), 400
        
        if not chat_id:
            chat_id = 'default'
            
        session_name = user_email + str(session_id.lower())
    except Exception as e:
        logger.exception(f'Authentication error: {e}')
        return jsonify({'message': 'Authentication failed!'}), 401
    
    # Check if it's creative mode
    mode = data.get('mode', 'default')
    if mode != 'creative':
        # For non-creative mode, redirect to regular endpoint
        response, status_code = query_service.process_authenticated_query(data, user_email, session_name, chat_id)
        return jsonify(response), status_code
    
    # Generate streaming response with chat history context
    def generate():
        try:
            # Extract query parameters
            user_query = query_service._extract_query_parameters(data)
            
            # Apply guardrails
            guardrail_response = query_service._guardrail.process_input(user_query["message"])
            if guardrail_response.get("status") == "blocked":
                yield f"data: {json.dumps({'type': 'error', 'content': guardrail_response})}\n\n"
                return
                
            user_query["message"] = guardrail_response.get("sanitized_input", user_query["message"])
            
            # Get chat context if needed with chat_id
            chat_context = query_service.query_agent._get_chat_context_if_needed(
                user_query["message"], session_name, {}, chat_id
            )
            
            # Get streaming response from creative service with chat context
            from app.services.creative_reasoning_service import get_creative_reasoning_service
            creative_service = get_creative_reasoning_service()
            
            for event in creative_service.process_creative_query_stream(
                user_query["message"],
                session_name,
                user_query["input_language"],
                user_query["output_language"],
                user_query["filenames"],
                user_query["hascsvxl"],
                chat_context,
                chat_id
            ):
                yield f"data: {json.dumps(event)}\n\n"
                
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',  # Disable Nginx buffering
            'Connection': 'keep-alive'
        }
    )

@queries_bp.route('/ask-tts', methods=['POST'])
def ask_tts():
    """
    Handle document queries for authenticated users with TTS audio streaming.
    
    This endpoint:
    1. Authenticates the user using a JWT token
    2. Checks if the user has exceeded query limits
    3. Processes the user's question with chat history context
    4. Generates a response using vector search and LLMs
    5. Converts the response to speech using TTS service
    6. Streams audio response directly
    7. Saves the conversation to chat history
    
    Returns:
        Audio stream response (audio/mpeg)
    """
    # Apply rate limiting for TTS endpoint (more restrictive due to audio processing)
    limiter = get_limiter()
    if limiter:
        limiter.limit("10 per minute")(ask_tts)
    
    data = request.get_json()
    
    # Authenticate user
    try:
        token = data.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_name = user_email
        context = data.get('context', False)
        chat_id = data.get('chatId')
        
        if not chat_id:
            chat_id = 'default'
            
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError as e:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.exception(f'Authentication error: {e}')
        return jsonify({'message': 'Authentication failed!'}), 401
    
    # We only need session_id when context is True
    if context:
        session_id = data.get('sessionId')
        if not session_id:
            return jsonify({'message': 'Session ID is required for context queries!'}), 400
            
        session_name = user_email + str(session_id.lower())

    # Process query first to get text response
    try:
        query_response, status_code = query_service.process_authenticated_query(
            data, user_email, session_name, chat_id
        )
        
        if status_code != 200:
            # Return JSON error for non-200 responses
            return jsonify(query_response), status_code
        
        # Extract answer text from response
        answer_text = ""
        if isinstance(query_response, dict) and 'answer' in query_response:
            answer_text = query_response['answer']
        elif isinstance(query_response, str):
            answer_text = query_response
        else:
            logger.error(f"Unexpected query response format: {type(query_response)}")
            return jsonify({'message': 'Invalid response format'}), 500
        
        if not answer_text or not answer_text.strip():
            return jsonify({'message': 'Empty response generated'}), 500
            
    except Exception as e:
        logger.exception(f'Error processing query for TTS: {e}')
        return jsonify({'message': 'Error generating response'}), 500

    # Generate TTS audio stream
    try:
        tts_service = get_tts_service()
        
        output_language = str(data.get('outputLanguage', 'en')).lower().strip()
        logger.info(f"Generating TTS for user {user_email}, language: {output_language}")
        
        def generate_audio():
            """Generator function for streaming audio response."""
            try:
                chunk_count = 0
                for audio_chunk in tts_service.generate_audio_stream(answer_text, output_language):
                    chunk_count += 1
                    yield audio_chunk
                
                logger.info(f"TTS streaming completed, sent {chunk_count} audio chunks")
                
            except Exception as e:
                logger.error(f"Error during TTS streaming: {e}")
        
        # Return streaming audio response (WAV from Vexyl-TTS)
        return Response(
            generate_audio(),
            mimetype='audio/wav',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',  # Disable Nginx buffering
                'Connection': 'keep-alive',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
            }
        )
        
    except ValueError as e:
        logger.error(f"TTS service configuration error: {e}")
        return jsonify({'message': 'TTS service not available'}), 503
    except Exception as e:
        logger.exception(f'Error generating TTS audio: {e}')
        return jsonify({'message': 'Error generating audio response'}), 500

@queries_bp.route('/synthesize', methods=['POST'])
def synthesize():
    """
    Synthesize arbitrary text into speech using Vexyl-TTS.
    
    Expected JSON body:
        token (str): JWT authentication token
        text (str): The text content to synthesize
        language (str/int): Sachet language specifier (e.g. 'hindi', 'english', 1, 23)
        
    Returns:
        Audio stream response (audio/wav)
    """
    limiter = get_limiter()
    if limiter:
        limiter.limit("20 per minute")(synthesize)
        
    data = request.get_json()
    if not data:
        return jsonify({'message': 'Missing request body!'}), 400
        
    token = data.get('token')
    if not token:
        return jsonify({'message': 'Token is missing!'}), 401
        
    try:
        user_email = auth_service.authenticate(token)
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError as e:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.exception(f'Authentication error: {e}')
        return jsonify({'message': 'Authentication failed!'}), 401
        
    text = data.get('text')
    if not text or not text.strip():
        return jsonify({'message': 'Text is required!'}), 400
        
    language = data.get('language', 'english')
    
    try:
        tts_service = get_tts_service()

        logger.info(f"Synthesizing text for user {user_email}, language: {language}")

        # Collect all streamed chunks into one buffer, then fix the WAV header.
        # generate_audio_stream inflates the WAV size to 0x7f000000 for live
        # streaming, but the frontend waits for the full blob anyway. Some
        # browsers fire onerror on size-mismatched WAV files and start the next
        # sentence prematurely, causing two voices to play simultaneously.
        parts = []
        try:
            for chunk in tts_service.generate_audio_stream(text, language):
                parts.append(chunk)
        except Exception as e:
            logger.error(f"Error during synthesis: {e}")
            return jsonify({'message': 'Error generating audio response'}), 500

        if not parts:
            return jsonify({'message': 'No audio generated'}), 500

        audio_data = b''.join(parts)

        if len(audio_data) >= 44:
            header = bytearray(audio_data[:44])
            pcm_size = len(audio_data) - 44
            header[4:8] = (pcm_size + 36).to_bytes(4, 'little')
            header[40:44] = pcm_size.to_bytes(4, 'little')
            audio_data = bytes(header) + audio_data[44:]

        return Response(
            audio_data,
            mimetype='audio/wav',
            headers={
                'Content-Length': len(audio_data),
                'Cache-Control': 'no-cache',
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Content-Type',
            }
        )
    except ValueError as e:
        logger.error(f"TTS service configuration error: {e}")
        return jsonify({'message': 'TTS service not available'}), 503
    except Exception as e:
        logger.exception(f'Error generating TTS audio: {e}')
        return jsonify({'message': 'Error generating audio response'}), 500

@queries_bp.route('/tts-health', methods=['GET'])
def tts_health():
    """
    Check Vexyl-TTS service health and configuration.

    Returns:
        JSON response with TTS service status
    """
    try:
        token = request.args.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401

        auth_service.authenticate(token)

        tts_service = get_tts_service()
        connection_ok = tts_service.test_connection()

        return jsonify({
            'status': 'healthy' if connection_ok else 'degraded',
            'tts_available': connection_ok,
            'vexyl_url': tts_service.vexyl_url,
            'message': 'Vexyl-TTS is ready' if connection_ok else 'Vexyl-TTS is not reachable'
        })

    except Exception as e:
        logger.error(f'TTS health check error: {e}')
        return jsonify({
            'status': 'unhealthy',
            'tts_available': False,
            'message': 'TTS service error'
        }), 500


# ----------------------------------------
# STT Routes (Vexyl-STT)
# ----------------------------------------

@queries_bp.route('/stt-transcribe', methods=['POST'])
def stt_transcribe():
    """
    Transcribe an audio file via Vexyl-STT batch API.

    Accepts multipart/form-data with:
        token    - JWT authentication token
        audio    - audio file (WAV/MP3/OGG/FLAC/WEBM)
        language - language code or 'auto' (default: auto)

    Returns:
        JSON: {transcript, language, latency_ms, job_id}
    """
    # Auth
    try:
        token = request.form.get('token') or (request.get_json(silent=True) or {}).get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        auth_service.authenticate(token)
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.exception(f'STT auth error: {e}')
        return jsonify({'message': 'Authentication failed!'}), 401

    audio_file = request.files.get('audio')
    if not audio_file:
        return jsonify({'message': 'No audio file provided'}), 400

    language = request.form.get('language', 'auto')

    try:
        audio_bytes = audio_file.read()
        if not audio_bytes:
            return jsonify({'message': 'Audio file is empty'}), 400

        stt_service = get_stt_service()
        result = stt_service.transcribe_audio_bytes(
            audio_bytes=audio_bytes,
            language=language,
            filename=audio_file.filename or 'audio.wav',
        )
        return jsonify(result)

    except RuntimeError as e:
        logger.error(f'STT transcription error: {e}')
        return jsonify({'message': str(e)}), 502
    except TimeoutError as e:
        logger.error(f'STT transcription timeout: {e}')
        return jsonify({'message': 'Transcription timed out'}), 504
    except Exception as e:
        logger.exception(f'STT unexpected error: {e}')
        return jsonify({'message': 'Transcription failed'}), 500


@queries_bp.route('/stt-health', methods=['GET'])
def stt_health():
    """
    Check Vexyl-STT service health.

    Returns:
        JSON: {status, stt_available, vexyl_url, message}
    """
    try:
        token = request.args.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        auth_service.authenticate(token)

        stt_service = get_stt_service()
        connection_ok = stt_service.test_connection()

        return jsonify({
            'status': 'healthy' if connection_ok else 'degraded',
            'stt_available': connection_ok,
            'vexyl_url': stt_service.stt_url,
            'message': 'Vexyl-STT is ready' if connection_ok else 'Vexyl-STT is not reachable'
        })

    except Exception as e:
        logger.error(f'STT health check error: {e}')
        return jsonify({
            'status': 'unhealthy',
            'stt_available': False,
            'message': 'STT service error'
        }), 500


# ----------------------------------------
# Notes Management Routes
# ----------------------------------------

@queries_bp.route('/notes/toggle', methods=['POST'])
def toggle_note():
    try:
        data = request.get_json()
        
        token = data.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = data.get('sessionId')
        chat_id = data.get('chatId')
        message_id = data.get('messageId')
        
        if not session_id:
            return jsonify({'message': 'Session ID is required!'}), 400
        
        if not chat_id:
            chat_id = 'default'
        
        if not message_id:
            return jsonify({'message': 'Message ID is required!'}), 400
            
        user_session = user_email + str(session_id.lower())
        
        success = chat_history_manager.toggle_message_note(user_session, chat_id, message_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Note state toggled successfully',
                'message_id': message_id
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to toggle note state or message not found'
            }), 404
        
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.error(f'Error toggling note: {e}')
        return jsonify({'message': 'Error toggling note'}), 500

@queries_bp.route('/notes/list', methods=['GET'])
def list_notes():
    try:
        token = request.args.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = request.args.get('sessionId')
        
        if not session_id:
            return jsonify({'message': 'Session ID is required!'}), 400
            
        user_session = user_email + str(session_id.lower())
        notes = chat_history_manager.get_saved_notes(user_session)
        
        return jsonify({
            'success': True,
            'notes': notes,
            'total_notes': len(notes)
        })
        
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.error(f'Error listing notes: {e}')
        return jsonify({'message': 'Error retrieving notes'}), 500

# ----------------------------------------
# Chat History Management Routes
# ----------------------------------------

@queries_bp.route('/chat-history', methods=['GET'])
def get_chat_history():
    try:
        token = request.args.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = request.args.get('sessionId')
        chat_id = request.args.get('chatId')
        
        if not session_id:
            return jsonify({'message': 'Session ID is required!'}), 400
        
        user_session = user_email + str(session_id.lower())
        
        if not chat_id:
            latest_empty_chat = chat_history_manager.get_latest_empty_chat(user_session)
            
            if latest_empty_chat:
                return jsonify({
                    'success': True, 
                    'messages': [], 
                    'total_messages': 0,
                    'chatId': latest_empty_chat["chat_id"],
                    'chatName': latest_empty_chat["chat_name"],
                    'session_exists': True
                }), 200
            else:
                chat_id = str(int(time.time() * 1000))
                chat_history_manager._create_chat_name_entry(user_session, chat_id)
                
                return jsonify({
                    'success': True, 
                    'messages': [], 
                    'total_messages': 0,
                    'chatId': chat_id,
                    'chatName': chat_history_manager._generate_default_chat_name(),
                    'session_exists': False
                }), 201
        
        limit = int(request.args.get('limit', 20))
        limit = min(limit, 100)
        
        chat_session = chat_history_manager._get_session(user_session, chat_id)
        chat_name = chat_history_manager._get_chat_name(user_session, chat_id)
        if not chat_name:
            chat_name = chat_history_manager._generate_default_chat_name()
            chat_history_manager._create_chat_name_entry(user_session, chat_id, chat_name)
        
        if not chat_session:
            return jsonify({
                'success': True,
                'messages': [],
                'total_messages': 0,
                'session_exists': False,
                'chatId': chat_id,
                'chatName': chat_name
            })
        
        recent_messages = chat_session.get_recent_messages(limit)
        
        messages = []
        for msg in recent_messages:
            msg_dict = msg.to_dict()
            messages.append({
                'message_id': msg_dict.get("message_id"),
                'timestamp': msg_dict.get("timestamp"),
                'role': msg_dict.get("role"),
                'content': msg_dict.get("content"),
                'query_type': msg_dict.get("query_type"),
                'save_to_note': msg_dict.get("save_to_note", False),
                'image_url': msg_dict.get("image_url", ""),        # NEW
                'image_caption': msg_dict.get("image_caption", "") # NEW
            })
        
        return jsonify({
            'success': True,
            'messages': messages,
            'total_messages': chat_session.total_messages,
            'session_exists': True,
            'chatId': chat_id,
            'chatName': chat_name
        })
        
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.error(f'Error getting chat history: {e}')
        return jsonify({'message': 'Error retrieving chat history'}), 500

@queries_bp.route('/chat-history/list', methods=['GET'])
def list_chats():
    try:
        token = request.args.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = request.args.get('sessionId')
        
        if not session_id:
            return jsonify({'message': 'Session ID is required!'}), 400
            
        user_session = user_email + str(session_id.lower())
        chats = chat_history_manager.list_chats(user_session)
        
        return jsonify({
            'success': True,
            'chats': chats,
            'total_chats': len(chats)
        })
        
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.error(f'Error listing chats: {e}')
        return jsonify({'message': 'Error retrieving chat list'}), 500

@queries_bp.route('/chat-history/rename', methods=['PUT'])
def rename_chat():
    try:
        data = request.get_json()
        
        token = data.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = data.get('sessionId')
        chat_id = data.get('chatId')
        new_chat_name = data.get('newChatName')
        
        if not session_id:
            return jsonify({'message': 'Session ID is required!'}), 400
        
        if not chat_id:
            chat_id = 'default'
        
        if not new_chat_name or not new_chat_name.strip():
            return jsonify({'message': 'New chat name is required!'}), 400
            
        user_session = user_email + str(session_id.lower())
        
        new_chat_name = new_chat_name.strip()
        if len(new_chat_name) > 100:
            return jsonify({'message': 'Chat name is too long (max 100 characters)!'}), 400
        
        success = chat_history_manager.update_chat_name(user_session, chat_id, new_chat_name)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Chat renamed successfully',
                'chat_id': chat_id,
                'new_chat_name': new_chat_name
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to rename chat'
            }), 500
        
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.error(f'Error renaming chat: {e}')
        return jsonify({'message': 'Error renaming chat'}), 500
        
@queries_bp.route('/chat-history/stats', methods=['GET'])
def get_chat_history_stats():
    try:
        token = request.args.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = request.args.get('sessionId')
        chat_id = request.args.get('chatId')
        
        if not session_id:
            return jsonify({'message': 'Session ID is required!'}), 400
        
        if not chat_id:
            chat_id = 'default'
            
        user_session = user_email + str(session_id.lower())
        stats = chat_history_manager.get_session_stats(user_session, chat_id)
        
        return jsonify({
            'success': True,
            'stats': stats
        })
        
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.error(f'Error getting chat history stats: {e}')
        return jsonify({'message': 'Error retrieving statistics'}), 500

@queries_bp.route('/chat-history/clear', methods=['DELETE'])
def clear_chat_history():
    try:
        if request.is_json and request.get_json():
            data = request.get_json()
        else:
            data = {
                'token': request.args.get('token'),
                'sessionId': request.args.get('sessionId'),
                'chatId': request.args.get('chatId')
            }
        
        token = data.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = data.get('sessionId')
        chat_id = data.get('chatId')
        
        if not session_id:
            return jsonify({'message': 'Session ID is required!'}), 400
        
        if not chat_id:
            chat_id = 'default'
            
        user_session = user_email + str(session_id.lower())
        success = chat_history_manager.delete_session(user_session, chat_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Chat history cleared successfully',
                'chat_id': chat_id
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to clear chat history'
            }), 500
        
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.error(f'Error clearing chat history: {e}')
        return jsonify({'message': 'Error clearing chat history'}), 500

@queries_bp.route('/chat-history/clear-all', methods=['DELETE'])
def clear_all_chats():
    try:
        if request.is_json and request.get_json():
            data = request.get_json()
        else:
            data = {
                'token': request.args.get('token'),
                'sessionId': request.args.get('sessionId')
            }
        
        token = data.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = data.get('sessionId')
        
        if not session_id:
            return jsonify({'message': 'Session ID is required!'}), 400
            
        user_session = user_email + str(session_id.lower())
        deleted_count = chat_history_manager.delete_all_chats_for_session(user_session)
        
        return jsonify({
            'success': True,
            'message': f'Cleared {deleted_count} chats successfully',
            'deleted_count': deleted_count
        })
        
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.error(f'Error clearing all chats: {e}')
        return jsonify({'message': 'Error clearing all chats'}), 500

# ----------------------------------------
# Demo Query Routes
# ----------------------------------------

@queries_bp.route('/demo', methods=['POST'])
def demo():
    limiter = get_limiter()
    if limiter:
        limiter.limit("10 per minute")(demo)
    
    data = request.get_json()
    response, status_code = query_service.process_demo_query(data)
    return jsonify(response), status_code

# ----------------------------------------
# Chat Context Analysis Routes
# ----------------------------------------

@queries_bp.route('/chat-context/analyze', methods=['POST'])
def analyze_chat_context():
    try:
        data = request.get_json()
        
        token = data.get('token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        
        user_email = auth_service.authenticate(token)
        session_id = data.get('sessionId')
        chat_id = data.get('chatId')
        query = data.get('query', '')
        
        if not session_id:
            return jsonify({'message': 'Session ID is required!'}), 400
        
        if not chat_id:
            chat_id = 'default'
        
        if not query:
            return jsonify({'message': 'Query is required!'}), 400
            
        user_session = user_email + str(session_id.lower())
        
        from app.services.chat_context_service import get_chat_context_service
        context_service = get_chat_context_service()
        
        session_stats = chat_history_manager.get_session_stats(user_session, chat_id)
        has_history = session_stats.get("exists", False) and session_stats.get("total_messages", 0) > 0
        
        analysis = context_service.detect_context_need(query, has_history)
        
        return jsonify({
            'success': True,
            'analysis': analysis,
            'session_has_history': has_history,
            'session_stats': session_stats,
            'chat_id': chat_id
        })
        
    except ExpiredSignatureError:
        return jsonify({'message': 'Token has expired!'}), 401
    except InvalidTokenError:
        return jsonify({'message': 'Token is invalid!'}), 401
    except Exception as e:
        logger.error(f'Error analyzing chat context: {e}')
        return jsonify({'message': 'Error analyzing context'}), 500