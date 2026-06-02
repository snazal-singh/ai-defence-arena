import json
import logging
import time
import os
import uuid
import base64
import requests
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse, Response

from app.api.deps import get_current_user, get_current_user_sse
from app.core.config import settings
from app.core.limiter import limiter
from app.schemas.query import (
    AnalyzeContextRequest,
    DemoQueryRequest,
    QueryRequest,
    RenameChatRequest,
    ToggleNoteRequest,
    TrialQueryRequest,
)
from app.services.chat_history_manager import get_chat_history_manager
from app.services.query_service import get_query_service

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter(tags=["Queries"])

query_service = get_query_service()
chat_history_manager = get_chat_history_manager()


# ---------------------------------------------------------------------------
# Gemma 4 Image Captioning
# ---------------------------------------------------------------------------

GEMMA_SERVER_BASE_URL = os.getenv("GEMMA_SERVER_BASE_URL")
GEMMA4_API_KEY = os.getenv("GEMMA4_API_KEY")
GEMMA4_MODEL = os.getenv("GEMMA4_MODEL")


def get_image_caption(image_path: str) -> str:
    """Query the Gemma4 vision server to generate a detailed caption for the image."""
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
        return caption

    except Exception as e:
        logger.error(f"Gemma 4 captioning error: {e}")
        return ""


# ---------------------------------------------------------------------------
# Static serving for chat images
# ---------------------------------------------------------------------------

@router.get("/chat_images/{filepath:path}")
def serve_file(filepath: str):
    """Serve saved chat images from the local chat_images directory."""
    base_dir = os.path.abspath("chat_images")
    file_path = os.path.join(base_dir, filepath)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


# ---------------------------------------------------------------------------
# Helper to authenticate user from token in headers OR payload data
# ---------------------------------------------------------------------------

import jwt

def authenticate_user_robust(request: Request, data: dict) -> str:
    """Robust authentication extracting token from headers OR form/json request data."""
    token = None
    
    # 1. Try to get from Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    
    # 2. Fallback to form/json token
    if not token and isinstance(data, dict):
        token = data.get("token")
        
    if not token:
        raise HTTPException(status_code=401, detail="Token is missing!")
        
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_email: str | None = payload.get("email")
        if user_email is None:
            raise HTTPException(status_code=401, detail="Could not validate credentials")
        return user_email
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")


# ---------------------------------------------------------------------------
# Trial query (no auth)
# ---------------------------------------------------------------------------

@router.post("/trial-ask")
@limiter.limit("20/minute")
async def trial_ask(request: Request):
    """Process a document query for a fingerprint-identified trial user with optional image uploads."""
    if "multipart/form-data" in request.headers.get("content-type", ""):
        form = await request.form()
        image = form.get("image")
        data = {
            'fingerprint': form.get('fingerprint'),
            'message': form.get('message', '')
        }
        if image and image.filename:
            image_path = f"/tmp/{image.filename}"
            content = await image.read()
            with open(image_path, "wb") as f:
                f.write(content)
                
            caption = get_image_caption(image_path)
            
            if data['message']:
                data['message'] = f"{data['message']}\n\nImage Description: {caption}"
            else:
                data['message'] = f"Image Description: {caption}"
            logger.info(f"📨 FINAL TRIAL MESSAGE SENT TO RAG:\n{data['message']}")
            
            os.remove(image_path)
    else:
        data = await request.json()

    response, status_code = query_service.process_trial_query(data)
    return JSONResponse(content=response, status_code=status_code)


# ---------------------------------------------------------------------------
# Authenticated query
# ---------------------------------------------------------------------------

