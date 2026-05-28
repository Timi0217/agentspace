"""
Structured logging configuration for the Chekk backend.

Usage in any module:
    from app.core.logging import get_logger
    logger = get_logger(__name__)
    logger.info("Something happened", extra={"candidate": username})
"""

import logging
import sys

from app.core.config import settings

_configured = False


def setup_logging():
    """Configure root logger with structured format. Called once at startup."""
    global _configured
    if _configured:
        return
    _configured = True

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger("app")
    root.setLevel(level)
    root.addHandler(handler)
    # Prevent duplicate logs if uvicorn also adds handlers
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Get a logger for the given module name."""
    setup_logging()
    return logging.getLogger(name)
