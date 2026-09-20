"""In-memory + file log buffer for CreoPDM agent tray logs."""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

# Wired for uvicorn dictConfig / BufferHandler (must be set before the server starts).
ACTIVE_BUFFER: LogBuffer | None = None


class LogBuffer:
    def __init__(self, capacity: int = 2000, log_path: Path | None = None) -> None:
        self._lines: deque[str] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._generation = 0
        self.log_path = log_path
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, line: str) -> None:
        text = (line or "").rstrip()
        if not text:
            return
        with self._lock:
            self._lines.append(text)
            self._generation += 1
            path = self.log_path
        if path is not None:
            try:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(text + "\n")
            except OSError:
                pass

    def snapshot(self) -> tuple[int, list[str]]:
        with self._lock:
            return self._generation, list(self._lines)

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()
            self._generation += 1
            path = self.log_path
        if path is not None:
            try:
                path.write_text("", encoding="utf-8")
            except OSError:
                pass


class BufferHandler(logging.Handler):
    """Logging handler that writes into ACTIVE_BUFFER (or an explicit buffer)."""

    def __init__(self, level: int = logging.NOTSET, buffer: LogBuffer | None = None) -> None:
        super().__init__(level)
        self._buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            target = self._buffer or ACTIVE_BUFFER
            if target is None:
                return
            stamp = datetime.now().strftime("%H:%M:%S")
            message = self.format(record)
            target.append(f"{stamp} {message}")
        except Exception:
            self.handleError(record)


def uvicorn_log_config() -> dict:
    """dictConfig that sends uvicorn + agent logs into ACTIVE_BUFFER."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": False,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
                "use_colors": False,
            },
            "plain": {"format": "%(levelname)s %(name)s: %(message)s"},
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "creopdm_agent.logbuf.BufferHandler",
            },
            "access": {
                "formatter": "access",
                "class": "creopdm_agent.logbuf.BufferHandler",
            },
            "plain": {
                "formatter": "plain",
                "class": "creopdm_agent.logbuf.BufferHandler",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["access"], "level": "INFO", "propagate": False},
            "creopdm_agent": {"handlers": ["plain"], "level": "INFO", "propagate": False},
        },
    }


def install_log_buffer(buffer: LogBuffer, level: int = logging.INFO) -> BufferHandler:
    global ACTIVE_BUFFER
    ACTIVE_BUFFER = buffer
    handler = BufferHandler(level=level, buffer=buffer)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "creopdm_agent"):
        logger = logging.getLogger(name)
        logger.setLevel(level)
        for existing in list(logger.handlers):
            if isinstance(existing, BufferHandler):
                logger.removeHandler(existing)
        logger.addHandler(handler)
        logger.propagate = False
    buffer.append("CreoPDM agent log started")
    logging.getLogger("creopdm_agent").info("Log capture ready")
    return handler
