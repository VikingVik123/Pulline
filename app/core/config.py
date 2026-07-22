"""
Configuration management for Pulline API.
Supports environment-based settings for dev/prod.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal
import os


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Use .env files for different environments.
    """
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    # Environment
    ENV: Literal["development", "production", "testing"] = "development"
    DEBUG: bool = True

    # API
    API_TITLE: str = "Pulline API"
    API_VERSION: str = "1.0.0"
    API_DESCRIPTION: str = "Building information ingestion and processing API"

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    # PostgreSQL example: postgresql+asyncpg://user:password@localhost:5432/pulline
    DATABASE_ECHO: bool = False  # Set True to see SQL queries
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 40

    # CORS
    CORS_ORIGINS: list[str] = ["*"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list[str] = ["*"]
    CORS_ALLOW_HEADERS: list[str] = ["*"]

    # File Upload
    UPLOAD_DIR: str = "files"
    MAX_UPLOAD_SIZE_MB: int = 50 * 1024 * 1024
    ALLOWED_EXTENSIONS: set[str] = {".ifc"}

    # Redis (used for queue and caching)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_TIMEOUT: int = 30
    REDIS_TOKEN_PREFIX: str = "token:"
    REDIS_BLACKLIST_PREFIX: str = "blacklist:"
    REDIS_SESSION_PREFIX: str = "session:"
    REDIS_USER_TOKENS_PREFIX: str = "user_tokens:"
    REDIS_TOKEN_EXPIRE_BUFFER: int = 60

    # Worker Configuration
    WORKER_CONCURRENCY: int = 4
    WORKER_PREFETCH_COUNT: int = 1
    WORKER_TIMEOUT: int = 300  # seconds

    # JWT Configuration
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")

    # mail
    MAIL_SERVER: str = os.getenv("MAIL_SERVER")
    MAIL_PORT: int = os.getenv("MAIL_PORT", 587)
    MAIL_TLS: bool = os.getenv("MAIL_TLS", True)
    MAIL_SSL: bool = os.getenv("MAIL_SSL", False)

    # Email Credentials (Required)
    MAIL_USERNAME: str = os.getenv("MAIL_USERNAME", "infopulline@gmail.com")
    MAIL_PASSWORD: str = os.getenv("MAIL_PASSWORD")
    MAIL_FROM:str = os.getenv("MAIL_FROM", "noreply@pulline.com")

settings = Settings()  # Load settings from environment variables