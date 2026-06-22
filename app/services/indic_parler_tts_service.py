"""
Indic Parler TTS Service
========================
Uses ai4bharat/indic-parler-tts (880M params, Apache-2.0) for local,
offline, multilingual text-to-speech supporting 21 Indian languages + English.

Pipeline:
  text (in target language) + voice description prompt
        → ParlerTTSForConditionalGeneration.generate()
        → numpy WAV array
        → MP3 bytes (via soundfile + pydub)

For now: works for English.
Later:   feed translated text (Tamil/Hindi/etc.) → native language audio.

Device priority: mps (Apple Silicon) → cuda → cpu
"""

import io
import logging
import re
import threading
from typing import Optional

import numpy as np
import torch

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Voice description prompts per language.
# These control the speaker style/gender/pace/quality for Parler TTS.
# Named speakers (Divya, Rohit, etc.) are baked into the model training data.
#
# For languages without a known named speaker we use a generic description.
# Later: swap text with translated text → native language audio automatically.
# ---------------------------------------------------------------------------
LANGUAGE_DESCRIPTIONS: dict[str, str] = {
    "english":   "Thoma speaks at a moderate pace, very clear audio with no background noise.",
    "hindi":     "Divya speaks at a moderate pace, very clear audio with almost no background noise.",
    "tamil":     "A female speaker delivers clear speech at a moderate pace, very close recording with no background noise.",
    "telugu":    "A female speaker delivers clear speech at a moderate pace, very close recording with no background noise.",
    "bengali":   "Aditi speaks at a moderate pace, very clear audio with no background noise.",
    "marathi":   "Sunita speaks at a moderate pace, very clear audio with no background noise.",
    "gujarati":  "Neha speaks at a moderate pace, very clear audio with no background noise.",
    "kannada":   "Anu speaks at a moderate pace, very clear audio with no background noise.",
    "malayalam": "A female speaker delivers clear speech at a moderate pace, close recording with no background noise.",
    "punjabi":   "A female speaker delivers clear speech at a moderate pace, close recording with no background noise.",
    "odia":      "A female speaker delivers clear speech at a moderate pace, close recording with no background noise.",
    "assamese":  "Aditi speaks at a moderate pace, very clear audio with no background noise.",
    "urdu":      "A female speaker delivers clear speech at a moderate pace, close recording with no background noise.",
    "nepali":    "A female speaker delivers clear speech at a moderate pace, close recording with no background noise.",
    "sanskrit":  "A female speaker delivers clear speech at a moderate pace, close recording with no background noise.",
    "sindhi":    "A female speaker delivers clear speech at a moderate pace, close recording with no background noise.",
    "maithili":  "A female speaker delivers clear speech at a moderate pace, close recording with no background noise.",
    "manipuri":  "A female speaker delivers clear speech at a moderate pace, close recording with no background noise.",
    "bodo":      "Maya speaks at a moderate pace, very clear audio with no background noise.",
    "dogri":     "Leela speaks at a moderate pace, very clear audio with no background noise.",
    "kashmiri":  "Shabnam speaks at a moderate pace, very clear audio with no background noise.",
    "santali":   "A female speaker delivers clear speech at a moderate pace, close recording with no background noise.",
    "konkani":   "Sunita speaks at a moderate pace, very clear audio with no background noise.",
}

DEFAULT_DESCRIPTION = "A speaker delivers clear speech at a moderate pace, very close recording with no background noise."

MODEL_NAME = "ai4bharat/indic-parler-tts"


def _select_device() -> str:
    """Pick the best available device: mps > cuda > cpu."""
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        # MPS is experimental for Parler — we attempt it but fall back in service init
        return "mps"
    return "cpu"


