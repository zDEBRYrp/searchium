"""
Logging configuration
"""

import io
import logging
import os
import sys
from typing import Optional


def _get_utf8_stream():
    """Return a stdout wrapper that re-encodes to UTF-8, replacing unsupported chars."""
    if os.name == "nt" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return sys.stdout


def setup_logger(name: str, level: int = logging.INFO, format_string: Optional[str] = None) -> logging.Logger:
    """
    Setup and return a configured logger

    Args:
        name: Logger name
        level: Logging level
        format_string: Custom format string

    Returns:
        Configured logger
    """
    if format_string is None:
        format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Remove existing handlers
    logger.handlers.clear()

    # Create console handler (UTF-8 safe on Windows)
    stream = _get_utf8_stream()
    handler = logging.StreamHandler(stream)
    handler.setLevel(level)

    # Create formatter
    formatter = logging.Formatter(format_string)
    handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(handler)

    # Prevent propagation to root logger
    logger.propagate = False

    return logger


# Create default logger
logger = setup_logger("searchium")