@router.post("/ask")
async def ask(request: Request):
    """Process a document query with full chat-history context for an authenticated user."""
    image_url = None
    caption = None
    
    if "multipart/form-data" in request.headers.get("content-type", ""):
        form = await request.form()
        image = form.get("image")
        data = {
            'token': form.get('token'),
            'message': form.get('message', ''),
            'context': form.get('context', "false").lower() in ("true", "1"),
            'chatId': form.get('chatId', 'default'),
            'sessionId': form.get('sessionId'),
            'inputLanguage': int(form.get('inputLanguage', 23)),
            'outputLanguage': int(form.get('outputLanguage', 23)),
            'filenames': form.getlist('filenames'),
            'hasCsvOrXlsx': form.get('hasCsvOrXlsx', "false").lower() in ("true", "1"),
            'mode': form.get('mode', 'default'),
        }
        
        if image and image.filename:
            # Save image permanently to files directory instead of /tmp/
            BASE_USERS_DIR = "chat_images"
            session_id_for_path = data.get('sessionId', 'default')
            ext = os.path.splitext(image.filename)[1] or ".jpg"
            image_filename = f"img_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
            image_dir = os.path.join(BASE_USERS_DIR, session_id_for_path)
            os.makedirs(image_dir, exist_ok=True)
            image_save_path = os.path.join(image_dir, image_filename)
            
            # Read and write content
            content = await image.read()
            with open(image_save_path, "wb") as f:
                f.write(content)

            # Get caption from Gemma4
            caption = get_image_caption(image_save_path)

            # Build URL for frontend to fetch image
            image_url = f"/chat_images/{session_id_for_path}/{image_filename}"

            if data['message']:
                data['message'] = f"{data['message']}\n\nImage Description: {caption}"
            else:
                data['message'] = f"Image Description: {caption}"
            logger.info(f"FINAL MESSAGE SENT TO RAG:\n{data['message']}")
    else:
        data = await request.json()

    # Authenticate user robustly
    user_email = authenticate_user_robust(request, data)
    session_name = user_email
    context = data.get('context', False)
    chat_id = data.get('chatId', 'default')
    
    if context:
        session_id = data.get('sessionId')
        if not session_id:
            raise HTTPException(status_code=400, detail="sessionId is required when context=true.")
        session_name = user_email + str(session_id.lower())

    # Pre-store user message with image before full RAG execution (if image uploaded)
    if image_url:
        from app.models.chat_models import MessageRole
        # Ensure we store the user turn with its image payload
        chat_history_manager.store_user_message(
            user_session=session_name,
            chat_id=chat_id,
            role=MessageRole.USER,
            content=data['message'],
            image_caption=caption,
            image_url=image_url
        )
        # Skip standard user message storage in RAG agent because we already saved it here
        data['skip_user_message_storage'] = True

    data['image_url'] = image_url
    data['image_caption'] = caption

    response, status_code = query_service.process_authenticated_query(data, user_email, session_name, chat_id)
    return JSONResponse(content=response, status_code=status_code)


# ---------------------------------------------------------------------------
# Creative-mode SSE stream
# ---------------------------------------------------------------------------

