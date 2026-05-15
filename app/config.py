"""
Configuration module for the Flask application.

This module provides configuration management through environment variables
and different configuration classes for different environments.
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class BaseConfig:
    """Base configuration with common settings."""
    
    # App settings
    SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey")
    DEBUG = False
    TESTING = False
    
    # MongoDB
    MONGO_URL = os.getenv("MONGO_URL")
    
    # MySQL
    MYSQL_HOST = os.getenv("MYSQL_HOST")
    MYSQL_USERNAME = os.getenv("MYSQL_USERNAME")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
    
    # JWT Settings
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "secret")
    JWT_ALGORITHM = "HS256"
    
    # Rate limiting
    RATELIMIT_DEFAULT = "300 per day, 30 per hour"
    RATELIMIT_STRATEGY = "fixed-window"
    RATELIMIT_STORAGE_URL = "memory://"


    # Ollama
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")

    # Eleven Labs TTS
    ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

    # GPU Server
    GPU_SERVER_BASE_URL = os.getenv("GPU_SERVER_BASE_URL")
    GPU_SERVER_API_KEY = os.getenv("GPU_SERVER_API_KEY")
    GPU_SERVER_MODEL = os.getenv("GPU_SERVER_MODEL")
    GPU_SERVER_DEFAULT_MAX_TOKENS = int(os.getenv("GPU_SERVER_DEFAULT_MAX_TOKENS"))
    GPU_SERVER_VERIFY_SSL = os.getenv("GPU_SERVER_VERIFY_SSL", "false").lower() == "true"

    # Document Summary
    BASE_USERS_DIR = os.getenv("BASE_USERS_DIR")
    SUMMARY_FALLBACK_CHAR_LIMIT = int(os.getenv("SUMMARY_FALLBACK_CHAR_LIMIT", 5000))
    SUMMARY_MIN_SENTENCES = int(os.getenv("SUMMARY_MIN_SENTENCES", 60))
    SUMMARY_MAX_SENTENCES = int(os.getenv("SUMMARY_MAX_SENTENCES", 300))
    SUMMARY_EXTRACTION_RATIO = float(os.getenv("SUMMARY_EXTRACTION_RATIO", 0.35))
    
    @staticmethod
    def validate():
        """Validate that all required settings are present."""
        required_vars = [
            "ELEVENLABS_API_KEY",
            "MONGO_URL", "MYSQL_HOST", "MYSQL_USERNAME", "MYSQL_PASSWORD", "OLLAMA_BASE_URL"
        ]
        
        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            raise EnvironmentError(
                f"Missing environment variables: {', '.join(missing)}"
            )

class DevelopmentConfig(BaseConfig):
    """Development environment configuration."""
    DEBUG = True
    # Add development-specific settings

class TestingConfig(BaseConfig):
    """Testing environment configuration."""
    TESTING = True
    DEBUG = True
    # Add testing-specific settings
    
    # Use in-memory databases for testing
    MONGO_URL = "mongodb://localhost:27017/test"
    
    # Override validation for testing
    @staticmethod
    def validate():
        """Skip validation in testing environment."""
        pass

class ProductionConfig(BaseConfig):
    """Production environment configuration."""
    # Add production-specific settings
    
    # Override with stronger secret key for production
    SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")
    if not SECRET_KEY:
        raise ValueError("SECRET_KEY environment variable is required in production")
    
    # More strict rate limiting for production
    RATELIMIT_DEFAULT = "200 per day, 200 per hour"

class ConfigFactory:
    """Factory class to create configuration objects."""
    
    @staticmethod
    def get_config(config_name):
        """
        Get the appropriate configuration class based on the name.
        
        Args:
            config_name (str): Name of the configuration to use
            
        Returns:
            Config class: The configuration class to use
            
        Raises:
            ValueError: If an invalid configuration name is provided
        """
        configs = {
            "development": DevelopmentConfig,
            "testing": TestingConfig,
            "production": ProductionConfig,
            "default": DevelopmentConfig
        }
        
        if config_name not in configs:
            raise ValueError(f"Invalid configuration name: {config_name}")
        
        config_class = configs[config_name]
        
        # Validate configuration
        if config_name != "testing":
            config_class.validate()
            
        return config_class


# Convenience alias — used by application modules via `from app.config import Config`
Config = DevelopmentConfig
