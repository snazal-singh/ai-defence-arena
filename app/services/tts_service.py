"""
Text-to-Speech service module using Vexyl-TTS (ai4bharat/indic-parler-tts).

Connects to the local Vexyl-TTS WebSocket server for true sentence-level
streaming synthesis. Preserves the same public API as the former ElevenLabs
implementation so callers in queries.py need no changes.

Audio format: WAV (the route serves audio/wav).
"""

import asyncio
import base64
import io
import json
import logging
import re
import time
import threading
import uuid
from typing import Generator, Optional

import requests
import websockets

from app.core.config import settings as Config

logger = logging.getLogger(__name__)

# ─── Language mapping ──────────────────────────────────────────────────────────
# Maps ISO 639-1/3 codes → Vexyl BCP-47 locale tags
_LANG_MAP: dict[str, str] = {
    "en":  "en-IN",
    "hi":  "hi-IN",
    "kok": "kok-IN",
    "kn":  "kn-IN",
    "doi": "doi-IN",
    "brx": "brx-IN",
    "ur":  "ur-IN",
    "ta":  "ta-IN",
    "ks":  "ks-IN",
    "as":  "as-IN",
    "bn":  "bn-IN",
    "mr":  "mr-IN",
    "sd":  "sd-IN",
    "mai": "mai-IN",
    "pa":  "pa-IN",
    "ml":  "ml-IN",
    "mni": "mni-IN",
    "te":  "te-IN",
    "sa":  "sa-IN",
    "ne":  "ne-IN",
    "sat": "sat-IN",
    "gu":  "gu-IN",
    "or":  "or-IN",
}


def _to_vexyl_lang(language: str) -> str:
    """Normalize an ISO 639-1/3 code to a Vexyl BCP-47 locale tag."""
    key = str(language).lower().strip()
    return _LANG_MAP.get(key, "en-IN")


def _ws_to_http(ws_url: str) -> str:
    """Convert ws:// → http:// for REST health/batch calls."""
    return ws_url.replace("ws://", "http://", 1).replace("wss://", "https://", 1)


# ─── Clean text ───────────────────────────────────────────────────────────────

