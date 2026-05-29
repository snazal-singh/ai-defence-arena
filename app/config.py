"""
Compatibility shim — kept so existing service/controller imports continue to work.
All configuration is now managed centrally in app/core/config.py (Pydantic Settings).
Do not add new config here; use `from app.core.config import settings` instead.
"""

from app.core.config import settings


class Config:
    SECRET_KEY = settings.SECRET_KEY
    DEBUG = settings.DEBUG
    TESTING = settings.TESTING

    # Elasticsearch
    ES_BASE_URL = settings.ES_BASE_URL

    # MongoDB
    MONGO_URL = settings.MONGO_URL

    # MySQL
    MYSQL_HOST = settings.MYSQL_HOST
    MYSQL_USERNAME = settings.MYSQL_USERNAME
    MYSQL_PASSWORD = settings.MYSQL_PASSWORD
    MYSQL_PORT = settings.MYSQL_PORT

    # JWT
    JWT_SECRET_KEY = settings.JWT_SECRET_KEY
    JWT_ALGORITHM = settings.JWT_ALGORITHM

    # Ollama
    OLLAMA_BASE_URL = settings.OLLAMA_BASE_URL
    OLLAMA_LLM_MODEL = settings.OLLAMA_LLM_MODEL
    OLLAMA_EMBEDDING_MODEL = settings.OLLAMA_EMBEDDING_MODEL

    # TTS
    ELEVENLABS_API_KEY = settings.ELEVENLABS_API_KEY

    # GPU server
    GPU_SERVER_BASE_URL = settings.GPU_SERVER_BASE_URL
    GPU_SERVER_API_KEY = settings.GPU_SERVER_API_KEY
    GPU_SERVER_MODEL = settings.GPU_SERVER_MODEL
    GPU_SERVER_DEFAULT_MAX_TOKENS = settings.GPU_SERVER_DEFAULT_MAX_TOKENS
    GPU_SERVER_VERIFY_SSL = settings.GPU_SERVER_VERIFY_SSL

    # Gemma server
    GEMMA_SERVER_BASE_URL = settings.GEMMA_SERVER_BASE_URL
    GEMMA4_API_KEY = settings.GEMMA4_API_KEY
    GEMMA4_MODEL = settings.GEMMA4_MODEL

    # Bhashini / translation
    BHASHINI_INFERENCE_KEY = settings.BHASHINI_INFERENCE_KEY
    TRANSLATION_SERVER_URL = settings.TRANSLATION_SERVER_URL

    # File storage & summarisation
    BASE_USERS_DIR = settings.BASE_USERS_DIR
    SUMMARY_FALLBACK_CHAR_LIMIT = settings.SUMMARY_FALLBACK_CHAR_LIMIT
    SUMMARY_MIN_SENTENCES = settings.SUMMARY_MIN_SENTENCES
    SUMMARY_MAX_SENTENCES = settings.SUMMARY_MAX_SENTENCES
    SUMMARY_EXTRACTION_RATIO = settings.SUMMARY_EXTRACTION_RATIO
