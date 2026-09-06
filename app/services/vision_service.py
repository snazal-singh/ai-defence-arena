import logging
import base64
import requests
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

class VisionService:
    """Service for handling vision-based LLM operations like image captioning and document layout parsing."""

    def __init__(self):
        logger.info("Initializing VisionService")
        if settings.GEMMA4_CHAT_ENDPOINT:
            self.gemma_url = settings.GEMMA4_CHAT_ENDPOINT
        elif settings.GEMMA_SERVER_BASE_URL:
            self.gemma_url = f"{settings.GEMMA_SERVER_BASE_URL.rstrip('/')}/cdot/ollama2/api/chat"
        else:
            self.gemma_url = ""
        self.gemma_key = settings.GEMMA4_API_KEY
        self.gemma_model = settings.GEMMA4_MODEL
        self.gemma_api_format = settings.GEMMA4_API_FORMAT
        
        self.numarkdown_url = settings.NUMARKDOWN_API_URL
        self.numarkdown_key = settings.NUMARKDOWN_API_KEY
        self.numarkdown_model = settings.NUMARKDOWN_MODEL

    def get_image_caption_from_bytes(self, image_bytes: bytes, mime: str = "image/jpeg") -> str:
        """Query the Gemma4 vision server to generate a caption from raw image bytes."""
        if not self.gemma_url:
            logger.warning("Gemma vision server URL is not configured.")
            return ""

        try:
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
            return self._caption_from_base64(image_base64, mime)
        except Exception as e:
            logger.error(f"Gemma 4 captioning error: {e}")
            return ""

    def _caption_from_base64(self, image_base64: str, mime: str = "image/jpeg") -> str:
        if self.gemma_api_format == "openai":
            message_content = [
                {"type": "text", "text": "Describe this image in detail. Mention all objects, text, charts, or any relevant content you see."},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_base64}"}},
            ]
        else:
            message_content = "Describe this image in detail. Mention all objects, text, charts, or any relevant content you see."

        payload = {
            "model": self.gemma_model,
            "messages": [{
                "role": "user",
                "content": message_content,
                **({"images": [image_base64]} if self.gemma_api_format != "openai" else {}),
            }],
            "stream": False,
            "max_tokens": 512,
        }

        headers = {
            "Authorization": f"Bearer {self.gemma_key}",
            "Content-Type": "application/json"
        }

        response = requests.post(self.gemma_url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        data = response.json()
        if self.gemma_api_format == "openai":
            caption = data["choices"][0]["message"]["content"]
        else:
            caption = data["message"]["content"]
        logger.info(f"Gemma 4 Caption successfully retrieved ({len(caption)} chars)")
        return caption

    def get_image_caption(self, image_path: str) -> str:
        """Query the Gemma4 vision server to generate a detailed caption for the image."""
        if not self.gemma_url:
            logger.warning("Gemma vision server URL is not configured.")
            return ""

        try:
            with open(image_path, "rb") as f:
                image_base64 = base64.b64encode(f.read()).decode("utf-8")

            return self._caption_from_base64(image_base64)

        except Exception as e:
            logger.error(f"Gemma 4 captioning error: {e}")
            return ""

    def parse_document_image(self, image_bytes: bytes) -> str:
        """Query the NuMarkdown API to parse a document page image into Markdown."""
        if not self.numarkdown_url:
            logger.warning("NuMarkdown API URL is not configured.")
            return ""

        try:
            # Check if this is a file upload endpoint (e.g. ends with /parse or has 5001)
            is_file_upload_api = "/parse" in self.numarkdown_url or "5001" in self.numarkdown_url
            
            if is_file_upload_api:
                logger.info(f"Sending image to NuMarkdown file upload API: {self.numarkdown_url}")
                # Post the raw image bytes as multipart form data
                files = {"file": ("page.png", image_bytes, "image/png")}
                response = requests.post(
                    self.numarkdown_url,
                    files=files,
                    timeout=120
                )
                response.raise_for_status()
                markdown = response.json().get("markdown", "")
            else:
                logger.info(f"Sending image to CDAC NuMarkdown Chat API: {self.numarkdown_url}")
                # Post base64 encoded image to Ollama chat endpoint
                image_base64 = base64.b64encode(image_bytes).decode("utf-8")
                payload = {
                    "model": self.numarkdown_model,
                    "messages": [{
                        "role": "user",
                        "content": (
                            "You are a precise document-to-Markdown converter. "
                            "Convert this document page image to clean, well-structured Markdown. "
                            "Follow these rules strictly:\n"
                            "1. Preserve ALL headings using # / ## / ### hierarchy exactly as they appear.\n"
                            "2. Reproduce ALL tables using Markdown pipe-table syntax (| col | col |). Do NOT flatten tables into plain text.\n"
                            "3. Preserve bullet lists (- item) and numbered lists (1. item) exactly.\n"
                            "4. Keep bold (**text**) and italic (*text*) formatting where visible.\n"
                            "5. For figures/charts/diagrams, write: [Figure: <brief description of what the figure shows>]\n"
                            "6. Preserve the reading order of the page (top to bottom, left to right).\n"
                            "7. Do NOT add any commentary, preamble, or explanation — output ONLY the Markdown content of the page."
                        ),
                        "images": [image_base64]
                    }],
                    "stream": False
                }
                
                headers = {}
                if self.numarkdown_key:
                    headers["Authorization"] = f"Bearer {self.numarkdown_key}"
                headers["Content-Type"] = "application/json"
                
                response = requests.post(
                    self.numarkdown_url,
                    json=payload,
                    headers=headers,
                    timeout=120
                )
                response.raise_for_status()
                markdown = response.json()["message"]["content"]
                
            return markdown
            
        except Exception as e:
            logger.error(f"NuMarkdown parsing error: {e}")
            return ""

_vision_service = None

def get_vision_service() -> VisionService:
    global _vision_service
    if _vision_service is None:
        _vision_service = VisionService()
    return _vision_service
