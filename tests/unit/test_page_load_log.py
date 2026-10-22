"""One log line per HTML page request, so a browser reload can be told from a visit or a soft navigation."""

from __future__ import annotations

import logging


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _watch():
    handler = _Capture()
    logger = logging.getLogger("creopdm.page-load")
    logger.addHandler(handler)
    return logger, handler


def test_a_page_request_is_logged_with_how_it_was_made(client):
    logger, handler = _watch()
    try:
        client.get("/", headers={"Cache-Control": "max-age=0", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})
        client.get("/", headers={"X-CreoPDM-Soft": "1", "Sec-Fetch-Mode": "cors"})
    finally:
        logger.removeHandler(handler)
    pages = [line for line in handler.lines if line.startswith("Page /")]
    assert len(pages) >= 2, handler.lines
    reload_line, soft_line = pages[0], pages[1]
    assert "soft=no" in reload_line and "mode=navigate" in reload_line and "cache=max-age=0" in reload_line
    assert "soft=yes" in soft_line and "mode=cors" in soft_line


def test_static_files_and_api_calls_are_not_logged(client):
    logger, handler = _watch()
    try:
        client.get("/static/css/app.css")
        client.get("/api/health")
    finally:
        logger.removeHandler(handler)
    assert [line for line in handler.lines if line.startswith("Page ")] == []
