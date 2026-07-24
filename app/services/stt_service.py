"""
Speech-to-Text service module using Vexyl-STT (ai4bharat/indic-conformer).

Provides two modes:
  - Batch transcription:  Send an audio file via HTTP POST, poll for result.
  - Streaming transcription: Open a WebSocket, stream 16kHz PCM chunks,
    receive real-time partial + final transcripts.

The Vexyl-STT server runs at ws://127.0.0.1:8091 (configured via VEXYL_STT_URL).
"""

import asyncio
import io
import json
import logging
import time
import threading
import uuid
from typing import Generator, Iterator, Optional

import requests
import websockets

from app.core.config import settings as Config
from utils.language_codes import ISO_TO_BCP47

logger = logging.getLogger(__name__)


def _to_vexyl_lang(language) -> str:
    """Normalize an ISO 639-1 code or language name to a Vexyl BCP-47 locale tag."""
    return ISO_TO_BCP47.get(str(language).lower().strip(), "auto")


def _ws_to_http(ws_url: str) -> str:
    """Convert ws:// → http:// for REST calls."""
    return ws_url.replace("ws://", "http://", 1).replace("wss://", "https://", 1)


# ─── Service class ────────────────────────────────────────────────────────────

class STTService:
    """
    Service for speech-to-text operations via Vexyl-STT.

    Batch mode:   sends a complete audio file, returns the final transcript.
    Stream mode:  iterates over 16kHz PCM chunks, yields transcript strings
                  as Vexyl-STT emits utterances.
    """

    def __init__(self):
        self.stt_url  = Config.VEXYL_STT_URL
        self.http_base = _ws_to_http(self.stt_url)
        logger.info(f"[VexylSTT] STTService initialised → {self.stt_url}")

    # ------------------------------------------------------------------
    # Batch transcription (HTTP)
    # ------------------------------------------------------------------

    def transcribe_audio_bytes(
        self,
        audio_bytes: bytes,
        language: str = "auto",
        filename: str = "audio.wav",
        poll_interval: float = 0.5,
        timeout: float = 120.0,
    ) -> dict:
        """
        Transcribe a complete audio file via the Vexyl-STT batch HTTP API.

        The audio is submitted as a multipart upload; the method polls the
        job-status endpoint until the transcription is done.

        Args:
            audio_bytes:   Raw bytes of the audio file (WAV/MP3/OGG/FLAC).
            language:      Sachet language name, numeric code, or 'auto'.
            filename:      Original filename (used for content-type sniffing).
            poll_interval: Seconds between poll requests.
            timeout:       Maximum seconds to wait before giving up.

        Returns:
            dict with keys: transcript, language, latency_ms, job_id
        """
        lang_code = _to_vexyl_lang(language)
        submit_url = f"{self.http_base}/batch/transcribe"
        logger.info(f"[VexylSTT] Submitting batch job | lang={lang_code} | size={len(audio_bytes)}")

        # Determine MIME type from extension
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "wav"
        mime_map = {
            "wav": "audio/wav",
            "mp3": "audio/mpeg",
            "ogg": "audio/ogg",
            "flac": "audio/flac",
            "m4a": "audio/mp4",
            "webm": "audio/webm",
        }
        mime_type = mime_map.get(ext, "audio/wav")

        try:
            resp = requests.post(
                submit_url,
                files={"file": (filename, io.BytesIO(audio_bytes), mime_type)},
                data={"language_code": lang_code},
                timeout=30,
            )
        except requests.RequestException as exc:
            logger.error(f"[VexylSTT] Batch submit failed: {exc}")
            raise RuntimeError(f"Failed to submit audio to Vexyl-STT: {exc}") from exc

        if resp.status_code not in (200, 201, 202):
            logger.error(f"[VexylSTT] Batch submit HTTP {resp.status_code}: {resp.text[:200]}")
            raise RuntimeError(f"Vexyl-STT submit error {resp.status_code}: {resp.text[:200]}")

        job_data = resp.json()
        job_id   = job_data.get("job_id")
        if not job_id:
            # Synchronous response — transcript returned immediately
            transcript = job_data.get("transcript", "")
            logger.info(f"[VexylSTT] Synchronous result: '{transcript}'")
            return {
                "transcript": transcript,
                "language": job_data.get("language", lang_code),
                "latency_ms": job_data.get("latency_ms", 0),
                "job_id": None,
            }

        logger.info(f"[VexylSTT] Job queued: {job_id}, polling...")

        # Poll until complete
        poll_url = f"{self.http_base}/batch/status/{job_id}"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            try:
                poll_resp = requests.get(poll_url, timeout=10)
            except requests.RequestException as exc:
                logger.warning(f"[VexylSTT] Poll error: {exc}")
                continue

            if poll_resp.status_code != 200:
                logger.warning(f"[VexylSTT] Poll HTTP {poll_resp.status_code}")
                continue

            status_data = poll_resp.json()
            status = status_data.get("status")

            if status == "completed":
                transcript = status_data.get("transcript", "")
                logger.info(f"[VexylSTT] Job {job_id} done: '{transcript}'")
                return {
                    "transcript":  transcript,
                    "language":    status_data.get("language", lang_code),
                    "latency_ms":  status_data.get("latency_ms", 0),
                    "job_id":      job_id,
                }
            elif status == "failed":
                err = status_data.get("error_message", status_data.get("error", "Unknown transcription error"))
                logger.error(f"[VexylSTT] Job {job_id} failed: {err}")
                raise RuntimeError(f"Transcription failed: {err}")

            # queued / processing — keep polling
            logger.debug(f"[VexylSTT] Job {job_id} status: {status}")

        raise TimeoutError(f"Transcription job {job_id} did not complete within {timeout}s")

    # ------------------------------------------------------------------
    # Streaming transcription (WebSocket, sync generator)
    # ------------------------------------------------------------------

    def stream_transcription(
        self,
        pcm_chunks: Iterator[bytes],
        language: str = "auto",
        session_id: Optional[str] = None,
        default_lang: str = "hi-IN",
    ) -> Generator[dict, None, None]:
        """
        Stream 16kHz 16-bit mono PCM audio chunks to Vexyl-STT; yield
        transcript dicts as utterances are finalized.

        Args:
            pcm_chunks:   Iterator yielding raw PCM bytes (16kHz, 16-bit, mono).
            language:     Language code or 'auto' for automatic detection.
            session_id:   Optional session identifier (auto-generated if None).
            default_lang: Fallback language for auto-detection.

        Yields:
            dicts with keys: text, lang, latency_ms, duration
        """
        lang_code  = _to_vexyl_lang(language)
        session_id = session_id or f"sachet_{uuid.uuid4().hex[:8]}"
        import queue as _queue

        result_queue: _queue.Queue = _queue.Queue()

        def _thread_target():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    _async_stream_stt(
                        pcm_chunks, lang_code, session_id, default_lang, result_queue, loop
                    )
                )
            finally:
                loop.close()

        thread = threading.Thread(target=_thread_target, daemon=True)
        thread.start()

        while True:
            item = result_queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                logger.error(f"[VexylSTT] Stream error: {item}")
                break
            yield item

        thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        """Test connectivity to the Vexyl-STT HTTP health endpoint."""
        health_url = f"{self.http_base}/health"
        try:
            resp = requests.get(health_url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                logger.info(f"[VexylSTT] Health OK: {data.get('status', 'ok')}")
                return True
            logger.warning(f"[VexylSTT] Health returned {resp.status_code}")
            return False
        except Exception as exc:
            logger.error(f"[VexylSTT] Health check failed: {exc}")
            return False


# ─── Async WebSocket streaming helper ─────────────────────────────────────────

async def _async_stream_stt(
    pcm_chunks,
    lang_code: str,
    session_id: str,
    default_lang: str,
    result_queue,
    loop,
):
    """
    Async coroutine: drives the Vexyl-STT WebSocket streaming session.
    Sends PCM chunks as binary frames; receives transcript events and
    puts them on result_queue. Signals done with None sentinel.
    """
    ws_url = Config.VEXYL_STT_URL

    def _put(item):
        loop.call_soon_threadsafe(result_queue.put_nowait, item)

    try:
        async with websockets.connect(ws_url, open_timeout=10, close_timeout=5) as ws:
            # 1. Wait for ready message
            ready_raw = await asyncio.wait_for(ws.recv(), timeout=10)
            ready = json.loads(ready_raw)
            if ready.get("type") != "ready":
                logger.warning(f"[VexylSTT] Unexpected handshake: {ready}")

            # 2. Send start message
            await ws.send(json.dumps({
                "type":         "start",
                "lang":         lang_code,
                "session_id":   session_id,
                "default_lang": default_lang,
            }))

            # Wait for "started" ack
            started_raw = await asyncio.wait_for(ws.recv(), timeout=10)
            started = json.loads(started_raw)
            logger.info(f"[VexylSTT] Session started: {started}")

            # 3. Send audio chunks while collecting transcripts concurrently
            async def _send_audio():
                for chunk in pcm_chunks:
                    await ws.send(chunk)
                # Signal end of audio
                await ws.send(json.dumps({"type": "stop"}))

            async def _recv_transcripts():
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    except asyncio.TimeoutError:
                        logger.warning("[VexylSTT] Receive timeout")
                        break
                    msg = json.loads(raw)
                    msg_type = msg.get("type")
                    if msg_type == "final":
                        transcript = msg.get("text", "").strip()
                        if transcript:
                            _put({
                                "text":       transcript,
                                "lang":       msg.get("lang", lang_code),
                                "latency_ms": msg.get("latency_ms", 0),
                                "duration":   msg.get("duration", 0),
                            })
                    elif msg_type == "stopped":
                        break
                    elif msg_type == "error":
                        logger.error(f"[VexylSTT] Server error: {msg.get('message')}")
                        break

            await asyncio.gather(_send_audio(), _recv_transcripts())

    except (websockets.exceptions.ConnectionClosed,
            websockets.exceptions.WebSocketException) as exc:
        _put(exc)
    except Exception as exc:
        logger.error(f"[VexylSTT] Unexpected error: {exc}", exc_info=True)
        _put(exc)
    finally:
        _put(None)  # sentinel


# ─── Singleton ────────────────────────────────────────────────────────────────

_stt_service: Optional[STTService] = None


def get_stt_service() -> STTService:
    """Get the STT service singleton instance."""
    global _stt_service
    if _stt_service is None:
        _stt_service = STTService()
    return _stt_service
