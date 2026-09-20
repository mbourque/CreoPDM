"""In-memory ring buffer for CreoPDM agent tray logs."""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime


class LogBuffer:
    def __init__(self, capacity: int = 2000) -> None:
        self._lines: deque[str] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._generation = 0

    def append(self, line: str) -> None:
        text = (line or "").rstrip()
        if not text:
            return
        with self._lock:
            self._lines.append(text)
            self._generation += 1

    def snapshot(self) -> tuple[int, list[str]]:
        with self._lock:
            return self._generation, list(self._lines)

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()
            self._generation += 1


class BufferHandler(logging.Handler):
    def __init__(self, buffer: LogBuffer) -> None:
        super().__init__()
        self._buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stamp = datetime.now().strftime("%H:%M:%S")
            message = self.format(record)
            self._buffer.append(f"{stamp} {message}")
        except Exception:
            self.handleError(record)


def install_log_buffer(buffer: LogBuffer, level: int = logging.INFO) -> BufferHandler:
    handler = BufferHandler(buffer)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "creopdm_agent"):
        logger = logging.getLogger(name)
        logger.setLevel(level)
        # Avoid duplicate handlers when tray restarts in-process.
        for existing in list(logger.handlers):
            if isinstance(existing, BufferHandler):
                logger.removeHandler(existing)
        logger.addHandler(handler)
        logger.propagate = False
    logging.getLogger("creopdm_agent").info("CreoPDM agent log window ready")
    return handler
