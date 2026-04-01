# config.py in root directory
from app.config import ConfigFactory

# Create a compatibility class
class Config:
    """Compatibility wrapper for old Config class"""
    
    # Get the actual config
    _config = ConfigFactory.get_config('default')
    
    # Define properties that redirect to the new config
    ES_BASE_URL = _config.ES_BASE_URL
    MONGO_URL = _config.MONGO_URL
    MYSQL_HOST = _config.MYSQL_HOST
    MYSQL_USERNAME = _config.MYSQL_USERNAME
    MYSQL_PASSWORD = _config.MYSQL_PASSWORD
    MYSQL_PORT = _config.MYSQL_PORT
    NEO4J_URI = _config.NEO4J_URI
    NEO4J_USERNAME = _config.NEO4J_USERNAME
    NEO4J_PASSWORD = _config.NEO4J_PASSWORD
    OLLAMA_BASE_URL = _config.OLLAMA_BASE_URL
    OLLAMA_LLM_MODEL = _config.OLLAMA_LLM_MODEL
    MISTRAL_OCR_API_KEY = _config.MISTRAL_OCR_API_KEY
    ELEVENLABS_API_KEY = _config.ELEVENLABS_API_KEY
    GPU_SERVER_BASE_URL = _config.GPU_SERVER_BASE_URL
    GPU_SERVER_API_KEY = _config.GPU_SERVER_API_KEY
    GPU_SERVER_MODEL = _config.GPU_SERVER_MODEL
    GPU_SERVER_DEFAULT_MAX_TOKENS = _config.GPU_SERVER_DEFAULT_MAX_TOKENS
    GPU_SERVER_VERIFY_SSL = _config.GPU_SERVER_VERIFY_SSL