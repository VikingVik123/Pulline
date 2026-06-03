"""
Configuration management for Pulline API.
Supports environment-based settings for dev/prod.
"""

from pydantic_settings import BaseSettings
from typing import Literal
import os


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Use .env files for different environments.
    """

    # Environment
    ENV: Literal["development", "production", "testing"] = "development"
    DEBUG: bool = True

    # API
    API_TITLE: str = "Pulline API"
    API_VERSION: str = "1.0.0"
    API_DESCRIPTION: str = "Building information ingestion and processing API"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./test.db"
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
    MAX_UPLOAD_SIZE_MB: int = 1000  # 1GB
    ALLOWED_EXTENSIONS: set[str] = {".ifc", ".dwg", ".pln"}

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # "json" or "plain"

    # Queue/Message Broker
    QUEUE_ENABLED: bool = False
    QUEUE_BROKER: str = "redis"  # "redis", "rabbitmq", "memory"
    QUEUE_URL: str = "redis://localhost:6379/0"
    # RabbitMQ example: amqp://guest:guest@localhost:5672//
    QUEUE_RETRY_MAX: int = 3
    QUEUE_RETRY_DELAY: int = 5  # seconds

    # Redis (used for queue and caching)
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_TIMEOUT: int = 30

    # API Keys / Security
    API_KEY_SECRET: str = "change-me-in-production"
    
    # Worker Configuration
    WORKER_CONCURRENCY: int = 4
    WORKER_PREFETCH_COUNT: int = 1
    WORKER_TIMEOUT: int = 300  # seconds

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        # Use _ prefix to skip environment variables during instantiation
        extra = "ignore"


def get_settings() -> Settings:
    """Get application settings instance."""
    return Settings()


# Conditional imports and initialization based on settings
def get_database_url(settings: Settings) -> str:
    """Get the appropriate database URL based on environment."""
    if settings.ENV == "production":
        if settings.DATABASE_URL.startswith("sqlite"):
            raise ValueError(
                "SQLite database is not allowed in production. "
                "Please set DATABASE_URL to a PostgreSQL connection string."
            )
    return settings.DATABASE_URL
