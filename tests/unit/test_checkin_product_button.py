"""Check in product… is offered only to the person who holds checkouts (not for someone else's)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.auth_constants import BuiltinRole
from creopdm.config import ConfigManager
from tests.conftest import requires_git
from tests.unit.test_auth import _login, _setup_admin_and_users


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _product_button(html: str) -> str:
    match = re.search(r'<button[^>]*id="checkin-product-btn"[^>]*>', html)
    assert match, "Check in product… button missing"
    return match.group(0)


@requires_git
def test_check_in_product_needs_your_own_checkouts(auth_client, auth_ctx):
    _setup_admin_and_users(
        auth_client,
        auth_ctx,
        ("david", BuiltinRole.ENGINEER.value),
        ("erin", BuiltinRole.ENGINEER.value),
    )
    _login(auth_client, "admin", "AdminPass1")
    product = auth_client.post("/api/products", json={"name": "Checkin Scope"}).json()
    obj = auth_client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("shaft.prt", b"v1", "application/octet-stream")},
        data={"comment": "Initial model"},
    ).json()

    _login(auth_client, "david", "DavidPass1")
    assert auth_client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    mine = auth_client.get(f"/?product={product['uuid']}")
    assert mine.status_code == 200
    tag = _product_button(mine.text)
    assert 'data-checkout-count="1"' in tag and "disabled" not in tag
    assert "Checked out · 1" in mine.text

    # Someone else's checkout does not offer Check in product… to another user.
    _login(auth_client, "erin", "ErinPass1")
    other = auth_client.get(f"/?product={product['uuid']}")
    assert other.status_code == 200
    assert "Checked out · 1" in other.text  # the tab still counts everyone's checkouts
    tag = _product_button(other.text)
    assert 'data-checkout-count="0"' in tag and "disabled" in tag

    # The file's Details page agrees.
    detail = auth_client.get(f"/products/{product['uuid']}/objects/{obj['uuid']}")
    assert detail.status_code == 200
    tag = _product_button(detail.text)
    assert 'data-checkout-count="0"' in tag and "disabled" in tag


def test_checkout_tab_loader_counts_only_my_checkouts_for_the_product_button():
    from pathlib import Path

    js = (
        Path(__file__).resolve().parents[2] / "src" / "creopdm" / "static" / "js" / "app.js"
    ).read_text(encoding="utf-8")
    assert "function setCheckedOutTabCount(count, mine)" in js
    assert "list.filter((item) => item && item.owned_by_me).length" in js
