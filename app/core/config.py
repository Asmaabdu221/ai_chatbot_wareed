"""
Application Configuration Module
Manages all environment variables and application settings
"""

import os
import json
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
import logging
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_DEFAULT = PROJECT_ROOT / ".env"
ENV_LOCAL = PROJECT_ROOT / ".env.local"

# Load environment variables with safe precedence:
# 1) OS environment
# 2) .env.local (preferred for local development)
# 3) .env (defaults)
load_dotenv(ENV_LOCAL, override=False)
load_dotenv(ENV_DEFAULT, override=False)


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables
    """
    
    # Application Settings
    APP_NAME: str = "Wareed AI Medical Assistant"
    APP_VERSION: str = "0.1.0"
    APP_DESCRIPTION: str = "Arabic Medical Chatbot API"
    DEBUG: bool = False
    
    # API Keys
    OPENAI_API_KEY: str = Field(..., description="OpenAI API Key")
    
    # OpenAI Configuration
    OPENAI_MODEL: str = Field(default="gpt-4", description="OpenAI model to use")
    OPENAI_MAX_TOKENS: int = Field(default=500, description="Max tokens for responses")
    OPENAI_TEMPERATURE: float = Field(default=0.7, description="Temperature for AI responses")
    OPENAI_EMBEDDING_MODEL: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model for semantic search"
    )
    # RAG: minimum cosine similarity to allow answer (0.0-1.0). Below = "no info" response.
    # 0.58-0.60 improves recall for symptom-based queries (نوم، مزاج، معدة); 0.75 was too strict.
    RAG_SIMILARITY_THRESHOLD: float = Field(
        default=0.58,
        description="Minimum cosine similarity for grounded retrieval (no hallucination)"
    )
    OPENAI_VISION_MODEL: str = Field(
        default="gpt-4o",
        description="OpenAI vision model for prescription image analysis"
    )
    
    # Database Configuration (Production PostgreSQL)
    # Leave empty to run without DB (demo mode). Set for production (e.g. chat.wareed.com.sa).
    DATABASE_URL: str = Field(
        default="",
        description="PostgreSQL connection URL (e.g. postgresql://chat_user:pass@localhost:5432/chat_user)"
    )
    
    # Database Connection Pool Settings
    DB_POOL_SIZE: int = Field(default=5, description="Database connection pool size")
    DB_MAX_OVERFLOW: int = Field(default=10, description="Max overflow connections")
    DB_POOL_TIMEOUT: int = Field(default=30, description="Pool checkout timeout in seconds")
    DB_POOL_RECYCLE: int = Field(default=3600, description="Connection recycle time in seconds")
    
    # Logging Configuration
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    LOG_FILE: str = Field(default="logs/wareed_app.log", description="Log file path")
    LOG_MAX_BYTES: int = Field(default=10485760, description="Max log file size (10MB)")
    LOG_BACKUP_COUNT: int = Field(default=5, description="Number of log backup files")
    
    # Security
    CORS_ORIGINS: list = Field(
        default=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
            "http://localhost:8000",
        ],
        description="Allowed CORS origins (comma-separated in .env)"
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, list):
            return v
        if v is None:
            return v
        if isinstance(v, str):
            raw = v.strip()
            if not raw:
                return v
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        return [str(x).strip() for x in parsed if str(x).strip()]
                except Exception:
                    pass
            return [x.strip() for x in raw.split(",") if x.strip()]
        return v
    
    # JWT Authentication (platform-agnostic: Web + Mobile, Bearer token only)
    SECRET_KEY: str = Field(
        default="change-me-in-production-use-long-random-secret",
        description="Secret key for JWT signing (set strong value in production)"
    )
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60, description="Access token TTL in minutes")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, description="Refresh token TTL in days")
    
    # Rate Limiting (for future implementation)
    RATE_LIMIT_PER_MINUTE: int = Field(default=20, description="API requests per minute")

    # Knowledge Base auto-reload (check file mtime and reload when changed)
    KB_AUTO_RELOAD_ENABLED: bool = Field(default=True, description="Enable automatic KB reload on file change")
    KB_AUTO_RELOAD_INTERVAL_SECONDS: int = Field(default=60, description="Seconds between KB file checks")

    # Style Retrieval Layer (Hybrid Knowledge: RAG + Style examples)
    ENABLE_STYLE_RAG: bool = Field(default=True, description="Enable style-example retrieval for prompt guidance")
    STYLE_TOP_K: int = Field(default=3, description="Top style examples to retrieve")
    STYLE_MIN_SCORE: float = Field(default=0.78, description="Minimum cosine score for style example retrieval")
    STYLE_MAX_CHARS_PER_EXAMPLE: int = Field(default=400, description="Max chars per retrieved style example")
    STYLE_FALLBACK_LEXICAL: bool = Field(default=True, description="Use lexical fallback when style embeddings are unavailable")
    STYLE_FALLBACK_MIN_SCORE: float = Field(default=0.25, description="Minimum lexical similarity score for style fallback")
    CUSTOMER_SERVICE_PHONE: str = Field(default="+XXXXXXXX", description="Customer service contact phone")

    # Internal Leads Delivery
    INTERNAL_LEADS_WEBHOOK_URL: str = Field(
        default="",
        description="POST endpoint for lead delivery (empty = log-only stub mode)",
    )
    INTERNAL_LEADS_WEBHOOK_TIMEOUT_SECONDS: int = Field(
        default=5,
        description="HTTP timeout for lead webhook calls",
    )
    INTERNAL_LEADS_API_KEY: str = Field(
        default="",
        description="Bearer token required to call /internal/leads endpoints",
    )

    model_config = SettingsConfigDict(
        env_file=None,
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="forbid",
        env_parse_json=False,
        env_ignore_empty=True,
    )


# Create a global settings instance
settings = Settings()


def setup_logging():
    """
    Configure logging for the application with file rotation
    """
    # Create logs directory if it doesn't exist
    log_dir = os.path.dirname(settings.LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Configure logging
    from logging.handlers import RotatingFileHandler
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler with rotation
    file_handler = RotatingFileHandler(
        settings.LOG_FILE,
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(getattr(logging, settings.LOG_LEVEL))
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(getattr(logging, settings.LOG_LEVEL))
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL))
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Log startup message
    logging.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} starting up...")
    logging.info(f"📝 Logging configured - Level: {settings.LOG_LEVEL}")
    logging.info(f"📁 Log file: {settings.LOG_FILE}")


# Get logger instance
logger = logging.getLogger(__name__)