@router.get("/ask-stream")
def ask_stream(
    request: Request,
    user_email: str = Depends(get_current_user_sse),
    session_id: str = Query(..., alias="sessionId"),
    chat_id: str = Query(default="default", alias="chatId"),
    message: str = Query(...),
    mode: str = Query(default="creative"),
    input_language: int = Query(default=23, alias="inputLanguage"),
    output_language: int = Query(default=23, alias="outputLanguage"),
    has_csv_or_xlsx: bool = Query(default=False, alias="hasCsvOrXlsx"),
    filenames: List[str] = Query(default=[]),
):
    """
    Stream a creative-mode query response via Server-Sent Events.
    Token is accepted as a query parameter because browser EventSource cannot set headers.
    """
    session_name = user_email + session_id.lower()

    data = {
        "message": message,
        "sessionId": session_id,
        "chatId": chat_id,
        "mode": mode,
        "inputLanguage": input_language,
        "outputLanguage": output_language,
        "hasCsvOrXlsx": has_csv_or_xlsx,
        "filenames": filenames,
    }

    if mode != "creative":
        response, status_code = query_service.process_authenticated_query(
            data, user_email, session_name, chat_id
        )
        return JSONResponse(content=response, status_code=status_code)

    def generate():
        try:
            user_query = query_service._extract_query_parameters(data)

            guardrail_response = query_service._guardrail.process_input(user_query["message"])
            if guardrail_response.get("status") == "blocked":
                yield f"data: {json.dumps({'type': 'error', 'content': guardrail_response})}\n\n"
                return

            user_query["message"] = guardrail_response.get("sanitized_input", user_query["message"])

            chat_context = query_service.query_agent._get_chat_context_if_needed(
                user_query["message"], session_name, {}, chat_id
            )

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
                chat_id,
            ):
                yield f"data: {json.dumps(event)}\n\n"

        except Exception as e:
            logger.error(f"SSE streaming error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Query with local offline TTS audio response
# ---------------------------------------------------------------------------

@router.post("/ask-tts")
@limiter.limit("10/minute")
def ask_tts(request: Request, body: QueryRequest, user_email: str = Depends(get_current_user)):
    """
    Process a document query and return the answer as a local multilingual Indic Parler TTS audio buffer.
    """
    data = body.model_dump()
    session_name = user_email
    chat_id = body.chatId or "default"

    if body.context:
        if not body.sessionId:
            raise HTTPException(status_code=400, detail="sessionId is required when context=true.")
        session_name = user_email + body.sessionId.lower()

    query_response, status_code = query_service.process_authenticated_query(
        data, user_email, session_name, chat_id
    )
    if status_code != 200:
        raise HTTPException(status_code=status_code, detail=query_response.get("message", "Query failed"))

    answer_text = ""
    if isinstance(query_response, dict):
        answer_text = query_response.get("answer", "")
    if not answer_text or not answer_text.strip():
        raise HTTPException(status_code=500, detail="Empty response generated.")

    output_language = body.outputLanguage or 23
    language_map = {1: "hindi", 23: "english"}
    lang_str = language_map.get(output_language, "english") if isinstance(output_language, int) else output_language
    lang_str = str(lang_str).strip().lower()

    try:
        from app.services.indic_parler_tts_service import get_indic_parler_service
        parler_service = get_indic_parler_service()
        audio_bytes = parler_service.generate_audio_bytes(answer_text, lang_str)
        
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Length": str(len(audio_bytes)),
                "Cache-Control": "no-cache",
                "X-TTS-Provider": "indic-parler",
            }
        )
    except Exception as e:
        logger.exception(f"TTS generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Local TTS generation failed: {str(e)}")


# ---------------------------------------------------------------------------
# TTS health check
# ---------------------------------------------------------------------------

@router.get("/tts-health")
def tts_health(user_email: str = Depends(get_current_user)):
    """Check whether the local Indic Parler TTS service is reachable and configured."""
    try:
        from app.services.indic_parler_tts_service import get_indic_parler_service
        parler_service = get_indic_parler_service()
        connection_ok = parler_service.test_connection()
        return {
            "status": "healthy" if connection_ok else "degraded",
            "tts_available": connection_ok,
            "default_voice": "parler-tts-indic-v1",
            "message": "Local Indic Parler TTS service is ready" if connection_ok else "Local Indic Parler TTS service has issues",
        }
    except Exception as e:
        logger.error(f"TTS health check error: {e}")
        return {
            "status": "unhealthy",
            "tts_available": False,
            "message": f"TTS service error: {str(e)}"
        }


# ---------------------------------------------------------------------------
# Direct TTS audio synthesis endpoint
# ---------------------------------------------------------------------------

