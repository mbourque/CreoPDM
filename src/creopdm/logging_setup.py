"""Rotating file logging for the local application."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from creopdm.constants import APP_NAME

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 5


def setup_logging(log_path: Path, level: int = logging.INFO) -> logging.Logger:
    """Configure application logging to a rotating file and stderr."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("creopdm")
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    logging.captureWarnings(True)
    logger.debug("%s logging initialized at %s", APP_NAME, log_path)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    if name:
        return logging.getLogger("creopdm").getChild(name)
    return logging.getLogger("creopdm")