class IndicParlerTTSService:
    """
    Singleton service for Indic Parler TTS inference.

    Model is lazy-loaded on the first call to generate_audio_bytes() to avoid
    slow startup times when the backend boots.
    """

    def __init__(self):
        self._model = None
        self._tokenizer = None
        self._device: Optional[str] = None
        self._model_loaded = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_model(self):
        """Lazy-load the Parler TTS model + tokenizer. Called once."""
        if self._model_loaded:
            return

        with self._lock:
            # Check again to avoid double loading
            if self._model_loaded:
                return

            try:
                from parler_tts import ParlerTTSForConditionalGeneration
                from transformers import AutoTokenizer
            except ImportError as exc:
                raise RuntimeError(
                    "parler-tts is not installed. Run:\n"
                    "  pip install git+https://github.com/huggingface/parler-tts.git"
                ) from exc

            device = _select_device()
            logger.info(f"Loading Indic Parler TTS model '{MODEL_NAME}' on device={device} ...")

            try:
                logger.info(f"Attempting to load Parler TTS with torch.bfloat16 on {device}...")
                model = ParlerTTSForConditionalGeneration.from_pretrained(
                    MODEL_NAME,
                    torch_dtype=torch.bfloat16
                )
                model = model.to(device)
                model.eval()
            except Exception as e:
                logger.warning(
                    f"Failed to load model on {device} with bfloat16: {e}. "
                    f"Falling back to default float32 loading."
                )
                try:
                    model = ParlerTTSForConditionalGeneration.from_pretrained(MODEL_NAME)
                    model = model.to(device)
                    model.eval()
                except Exception as inner_e:
                    if device != "cpu":
                        logger.warning(
                            f"Failed to load float32 model on {device}: {inner_e}. Falling back to CPU."
                        )
                        device = "cpu"
                        model = ParlerTTSForConditionalGeneration.from_pretrained(MODEL_NAME)
                        model = model.to("cpu")
                        model.eval()
                    else:
                        raise

            tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

            self._model = model
            self._tokenizer = tokenizer
            self._device = device
            self._model_loaded = True
            logger.info(f"Indic Parler TTS model loaded successfully on device={device}.")

    # ------------------------------------------------------------------
    # Text cleaning (same approach as ElevenLabs service)
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_text(text: str) -> str:
        """Strip markdown, citations and excessive whitespace before TTS."""
        if not text:
            return ""
        # Remove PDF-style citations [filename.pdf, Page X]
        text = re.sub(
            r'\[([^,\]]+\.(?:pdf|doc|docx|txt|xls|xlsx|ppt|pptx|csv))[,\s]+Page\s*[\d\s,-]+\]',
            '', text, flags=re.IGNORECASE
        )
        text = re.sub(r'\[\d+\]', '', text)
        text = re.sub(
            r'\[[^\]]*\.(?:pdf|doc|docx|txt|xls|xlsx|ppt|pptx|csv)[^\]]*\]',
            '', text, flags=re.IGNORECASE
        )
        # Markdown
        text = re.sub(r'#{1,6}\s+', '', text)
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        text = re.sub(r'```[\s\S]*?```', '', text)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        # Special chars
        text = re.sub(r'[?>]+', '', text)
        # Abbreviations
        text = re.sub(r'\bDr\.', 'Doctor', text)
        text = re.sub(r'\bMr\.', 'Mister', text)
        text = re.sub(r'\bMrs\.', 'Misses', text)
        text = re.sub(r'\bMs\.', 'Miss', text)
        # Whitespace
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    # ------------------------------------------------------------------
    # WAV → MP3 conversion
    # ------------------------------------------------------------------

    @staticmethod
    def _wav_array_to_mp3_bytes(audio_array: np.ndarray, sample_rate: int) -> bytes:
        """
        Convert a numpy float32 WAV array → MP3 bytes using pydub.
        Falls back to raw WAV bytes if pydub is unavailable.
        """
        import soundfile as sf

        # Write WAV to in-memory buffer
        wav_buffer = io.BytesIO()
        sf.write(wav_buffer, audio_array, sample_rate, format="WAV", subtype="PCM_16")
        wav_buffer.seek(0)

        try:
            from pydub import AudioSegment
            segment = AudioSegment.from_wav(wav_buffer)
            mp3_buffer = io.BytesIO()
            segment.export(mp3_buffer, format="mp3", bitrate="128k")
            return mp3_buffer.getvalue()
        except Exception as e:
            logger.warning(f"pydub not available or failed ({e}). Returning WAV bytes.")
            wav_buffer.seek(0)
            return wav_buffer.read()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_audio_bytes(self, text: str, output_language: str = "english") -> bytes:
        """
        Generate audio for the given text and output language.

        Args:
            text:            The text to speak.
                             For now: English LLM responses.
                             Later: pass pre-translated text in target language.
            output_language: Output language label (e.g. 'english', 'hindi', 'tamil').

        Returns:
            MP3 bytes (or WAV bytes as fallback) ready to send as audio/mpeg.

        Raises:
            RuntimeError: If model loading fails.
        """
        self._load_model()

        # Normalize language key
        lang_key = output_language.strip().lower()

        # Clean text
        clean = self._clean_text(text)
        if not clean:
            logger.warning("No text to synthesize after cleaning.")
            return b""

        # Get voice description
        description = LANGUAGE_DESCRIPTIONS.get(lang_key, DEFAULT_DESCRIPTION)
        logger.info(
            f"Generating Indic Parler TTS | lang={lang_key} | "
            f"text_len={len(clean)} | device={self._device}"
        )

        # Tokenize
        tokenizer = self._tokenizer
        model = self._model

        input_ids = tokenizer(
            description, return_tensors="pt"
        ).input_ids.to(self._device)

        prompt_input_ids = tokenizer(
            clean, return_tensors="pt"
        ).input_ids.to(self._device)

        # Generate audio
        with self._lock:
            with torch.no_grad():
                generation = model.generate(
                    input_ids=input_ids,
                    prompt_input_ids=prompt_input_ids,
                )

        # Move to CPU and extract numpy array
        audio_array = generation.cpu().to(torch.float32).numpy().squeeze()
        sample_rate = model.config.sampling_rate

        logger.info(
            f"Indic Parler TTS generation done | "
            f"audio_duration={len(audio_array)/sample_rate:.1f}s | sr={sample_rate}"
        )

        return self._wav_array_to_mp3_bytes(audio_array, sample_rate)

    def is_model_loaded(self) -> bool:
        return self._model_loaded

    def health_check(self) -> dict:
        return {
            "model": MODEL_NAME,
            "loaded": self._model_loaded,
            "device": self._device,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_indic_parler_service: Optional[IndicParlerTTSService] = None


def get_indic_parler_service() -> IndicParlerTTSService:
    """Return the global IndicParlerTTSService singleton."""
    global _indic_parler_service
    if _indic_parler_service is None:
        _indic_parler_service = IndicParlerTTSService()
    return _indic_parler_service
