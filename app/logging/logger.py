# sandbox/app/logging/logger.py
"""
Purpose: Centralized structured logging for sandbox services.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from app.config.settings import get_settings


def _build_handler(json_logs: bool) -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)

    if json_logs:
        formatter = logging.Formatter(
            fmt='{"ts":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","msg":"%(message)s"}'
        )
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s"
        )

    handler.setFormatter(formatter)
    return handler


def get_logger(name: str = "sandbox") -> logging.Logger:
    """
    Get or create logger with given name.
    
    Args:
        name: Logger name (e.g., "main", "snapshot_repo", "parsers.pdf")
    
    Returns:
        Configured logger instance
    """
    settings = get_settings()
    
    logger = logging.getLogger(name)
    logger.setLevel(settings.log_level.upper())
    logger.propagate = False
    
    if not logger.handlers:
        logger.addHandler(_build_handler(settings.log_json))
    
    return logger
