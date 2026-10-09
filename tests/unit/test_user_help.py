"""User help page and top-bar Help pill."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELP_HTML = ROOT / "src" / "creopdm" / "static" / "help" / "index.html"
BASE_HTML = ROOT / "src" / "creopdm" / "templates" / "base.html"


def test_help_page_is_packaged():
    assert HELP_HTML.is_file()
    text = HELP_HTML.read_text(encoding="utf-8")
    assert "How to use CreoPDM" in text
    assert 'id="tips"' in text
    assert "nearBottom" in text


def test_help_route_serves_page(client):
    response = client.get("/help")
    assert response.status_code == 200, response.text
    assert "text/html" in (response.headers.get("content-type") or "")
    assert "How to use CreoPDM" in response.text
    assert "Quick start" in response.text


def test_help_pill_left_of_administration_opens_named_tab():
    base = BASE_HTML.read_text(encoding="utf-8")
    help_i = base.index('href="/help"')
    admin_i = base.index('href="/admin"')
    assert help_i < admin_i
    assert 'target="creopdm-help"' in base
    assert "status-pill" in base[help_i - 80 : help_i]