def _clean_text_for_tts(text: str) -> str:
    """Strip markdown, citations, and symbols that degrade TTS quality."""
    if not text:
        return ""

    # Remove citations with filenames [report.pdf, Page 3-5]
    text = re.sub(
        r'\[([^,\]]+\.(?:pdf|doc|docx|txt|xls|xlsx|ppt|pptx|csv))[,\s]+Page\s*[\d\s,-]+\]',
        '', text, flags=re.IGNORECASE
    )
    # Remove numeric citations [1], [2]
    text = re.sub(r'\[\d+\]', '', text)
    # Remove remaining bracket-enclosed filenames
    text = re.sub(
        r'\[[^\]]*\.(?:pdf|doc|docx|txt|xls|xlsx|ppt|pptx|csv)[^\]]*\]',
        '', text, flags=re.IGNORECASE
    )
    # Strip markdown
    text = re.sub(r'#{1,6}\s+', '', text)          # headers
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)       # italic
    text = re.sub(r'```[\s\S]*?```', '', text)        # code blocks
    text = re.sub(r'`([^`]+)`', r'\1', text)          # inline code
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # links
    text = re.sub(r'[>]+', '', text)                  # blockquotes
    # Expand common abbreviations
    text = re.sub(r'\bDr\.', 'Doctor', text)
    text = re.sub(r'\bMr\.', 'Mister', text)
    text = re.sub(r'\bMrs\.', 'Misses', text)
    text = re.sub(r'\bMs\.', 'Miss', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# ─── Async synthesis core ─────────────────────────────────────────────────────

async def _async_generate_audio_stream(text: str, lang_code: str):
    """
    Async generator: opens a WebSocket to Vexyl-TTS, sends a streaming synthesis
    request (sentence mode), yields raw WAV bytes for each audio_chunk received.
    """
    ws_url = Config.VEXYL_TTS_URL
    request_id = f"sachet_{uuid.uuid4().hex[:12]}"

    logger.info(f"[VexylTTS] Connecting to {ws_url} for request {request_id}")

    try:
        async with websockets.connect(ws_url, open_timeout=10, close_timeout=5, max_size=16 * 1024 * 1024) as ws:
            # Wait for "ready" handshake
            ready_raw = await asyncio.wait_for(ws.recv(), timeout=10)
            ready = json.loads(ready_raw)
            if ready.get("type") != "ready":
                logger.warning(f"[VexylTTS] Unexpected first message: {ready}")

            # Send synthesis request (sentence-level streaming)
            await ws.send(json.dumps({
                "type":           "synthesize",
                "text":           text,
                "lang":           lang_code,
                "style":          "default",
                "stream":         True,
                "streaming_mode": "sentence",
                "request_id":     request_id,
            }))
            logger.debug(f"[VexylTTS] Sent synthesize request for {len(text)} chars")

            chunk_count = 0
            # Collect messages until audio_end or error
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                except asyncio.TimeoutError:
                    logger.error("[VexylTTS] Timeout waiting for audio chunk")
                    break

                msg = json.loads(raw)
                msg_type = msg.get("type")

                if msg_type == "audio_chunk":
                    audio_b64 = msg.get("audio_b64", "")
                    if audio_b64:
                        wav_bytes = base64.b64decode(audio_b64)
                        chunk_count += 1
                        logger.debug(f"[VexylTTS] Chunk {chunk_count}: {len(wav_bytes)} bytes")
                        yield wav_bytes

                elif msg_type == "audio":
                    # Full (non-streaming) response — yield the whole buffer
                    audio_b64 = msg.get("audio_b64", "")
                    if audio_b64:
                        yield base64.b64decode(audio_b64)
                    break

                elif msg_type == "audio_end":
                    logger.info(
                        f"[VexylTTS] Stream complete: {chunk_count} chunks, "
                        f"{msg.get('total_bytes', 0)} bytes total"
                    )
                    break

                elif msg_type == "error":
                    logger.error(f"[VexylTTS] Server error: {msg.get('message')}")
                    break

                else:
                    # Ignore status / info messages
                    logger.debug(f"[VexylTTS] Ignored message type: {msg_type}")

    except (websockets.exceptions.ConnectionClosed,
            websockets.exceptions.WebSocketException) as exc:
        logger.error(f"[VexylTTS] WebSocket error: {exc}")
        raise
    except Exception as exc:
        logger.error(f"[VexylTTS] Unexpected error: {exc}", exc_info=True)
        raise


def _run_async_generator_to_queue(coro_gen, queue: "asyncio.Queue", loop):
    """Run an async generator in a dedicated event loop thread, pushing items to queue."""
    async def _drain():
        try:
            async for item in coro_gen:
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except Exception as exc:
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

    loop.run_until_complete(_drain())


# ─── Service class ────────────────────────────────────────────────────────────

class TTSService:
    """Service for handling text-to-speech operations via Vexyl-TTS."""

    def __init__(self):
        """Initialize the TTS service."""
        self.tts_url = Config.VEXYL_TTS_URL
        self.http_base = _ws_to_http(self.tts_url)
        logger.info(f"[VexylTTS] TTSService initialised → {self.tts_url}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_audio_stream(self, text: str, language: str = "english") -> Generator[bytes, None, None]:
        """
        Generate WAV audio stream from text using Vexyl-TTS server.

        Args:
            text:     Text to convert to speech.
            language: Sachet language name or numeric code.

        Yields:
            WAV audio chunks as bytes.
        """
        cleaned = _clean_text_for_tts(text)
        if not cleaned:
            logger.warning("[VexylTTS] No text after cleaning; skipping synthesis")
            return

        lang_code = _to_vexyl_lang(language)
        logger.info(f"[VexylTTS] Routing query to Vexyl server | lang={lang_code} | chars={len(cleaned)}")

        # Bridge: run the async generator in a background thread with its own
        # event loop, communicate results back via a thread-safe queue.
        import queue as _queue

        stop_event = threading.Event()
        result_queue: _queue.Queue = _queue.Queue()

        def _thread_target():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                async def _drain():
                    try:
                        async for chunk in _async_generate_audio_stream(cleaned, lang_code):
                            if stop_event.is_set():
                                break
                            result_queue.put(chunk)
                    except Exception as exc:
                        result_queue.put(exc)
                    finally:
                        result_queue.put(None)  # sentinel

                loop.run_until_complete(_drain())
            except Exception as e:
                logger.error(f"[VexylTTS] Error running async event loop in thread: {e}")
            finally:
                loop.close()

        thread = threading.Thread(target=_thread_target, daemon=True)
        thread.start()

        header_sent = False

        try:
            while True:
                item = result_queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    logger.error(f"[VexylTTS] Stream error in thread: {item}")
                    break

                if isinstance(item, bytes):
                    if not header_sent:
                        if len(item) >= 44:
                            # Construct a master infinite WAV header from the first chunk's parameters
                            header = bytearray(item[:44])
                            header[4:8] = (0x7f000024).to_bytes(4, 'little')   # ChunkSize (file size - 8)
                            header[40:44] = (0x7f000000).to_bytes(4, 'little') # Subchunk2Size (data size)
                            yield bytes(header)
                            # Yield the actual PCM data of the first chunk
                            yield item[44:]
                            header_sent = True
                        else:
                            yield item
                    else:
                        # Strip the 44-byte WAV header and yield only the raw PCM bytes
                        yield item[44:]
        finally:
            stop_event.set()
            thread.join(timeout=2)

    def generate_audio_buffer(self, text: str, language: str = "english") -> Optional[bytes]:
        """
        Generate complete WAV audio buffer from text using Vexyl-TTS server.

        Args:
            text:     Text to convert to speech.
            language: Sachet language name or numeric code.

        Returns:
            Complete WAV audio as bytes, or None on failure.
        """
        cleaned = _clean_text_for_tts(text)
        if not cleaned:
            return None

        try:
            buf = io.BytesIO()
            for chunk in self.generate_audio_stream(cleaned, language):
                buf.write(chunk)
            
            data = bytearray(buf.getvalue())
            if len(data) >= 44:
                # Update the header sizes to match the actual generated file size
                data_size = len(data) - 44
                data[4:8] = (data_size + 36).to_bytes(4, 'little')
                data[40:44] = data_size.to_bytes(4, 'little')
                
            return bytes(data) if data else None
        except Exception as exc:
            logger.error(f"[VexylTTS] generate_audio_buffer error: {exc}")
            return None

    def test_connection(self) -> bool:
        """
        Test connectivity to the Vexyl-TTS server via HTTP health endpoint.

        Returns:
            True if server is reachable and healthy.
        """
        health_url = f"{self.http_base}/health"
        try:
            resp = requests.get(health_url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"[VexylTTS] Health OK: {data.get('status', 'ok')}")
                return True
            logger.warning(f"[VexylTTS] Health returned {resp.status_code}")
            return False
        except Exception as exc:
            logger.error(f"[VexylTTS] Health check failed: {exc}")
            return False

    @property
    def vexyl_url(self) -> str:
        return self.tts_url


# ─── Singleton ────────────────────────────────────────────────────────────────

_tts_service: Optional[TTSService] = None


def get_tts_service() -> TTSService:
    """Get the TTS service singleton instance."""
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service