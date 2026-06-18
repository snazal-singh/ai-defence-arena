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
        self.gemma_url = f"{settings.GEMMA_SERVER_BASE_URL.rstrip('/')}/cdot/ollama2/api/chat" if settings.GEMMA_SERVER_BASE_URL else ""
        self.gemma_key = settings.GEMMA4_API_KEY
        self.gemma_model = settings.GEMMA4_MODEL
        
        self.numarkdown_url = settings.NUMARKDOWN_API_URL
        self.numarkdown_key = settings.NUMARKDOWN_API_KEY
        self.numarkdown_model = settings.NUMARKDOWN_MODEL

    def get_image_caption(self, image_path: str) -> str:
        """Query the Gemma4 vision server to generate a detailed caption for the image."""
        if not self.gemma_url:
            logger.warning("Gemma vision server URL is not configured.")
            return ""
            
        try:
            with open(image_path, "rb") as f:
                image_base64 = base64.b64encode(f.read()).decode("utf-8")

            payload = {
                "model": self.gemma_model,
                "messages": [{
                    "role": "user",
                    "content": "Describe this image in detail. Mention all objects, text, charts, or any relevant content you see.",
                    "images": [image_base64]
                }],
                "stream": False
            }

            headers = {
                "Authorization": f"Bearer {self.gemma_key}",
                "Content-Type": "application/json"
            }

            response = requests.post(
                self.gemma_url,
                json=payload,
                headers=headers,
                timeout=60
            )
            response.raise_for_status()
            caption = response.json()["message"]["content"]
            logger.info(f"Gemma 4 Caption successfully retrieved ({len(caption)} chars)")
            return caption

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
                        "content": "Convert this document image to Markdown.",
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
