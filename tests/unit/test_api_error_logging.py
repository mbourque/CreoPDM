"""A refused request is logged with its method, path and account, and a page stops polling after a 403."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from tests.unit.test_auth import _login
from tests.unit.test_baselines import _product, _signed_in_admin

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_a_refusal_is_logged_with_the_request_and_the_account_but_not_the_query(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    _login(auth_client, "view", "ViewPass1")
    capture = _Capture()
    logger = logging.getLogger("creopdm.api")
    logger.addHandler(capture)
    previous = logger.level
    logger.setLevel(logging.INFO)
    try:
        refused = auth_client.get("/api/admin/baselines", params={"q": "secret-search"})
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous)
    assert refused.status_code == 403
    line = next(m for m in capture.messages if "Client error FORBIDDEN" in m)
    # Enough to trace a burst of refusals to a page and an account...
    assert "GET /api/admin/baselines" in line and "user=view" in line
    # ...and nothing from the query string.
    assert "secret-search" not in line


def test_a_page_stops_polling_after_the_first_403():
    script = (ROOT / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "let pollDenied = false;" in script
    # The workspace watch records the refusal and stops asking...
    assert "if (response.status === 403) {" in script and "pollDenied = true;" in script
    assert "    if (pollDenied) return;" in script
    # ...and so does the product lifecycle poll that runs on the same page.
    assert "if (document.hidden || pollDenied) return;" in script
