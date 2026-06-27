"""
Translation utility — delegates to a remote IndicTrans2 inference server.

The inference server (translation_server/server.py) must be running on the
remote machine.  Configure the backend via environment variables:

    TRANSLATION_SERVER_URL   Base URL of the inference server, e.g.
                             http://translation.server.ip:8765   (no trailing slash)
    TRANSLATION_API_KEY      Bearer token, if the server was started with one.
                             Leave unset when the server runs without auth.

Usage:
    from utils.translation import translate_to_indic, translate_to_english

    translated = translate_to_indic("Hello, how are you?", "Hindi")
    english   = translate_to_english("नमस्ते", "hi")

Language codes are ISO 639-1/639-3 short codes (e.g. "hi", "en", "ml", "kok").
"""

import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ISO 639-1/3 code → display name (used for FLORES lookup and logging)
# ---------------------------------------------------------------------------
ISO_TO_NAME: dict[str, str] = {
    "en":  "English",
    "hi":  "Hindi",
    "kok": "Konkani",
    "kn":  "Kannada",
    "doi": "Dogri",
    "brx": "Bodo",
    "ur":  "Urdu",
    "ta":  "Tamil",
    "ks":  "Kashmiri",
    "as":  "Assamese",
    "bn":  "Bengali",
    "mr":  "Marathi",
    "sd":  "Sindhi",
    "mai": "Maithili",
    "pa":  "Punjabi",
    "ml":  "Malayalam",
    "mni": "Manipuri",
    "te":  "Telugu",
    "sa":  "Sanskrit",
    "ne":  "Nepali",
    "sat": "Santali",
    "gu":  "Gujarati",
    "or":  "Odia",
}

# ---------------------------------------------------------------------------
# FLORES-200 language codes — kept here so callers can still inspect them
# and so we can do a fast local check before hitting the network.
# ---------------------------------------------------------------------------
LANGUAGE_TO_FLORES: dict[str, str] = {
    "English":   "eng_Latn",
    "Hindi":     "hin_Deva",
    "Konkani":   "kok_Deva",
    "Kannada":   "kan_Knda",
    "Dogri":     "dgo_Deva",
    "Bodo":      "brx_Deva",
    "Urdu":      "urd_Arab",
    "Tamil":     "tam_Taml",
    "Kashmiri":  "kas_Arab",
    "Assamese":  "asm_Beng",
    "Bengali":   "ben_Beng",
    "Marathi":   "mar_Deva",
    "Sindhi":    "snd_Arab",
    "Maithili":  "mai_Deva",
    "Punjabi":   "pan_Guru",
    "Malayalam": "mal_Mlym",
    "Manipuri":  "mni_Beng",
    "Telugu":    "tel_Telu",
    "Sanskrit":  "san_Deva",
    "Nepali":    "npi_Deva",
    "Santali":   "sat_Olck",
    "Gujarati":  "guj_Gujr",
    "Odia":      "ory_Orya",
}

# ---------------------------------------------------------------------------
# Remote server config (read once at import time)
# ---------------------------------------------------------------------------
_SERVER_URL: Optional[str] = os.getenv("TRANSLATION_SERVER_URL", "localhost").rstrip("/") or None
_API_KEY: Optional[str] = os.getenv("TRANSLATION_API_KEY")

_REQUEST_TIMEOUT: int = int(os.getenv("TRANSLATION_REQUEST_TIMEOUT", "120"))  # seconds


def _headers() -> dict:
    if _API_KEY:
        return {"Authorization": f"Bearer {_API_KEY}"}
    return {}


def translate_to_indic(text: str, language: str) -> str:
    """
    Translate *text* (English) to the target *language* via the remote
    IndicTrans2 inference server.

    *language* accepts either a language name ("Hindi") or an ISO code ("hi").

    Returns the original text unchanged if:
    - *language* resolves to "English",
    - *language* is unsupported,
    - TRANSLATION_SERVER_URL is not set,
    - the remote call fails (logs a warning).
    """
    if not text or not text.strip():
        return text

    # Accept ISO code ("hi") or name ("Hindi")
    if language and language.lower() in ISO_TO_NAME:
        language_key = ISO_TO_NAME[language.lower()]
    else:
        language_key = language.strip().title() if language else "English"

    if language_key == "English":
        return text

    if language_key not in LANGUAGE_TO_FLORES:
        logger.warning(
            "Language '%s' is not supported by IndicTrans2; returning original text.",
            language,
        )
        return text

    if _SERVER_URL is None:
        logger.error(
            "TRANSLATION_SERVER_URL is not set. Cannot translate to '%s'. "
            "Returning original text.",
            language,
        )
        return text

    try:
        response = requests.post(
            f"{_SERVER_URL}/translate",
            json={"text": text, "language": language_key},
            headers=_headers(),
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()["translated"]

    except requests.exceptions.ConnectionError:
        logger.error(
            "Could not connect to translation server at %s. "
            "Returning original text.",
            _SERVER_URL,
        )
    except requests.exceptions.Timeout:
        logger.error(
            "Translation request to %s timed out after %ds. "
            "Returning original text.",
            _SERVER_URL,
            _REQUEST_TIMEOUT,
        )
    except Exception as exc:
        logger.error(
            "Translation to '%s' failed: %s. Returning original text.",
            language,
            exc,
            exc_info=True,
        )

    return text


def translate_to_english(text: str, lang_code: str) -> str:
    """
    Translate *text* (Indic) to English via the remote IndicTrans2 inference server.

    *lang_code* is an ISO 639-1/3 code (e.g. "hi", "ml", "kok").

    Returns the original text unchanged if:
    - *lang_code* maps to "English",
    - *lang_code* is unsupported,
    - TRANSLATION_SERVER_URL is not set,
    - the remote call fails (logs a warning).
    """
    if not text or not text.strip():
        return text

    language_name = ISO_TO_NAME.get(str(lang_code).lower(), "English")

    if language_name == "English":
        return text

    if language_name not in LANGUAGE_TO_FLORES:
        logger.warning(
            "Language '%s' (code: %s) is not supported by IndicTrans2; returning original text.",
            language_name,
            lang_code,
        )
        return text

    if _SERVER_URL is None:
        logger.error(
            "TRANSLATION_SERVER_URL is not set. Cannot translate to English from '%s'. "
            "Returning original text.",
            language_name,
        )
        return text

    try:
        response = requests.post(
            f"{_SERVER_URL}/translate-to-english",
            json={"text": text, "language": language_name},
            headers=_headers(),
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()["translated"]

    except requests.exceptions.ConnectionError:
        logger.error(
            "Could not connect to translation server at %s. "
            "Returning original text.",
            _SERVER_URL,
        )
    except requests.exceptions.Timeout:
        logger.error(
            "Translation to English request to %s timed out after %ds. "
            "Returning original text.",
            _SERVER_URL,
            _REQUEST_TIMEOUT,
        )
    except Exception as exc:
        logger.error(
            "Translation to English from '%s' failed: %s. Returning original text.",
            language_name,
            exc,
            exc_info=True,
        )

    return text


def _split_into_sentences(text: str) -> list[str]:
    """Kept for backwards compatibility — no longer used by this module."""
    import re
    parts = re.split(r'(?<=[.!?])\s+|(?<=[.!?]["\'])\s+', text.strip())
    sentences = [p.strip() for p in parts if p.strip()]
    return sentences if sentences else [text.strip()]