@router.api_route("/tts", methods=["GET", "POST"])
async def tts_direct(request: Request):
    """
    Direct text-to-speech endpoint using local Indic Parler TTS.
    Converts given text to audio and returns the bytes.
    """
    try:
        text = None
        output_language = "english"
        
        if request.method == "POST":
            data = await request.json()
            text = data.get("text")
            output_language = data.get("outputLanguage", "english")
        else:
            text = request.query_params.get("text")
            output_language = request.query_params.get("outputLanguage", "english")

        if not text or not text.strip():
            raise HTTPException(status_code=400, detail="Text is required")

        # Normalize output language
        try:
            output_language = int(output_language)
        except (ValueError, TypeError):
            pass
        if isinstance(output_language, int):
            language_map = {1: 'hindi', 23: 'english'}
            output_language = language_map.get(output_language, 'english')
        output_language = str(output_language).strip().lower()

        logger.info(f"Generating Direct TTS | lang={output_language} | text_len={len(text)}")

        from app.services.indic_parler_tts_service import get_indic_parler_service
        parler_service = get_indic_parler_service()
        audio_bytes = parler_service.generate_audio_bytes(text, output_language)

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                'Content-Length': str(len(audio_bytes)),
                'Cache-Control': 'no-cache',
                'X-TTS-Provider': 'indic-parler',
            }
        )
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception(f'Direct TTS generation error: {e}')
        raise HTTPException(status_code=500, detail=f'Direct TTS generation failed: {e}')


# ---------------------------------------------------------------------------
# Public Demo query
# ---------------------------------------------------------------------------

@router.post("/demoAsk")
def demo_ask(body: DemoQueryRequest):
    """Public demo endpoint — answers questions about public transport."""
    response, status_code = query_service.process_demo_query(body.model_dump())
    return JSONResponse(content=response, status_code=status_code)


# ---------------------------------------------------------------------------
# Chat-context analysis
# ---------------------------------------------------------------------------

@router.post("/chat-context/analyze")
def analyze_chat_context(body: AnalyzeContextRequest, user_email: str = Depends(get_current_user)):
    """Analyse whether the given query requires chat-history context (debug/dev utility)."""
    user_session = user_email + body.sessionId.lower()
    chat_id = body.chatId or "default"

    from app.services.chat_context_service import get_chat_context_service
    context_service = get_chat_context_service()

    session_stats = chat_history_manager.get_session_stats(user_session, chat_id)
    has_history = session_stats.get("exists", False) and session_stats.get("total_messages", 0) > 0

    analysis = context_service.detect_context_need(body.query, has_history)
    return {
        "success": True,
        "analysis": analysis,
        "session_has_history": has_history,
        "session_stats": session_stats,
        "chat_id": chat_id,
    }


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

@router.post("/notes/toggle")
def toggle_note(body: ToggleNoteRequest, user_email: str = Depends(get_current_user)):
    """Toggle the saved-note flag on a specific chat message."""
    user_session = user_email + body.sessionId.lower()
    chat_id = body.chatId or "default"

    success = chat_history_manager.toggle_message_note(user_session, chat_id, body.messageId)
    if success:
        return {"success": True, "message": "Note state toggled successfully", "message_id": body.messageId}
    raise HTTPException(status_code=404, detail="Message not found or note toggle failed.")


@router.get("/notes")
def list_notes(
    session_id: str = Query(..., alias="sessionId"),
    user_email: str = Depends(get_current_user),
):
    """Return all saved notes for a session."""
    user_session = user_email + session_id.lower()
    notes = chat_history_manager.get_saved_notes(user_session)
    return {"success": True, "notes": notes, "total_notes": len(notes)}


# ---------------------------------------------------------------------------
# Chat history — read
# ---------------------------------------------------------------------------

