"""Checked out / Modified / New files show only while they have something in them."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from tests.conftest import requires_git
from tests.unit.test_baselines import _product, _signed_in_admin

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _tab(html: str, name: str) -> str:
    match = re.search(rf'<button type="button" class="tab[^"]*" data-tab="{name}"([^>]*)>', html)
    assert match, name
    return match.group(1)


@requires_git
def test_empty_tabs_are_hidden_until_they_have_something(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    html = auth_client.get(f"/?product={product['uuid']}").text
    for name in ("checked-out", "modified", "changes"):
        assert " hidden" in _tab(html, name), name  # nothing in them yet: not shown
    # Files, Baselines and Discussion are never hidden
    for name in ("files", "baselines", "discussion"):
        assert " hidden" not in _tab(html, name), name

    assert auth_client.post(f"/api/objects/{objects['shaft.prt']['uuid']}/checkout").status_code == 200
    html = auth_client.get(f"/?product={product['uuid']}").text
    assert " hidden" not in _tab(html, "checked-out")  # something is checked out: shown
    assert "Checked out · 1" in html
    assert " hidden" in _tab(html, "modified")


def test_the_page_script_keeps_the_active_tab_and_hides_the_rest():
    app = (ROOT / "src/creopdm/static/js/app.js").read_text(encoding="utf-8")
    assert "function syncEmptyTabs()" in app
    assert 'tab.classList.contains("is-active")' in app  # the tab you are on never vanishes under you
    # recomputed whenever a count changes and whenever the tab changes
    assert app.count("syncEmptyTabs();") >= 3
    css = (ROOT / "src/creopdm/static/css/app.css").read_text(encoding="utf-8")
    assert ".tabs .tab[hidden] { display: none !important; }" in css
