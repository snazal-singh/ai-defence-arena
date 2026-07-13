import json
import logging
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.api.deps import get_current_user, get_current_user_sse
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
from app.services.tts_service import get_tts_service
from app.services.stt_service import get_stt_service

class SynthesizeRequest(BaseModel):
    text: str
    language: str = "en"

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Queries"])

query_service = get_query_service()
chat_history_manager = get_chat_history_manager()


# ---------------------------------------------------------------------------
# Trial query (no auth)
# ---------------------------------------------------------------------------

@router.post("/trial-ask")
@limiter.limit("20/minute")
def trial_ask(request: Request, body: TrialQueryRequest):
    """Process a document query for a fingerprint-identified trial user."""
    response, status_code = query_service.process_trial_query(body.model_dump())
    return JSONResponse(content=response, status_code=status_code)


# ---------------------------------------------------------------------------
# Authenticated query
# ---------------------------------------------------------------------------

@router.post("/ask")
async def ask(request: Request, user_email: str = Depends(get_current_user)):
    """Process a document query with full chat-history context for an authenticated user."""
    content_type = request.headers.get("content-type", "")
    
    image_id = None
    caption = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        logger.debug(f"Form keys: {list(form.keys())} | Image object: {form.get('image')} | Image type: {type(form.get('image'))}")
        message = form.get("message", "")
        chat_id = form.get("chatId", "default")
        session_id = form.get("sessionId")
        context = form.get("context", "")
        
        input_language = str(form.get("inputLanguage", "en"))
        output_language = str(form.get("outputLanguage", "en"))
            
        has_csv_or_xlsx = form.get("hasCsvOrXlsx", "false").lower() == "true"
        mode = form.get("mode", "default")
        
        # form.getlist returns a list of strings
        filenames = form.getlist("filenames")
        
        # Process image file
        image = form.get("image")
        logger.debug(f"Checking image: image={bool(image)}, type={type(image).__name__}, filename={getattr(image, 'filename', None)}")
        if image and (type(image).__name__ == "UploadFile" or hasattr(image, "filename")) and getattr(image, "filename", None):
            import base64, os
            ext = (os.path.splitext(image.filename)[1] or ".jpg").lstrip(".")
            mime = f"image/{ext}" if ext else "image/jpeg"

            image_bytes = await image.read()
            if image_bytes:
                from app.services.vision_service import get_vision_service
                vision_service = get_vision_service()
                try:
                    caption = vision_service.get_image_caption_from_bytes(image_bytes, mime)
                    if message:
                        message = f"{message}\n\nImage Description: {caption}"
                    else:
                        message = f"Image Description: {caption}"
                    logger.info(f"Generated caption for uploaded image: {caption}")
                except Exception as e:
                    logger.error(f"Error calling vision service for caption: {e}")

                # Store image in MongoDB
                data_uri = f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
                user_session_for_img = user_email + (session_id or "").lower()
                image_id = chat_history_manager.save_image(user_session_for_img, chat_id, data_uri)
                logger.info(f"Stored image in MongoDB with id: {image_id}")
            
        data = {
            "message": message,
            "chatId": chat_id,
            "sessionId": session_id,
            "context": context,
            "inputLanguage": input_language,
            "outputLanguage": output_language,
            "hasCsvOrXlsx": has_csv_or_xlsx,
            "mode": mode,
            "filenames": filenames,
        }
    else:
        # Standard JSON body
        body_json = await request.json()
        
        # Validate body_json against QueryRequest model attributes
        body = QueryRequest(**body_json)
        data = body.model_dump()
        chat_id = body.chatId or "default"
        session_id = body.sessionId
        context = body.context

    session_name = user_email
    if context:
        if not session_id:
            raise HTTPException(status_code=400, detail="sessionId is required when context=true.")
        session_name = user_email + session_id.lower()

    data['image_id'] = image_id
    data['image_caption'] = caption
    data['skip_user_message_storage'] = False

    response, status_code = query_service.process_authenticated_query(data, user_email, session_name, chat_id)

    if image_id and isinstance(response, dict):
        response["image_id"] = image_id
        
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
    input_language: str = Query(default="en", alias="inputLanguage"),
    output_language: str = Query(default="en", alias="outputLanguage"),
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
# Query with TTS audio streaming
# ---------------------------------------------------------------------------