@router.get("/chat-history")
def get_chat_history(
    session_id: str = Query(..., alias="sessionId"),
    chat_id: Optional[str] = Query(default=None, alias="chatId"),
    limit: int = Query(default=20, ge=1, le=100),
    user_email: str = Depends(get_current_user),
):
    """
    Return chat history for a specific chat.
    If chatId is omitted, returns the most recent empty chat (or creates a new one).
    """
    user_session = user_email + session_id.lower()

    if not chat_id:
        latest_empty = chat_history_manager.get_latest_empty_chat(user_session)
        if latest_empty:
            return JSONResponse(
                content={
                    "success": True,
                    "messages": [],
                    "total_messages": 0,
                    "chatId": latest_empty["chat_id"],
                    "chatName": latest_empty["chat_name"],
                    "session_exists": True,
                },
                status_code=200,
            )
        new_chat_id = str(int(time.time() * 1000))
        chat_history_manager._create_chat_name_entry(user_session, new_chat_id)
        return JSONResponse(
            content={
                "success": True,
                "messages": [],
                "total_messages": 0,
                "chatId": new_chat_id,
                "chatName": chat_history_manager._generate_default_chat_name(),
                "session_exists": False,
            },
            status_code=201,
        )

    chat_session = chat_history_manager._get_session(user_session, chat_id)
    chat_name = chat_history_manager._get_chat_name(user_session, chat_id)
    if not chat_name:
        chat_name = chat_history_manager._generate_default_chat_name()
        chat_history_manager._create_chat_name_entry(user_session, chat_id, chat_name)

    if not chat_session:
        return {"success": True, "messages": [], "total_messages": 0, "session_exists": False, "chatId": chat_id, "chatName": chat_name}

    recent = chat_session.get_recent_messages(limit)
    messages = []
    for msg in recent:
        d = msg.to_dict()
        messages.append({
            "message_id": d.get("message_id"),
            "timestamp": d.get("timestamp"),
            "role": d.get("role"),
            "content": d.get("content"),
            "query_type": d.get("query_type"),
            "save_to_note": d.get("save_to_note", False),
            "image_url": d.get("image_url", ""),
            "image_caption": d.get("image_caption", ""),
        })

    return {
        "success": True,
        "messages": messages,
        "total_messages": chat_session.total_messages,
        "session_exists": True,
        "chatId": chat_id,
        "chatName": chat_name,
    }


@router.get("/chat-history/list")
def list_chats(
    session_id: str = Query(..., alias="sessionId"),
    user_email: str = Depends(get_current_user),
):
    """List all chats in a session with their names."""
    user_session = user_email + session_id.lower()
    chats = chat_history_manager.list_chats(user_session)
    return {"success": True, "chats": chats, "total_chats": len(chats)}


@router.get("/chat-history/stats")
def get_chat_stats(
    session_id: str = Query(..., alias="sessionId"),
    chat_id: str = Query(default="default", alias="chatId"),
    user_email: str = Depends(get_current_user),
):
    """Return token and message statistics for a specific chat."""
    user_session = user_email + session_id.lower()
    stats = chat_history_manager.get_session_stats(user_session, chat_id)
    return {"success": True, "stats": stats}


# ---------------------------------------------------------------------------
# Chat history — mutation
# ---------------------------------------------------------------------------

@router.put("/chat-history/rename")
def rename_chat(body: RenameChatRequest, user_email: str = Depends(get_current_user)):
    """Rename a chat within a session."""
    new_name = body.newChatName.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="New chat name cannot be empty.")
    if len(new_name) > 100:
        raise HTTPException(status_code=400, detail="Chat name exceeds 100 characters.")

    user_session = user_email + body.sessionId.lower()
    chat_id = body.chatId or "default"
    success = chat_history_manager.update_chat_name(user_session, chat_id, new_name)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to rename chat.")
    return {"success": True, "message": "Chat renamed successfully", "chat_id": chat_id, "new_chat_name": new_name}


@router.delete("/chat-history")
def clear_chat_history(
    session_id: str = Query(..., alias="sessionId"),
    chat_id: str = Query(default="default", alias="chatId"),
    user_email: str = Depends(get_current_user),
):
    """Delete all messages in a specific chat."""
    user_session = user_email + session_id.lower()
    success = chat_history_manager.delete_session(user_session, chat_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to clear chat history.")
    return {"success": True, "message": "Chat history cleared successfully", "chat_id": chat_id}


@router.delete("/chat-history/all")
def clear_all_chats(
    session_id: str = Query(..., alias="sessionId"),
    user_email: str = Depends(get_current_user),
):
    """Delete every chat in a session."""
    user_session = user_email + session_id.lower()
    deleted_count = chat_history_manager.delete_all_chats_for_session(user_session)
    return {"success": True, "message": f"Cleared {deleted_count} chats successfully", "deleted_count": deleted_count}
