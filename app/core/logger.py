"""
Structured logging configuration for Pulline API.
Supports JSON and plain text formats for dev/prod environments.
"""

import logging
import logging.config
import json
import sys
from typing import Optional
from app.core.config import get_settings


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields if present
        if hasattr(record, "extra"):
            log_data.update(record.extra)

        return json.dumps(log_data)


class PlainFormatter(logging.Formatter):
    """Plain text formatter for development."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as plain text."""
        base_format = "[%(asctime)s] %(levelname)-8s | %(name)s.%(funcName)s:%(lineno)d | %(message)s"
        return super().format(record)


def setup_logging() -> None:
    """Configure logging based on environment settings."""
    settings = get_settings()

    # Map string log levels to logging module levels
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Choose formatter
    if settings.LOG_FORMAT == "json":
        formatter = JSONFormatter()
    else:
        formatter = PlainFormatter(
            "[%(asctime)s] %(levelname)-8s | %(name)s.%(funcName)s:%(lineno)d | %(message)s"
        )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()  # Remove default handlers
    root_logger.addHandler(console_handler)

    # Set specific loggers - suppress verbose third-party libraries
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.

    Args:
        name: The name of the logger (typically __name__ from the calling module)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)
