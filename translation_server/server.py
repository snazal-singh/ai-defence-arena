"""
IndicTrans2 Translation Inference Server
========================================
Runs the ai4bharat/indictrans2-en-indic-1B model and exposes a simple HTTP API.
Run this on the remote/GPU machine, then point the backend at it via
TRANSLATION_SERVER_URL.

Start:
    uvicorn server:app --host 0.0.0.0 --port 8765

Environment variables:
    INDICTRANS2_MODEL_DIR   Local directory to cache the model (default: ./models)
    TRANSLATION_API_KEY     Optional bearer token clients must send (leave unset to
                            disable auth — only do this on a trusted network)
"""

import logging
import os
import re
import sys
import types
from contextlib import asynccontextmanager
from typing import Optional

import torch

# ---------------------------------------------------------------------------
# Compatibility shim for transformers >= 4.40
# ai4bharat/indictrans2 configuration_indictrans.py references
# OnnxSeq2SeqConfigWithPast which was removed in transformers 4.40.
# The model file does a silent try/except around the import then still uses
# the name at class-definition time, causing a NameError on fresh downloads.
# Injecting a stub into sys.modules before from_pretrained is called fixes it.
# ---------------------------------------------------------------------------
def _patch_onnx_compat() -> None:
    class _OnnxSeq2SeqConfigWithPast:
        """Stub to satisfy IndicTrans2's configuration_indictrans.py on transformers>=4.40."""

    for mod_name in ("transformers.onnx", "transformers.onnx.config", "transformers.onnx.features"):
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            sys.modules[mod_name] = stub
        sys.modules[mod_name].OnnxSeq2SeqConfigWithPast = _OnnxSeq2SeqConfigWithPast

_patch_onnx_compat()
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger("translation_server")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MODEL_DIR: str = os.getenv("INDICTRANS2_MODEL_DIR", "./models/indictrans2-en-indic-1B")
HF_MODEL_ID: str = "ai4bharat/indictrans2-en-indic-1B"
API_KEY: Optional[str] = os.getenv("TRANSLATION_API_KEY")

LANGUAGE_TO_FLORES: dict[str, str] = {
    "English":   "eng_Latn",
    "Hindi":     "hin_Deva",
    "Gom":       "gom_Deva",
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
# Model globals (loaded once at startup)
# ---------------------------------------------------------------------------
_model = None
_tokenizer = None
_processor = None
_device: str = "cpu"


def _load_model() -> None:
    global _model, _tokenizer, _processor, _device

    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    from IndicTransToolkit.processor import IndicProcessor

    _device = "cuda" if torch.cuda.is_available() else "cpu"
    logger.info("Loading model on device=%s, cache=%s", _device, MODEL_DIR)

    os.makedirs(MODEL_DIR, exist_ok=True)

    _tokenizer = AutoTokenizer.from_pretrained(
        HF_MODEL_ID, trust_remote_code=True, cache_dir=MODEL_DIR
    )

    torch_dtype = torch.float16 if _device == "cuda" else torch.float32
    _model = AutoModelForSeq2SeqLM.from_pretrained(
        HF_MODEL_ID,
        trust_remote_code=True,
        torch_dtype=torch_dtype,
        cache_dir=MODEL_DIR,
    ).to(_device)
    _model.eval()

    _processor = IndicProcessor(inference=True)
    logger.info("Model loaded successfully.")


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_model()
    yield


app = FastAPI(title="IndicTrans2 Translation Server", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Auth (optional)
# ---------------------------------------------------------------------------
_bearer = HTTPBearer(auto_error=False)


def verify_key(credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)):
    if API_KEY is None:
        return  # auth disabled
    if credentials is None or credentials.credentials != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class TranslateRequest(BaseModel):
    text: str
    language: str        # e.g. "Hindi"
    batch_size: int = 4


class TranslateResponse(BaseModel):
    translated: str
    language: str
    flores_code: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _split_into_sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+|(?<=[.!?]["\'])\s+', text.strip())
    sentences = [p.strip() for p in parts if p.strip()]
    return sentences if sentences else [text.strip()]


def _run_translation(text: str, tgt_flores: str, batch_size: int) -> str:
    src_lang = "eng_Latn"
    sentences = _split_into_sentences(text)
    translated_parts: list[str] = []

    for i in range(0, len(sentences), batch_size):
        batch = sentences[i : i + batch_size]

        preprocessed = _processor.preprocess_batch(
            batch, src_lang=src_lang, tgt_lang=tgt_flores
        )

        inputs = _tokenizer(
            preprocessed,
            truncation=True,
            padding="longest",
            return_tensors="pt",
            return_attention_mask=True,
        ).to(_device)

        with torch.no_grad():
            generated_tokens = _model.generate(
                **inputs,
                use_cache=True,
                min_length=0,
                max_length=512,
                num_beams=5,
                num_return_sequences=1,
            )

        decoded = _tokenizer.batch_decode(
            generated_tokens,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=True,
        )

        translated_parts.extend(_processor.postprocess_batch(decoded, lang=tgt_flores))

    return " ".join(translated_parts)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok", "device": _device, "model": HF_MODEL_ID}


@app.post("/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest, _=Depends(verify_key)):
    if not req.text or not req.text.strip():
        return TranslateResponse(translated=req.text, language=req.language, flores_code="")

    language_key = req.language.strip().title()

    if language_key == "English":
        return TranslateResponse(
            translated=req.text, language=req.language, flores_code="eng_Latn"
        )

    tgt_flores = LANGUAGE_TO_FLORES.get(language_key)
    if tgt_flores is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported language: '{req.language}'. "
                   f"Supported: {sorted(LANGUAGE_TO_FLORES.keys())}",
        )

    try:
        translated = _run_translation(req.text, tgt_flores, req.batch_size)
    except Exception as exc:
        logger.error("Translation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Translation error: {exc}",
        )

    return TranslateResponse(translated=translated, language=req.language, flores_code=tgt_flores)
