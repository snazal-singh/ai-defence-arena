from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # App settings
    SECRET_KEY: str = "supersecretkey"
    DEBUG: bool = False
    TESTING: bool = False
    
    # Elasticsearch
    ES_BASE_URL: str
        
    # MongoDB
    MONGO_URL: str

    # Symmetric key (Fernet, 32 url-safe base64-encoded bytes) used to encrypt
    # user-supplied external MongoDB connection strings at rest. Generate with
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
    EXTERNAL_MONGO_ENCRYPTION_KEY: str = ""

    # DEV/TESTING ONLY: the external-Mongo-connector SSRF guard
    # (controllers/external_mongo_connection.py) normally rejects
    # localhost/private/loopback hosts, since a real deployment's backend
    # could otherwise be pointed at its own internal infrastructure. Set to
    # true only for local development against a Mongo instance on the same
    # machine — never enable this in a real deployment.
    ALLOW_LOCAL_MONGO: bool = False
    
    # MySQL
    MYSQL_HOST: str
    MYSQL_USERNAME: str
    MYSQL_PASSWORD: str
    MYSQL_PORT: int = 3306
    
    # JWT Settings
    JWT_SECRET_KEY: str = "secret"
    JWT_ALGORITHM: str = "HS256"

    # Neo4j Settings
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USERNAME: str = "neo4j"
    NEO4J_PASSWORD: str = "changeme_strong_password"

    OLLAMA_BASE_URL: str
    OLLAMA_LLM_MODEL: str = "qwen2.5:7b"
    OLLAMA_EMBEDDING_MODEL: str = "bge-m3:latest"

    # Reranking: a cross-encoder re-scores each (query, chunk) pair directly
    # after hybrid retrieval, before chunks are capped/formatted into the LLM
    # context. Unlike EnsembleRetriever's rank fusion (which only combines
    # keyword/vector ranks without looking at content), this actually scores
    # relevance. bge-reranker-v2-m3 is multilingual and pairs with the
    # bge-m3 embedding model already used for vector search.
    ENABLE_RERANKER: bool = True
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    # Candidates pulled from each retrieval branch before reranking (wider
    # than the final context so the reranker has real material to sort).
    RERANKER_CANDIDATE_K: int = 20
    # Chunks kept after reranking, handed off to the existing table-first
    # sort + 5-text/15-total cap in context_provider_service.
    RERANKER_TOP_N: int = 15

    # Document summary tuning
    SUMMARY_FALLBACK_CHAR_LIMIT: int = 5000
    SUMMARY_MIN_SENTENCES: int = 60
    SUMMARY_MAX_SENTENCES: int = 300
    SUMMARY_EXTRACTION_RATIO: float = 0.35

    # Mistral OCR
    MISTRAL_OCR_API_KEY: str

    # Eleven Labs TTS
    ELEVENLABS_API_KEY: str

    # OpenAI / Gemini
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""

    # File storage
    BASE_USERS_DIR: str = "users"

    # Bhashini translation
    BHASHINI_INFERENCE_KEY: str = ""
    TRANSLATION_SERVER_URL: str = "http://localhost:8765"

    # GPU inference server
    GPU_SERVER_BASE_URL: str = ""
    GPU_SERVER_API_KEY: str = ""
    GPU_SERVER_MODEL: str = "llama3.1:8b"
    GPU_SERVER_DEFAULT_MAX_TOKENS: int = 8000
    GPU_SERVER_VERIFY_SSL: bool = False

    # Temporary local fallback while GPU_SERVER_BASE_URL is unreachable.
    # Set USE_LOCAL_LLM=true in .env to route get_fast_llm()/get_standard_llm()
    # etc. to a local Ollama model instead. Revert by setting it back to false
    # (or removing it) once the remote GPU server is back up.
    USE_LOCAL_LLM: bool = False
    LOCAL_LLM_BASE_URL: str = "http://127.0.0.1:11434"
    LOCAL_LLM_MODEL: str = "mistral:latest"

    # Gemma server
    GEMMA_SERVER_BASE_URL: str = ""
    GEMMA4_API_KEY: str = ""
    GEMMA4_MODEL: str = "gemma4:26b"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