@router.post("/ask-tts")
@limiter.limit("10/minute")
def ask_tts(request: Request, body: QueryRequest, user_email: str = Depends(get_current_user)):
    """
    Process a document query and stream the answer as an audio/mpeg response via TTS.
    The query is resolved synchronously first; audio is then streamed chunk by chunk.
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

    iso_code = str(body.outputLanguage or "en")

    tts_service = get_tts_service()

    def generate_audio():
        try:
            for chunk in tts_service.generate_audio_stream(answer_text, iso_code):
                yield chunk
        except Exception as e:
            logger.error(f"TTS streaming error: {e}")

    return StreamingResponse(
        generate_audio(),
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# TTS synthesis (text → WAV) — used by the UI's per-sentence play button
# ---------------------------------------------------------------------------

@router.post("/synthesize")
@limiter.limit("30/minute")
def synthesize_text(request: Request, body: SynthesizeRequest, user_email: str = Depends(get_current_user)):
    """Convert text to WAV audio via Vexyl-TTS. Returns a streaming WAV response."""
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    iso_code = str(body.language or "en")
    tts = get_tts_service()

    def generate_audio():
        try:
            for chunk in tts.generate_audio_stream(text, iso_code):
                yield chunk
        except Exception as e:
            logger.error(f"TTS synthesis error: {e}")

    return StreamingResponse(
        generate_audio(),
        media_type="audio/wav",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# TTS health check
# ---------------------------------------------------------------------------

@router.get("/tts-health")
def tts_health(user_email: str = Depends(get_current_user)):
    """Check whether the Vexyl-TTS service is reachable."""
    tts_service = get_tts_service()
    ok = tts_service.test_connection()
    return {
        "status": "healthy" if ok else "degraded",
        "tts_available": ok,
        "vexyl_url": tts_service.vexyl_url,
        "message": "Vexyl-TTS is ready" if ok else "Vexyl-TTS is not reachable",
    }


# ---------------------------------------------------------------------------
# STT endpoints (Vexyl-STT)
# ---------------------------------------------------------------------------

@router.post("/stt-transcribe")
@limiter.limit("20/minute")
def stt_transcribe(
    request: Request,
    audio: UploadFile = File(...),
    language: str = Query(default="auto"),
    user_email: str = Depends(get_current_user),
):
    """Transcribe an uploaded audio file via Vexyl-STT."""
    audio_bytes = audio.file.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Audio file is empty.")

    stt_service = get_stt_service()
    try:
        result = stt_service.transcribe_audio_bytes(
            audio_bytes=audio_bytes,
            language=language,
            filename=audio.filename or "audio.wav",
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Transcription timed out.")
    except Exception as e:
        logger.exception(f"STT unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Transcription failed.")

    return result


@router.get("/stt-health")
def stt_health(user_email: str = Depends(get_current_user)):
    """Check whether the Vexyl-STT service is reachable."""
    stt_service = get_stt_service()
    ok = stt_service.test_connection()
    return {
        "status": "healthy" if ok else "degraded",
        "stt_available": ok,
        "vexyl_url": stt_service.stt_url,
        "message": "Vexyl-STT is ready" if ok else "Vexyl-STT is not reachable",
    }


# ---------------------------------------------------------------------------
# Demo query (public, no auth)
# ---------------------------------------------------------------------------

@router.post("/demo")
@limiter.limit("10/minute")
def demo(request: Request, body: DemoQueryRequest):
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
        metadata = d.get("metadata") or {}
        image_id = metadata.get("image_id")
        image_data = chat_history_manager.get_image(image_id) if image_id else None
        messages.append({
            "message_id": d.get("message_id"),
            "timestamp": d.get("timestamp"),
            "role": d.get("role"),
            "content": d.get("content"),
            "query_type": d.get("query_type"),
            "save_to_note": d.get("save_to_note", False),
            "image": image_data,
            "image_caption": metadata.get("image_caption"),
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
