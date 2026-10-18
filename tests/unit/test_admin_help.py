"""How to administrate CreoPDM: the administrator help page and where its Help pill points."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.auth_constants import BuiltinRole
from creopdm.config import ConfigManager
from tests.unit.test_auth import _login, _setup_admin_and_users

ROOT = Path(__file__).resolve().parents[2]
ADMIN_HELP = ROOT / "src" / "creopdm" / "static" / "help" / "admin.html"
USER_HELP = ROOT / "src" / "creopdm" / "static" / "help" / "index.html"
BASE_HTML = ROOT / "src" / "creopdm" / "templates" / "base.html"


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def test_admin_help_page_is_packaged_and_styled_like_the_user_help():
    text = ADMIN_HELP.read_text(encoding="utf-8")
    assert "How to administrate CreoPDM" in text
    assert "Administrator help" in text
    # Same look: it reuses the user help's styles and contents script.
    user = USER_HELP.read_text(encoding="utf-8")
    assert text.split("</style>")[0].split("<style>")[1] == user.split("</style>")[0].split("<style>")[1]
    assert 'id="menuBtn"' in text and "nearBottom" in text
    assert "fonts.googleapis.com" not in text
    for section in (
        "start",
        "users",
        "roles",
        "products",
        "membership",
        "lifecycle",
        "promote",
        "revise",
        "danger",
        "settings",
        "email",
        "ai",
        "utilities",
        "health",
        "audit",
        "tips",
    ):
        assert f'id="{section}"' in text, section
        assert f'href="#{section}"' in text, section
    for needle in (
        "objects.revise",
        "Revise (new revision)",
        "Use hash",
        "undo the release",
        "Discard changes",
        "Revision created",
        "state ∩ role",
        "Utilities → Logs",
        # Pages and fields are explained, not just named.
        "New users get no product access",
        "Save members",
        "Reset to defaults",
        "Add lifecycle state",
        "Rebuild file list from vault Git tip",
        "Compact product vault history",
        "Export CSV",
        "Authenticated SMTP",
        "Snapshot compare prompt",
        "file list refresh interval",
        "git fsck",
    ):
        assert needle in text, needle
    # Every System Settings tile is described.
    from creopdm.settings_hub import SETTINGS_HUB_TILES

    for tile in SETTINGS_HUB_TILES:
        assert f"<td>{tile.title}</td>" in text, tile.title


def test_help_pill_points_at_admin_help_on_admin_and_settings_pages():
    base = BASE_HTML.read_text(encoding="utf-8")
    assert 'href="/help/admin"' in base and 'href="/help"' in base
    assert "request.url.path.startswith('/admin')" in base
    assert "request.url.path.startswith('/settings')" in base
    # Still left of the Administration pill.
    assert base.index('href="/help/admin"') < base.index('href="/admin"')
    assert base.index('href="/help"') < base.index('href="/admin"')


def test_admin_help_route_is_for_administrators(auth_client, auth_ctx):
    _setup_admin_and_users(
        auth_client,
        auth_ctx,
        ("eng", BuiltinRole.ENGINEER.value),
        ("view", BuiltinRole.VIEWER.value),
    )
    _login(auth_client, "admin", "AdminPass1")
    page = auth_client.get("/help/admin")
    assert page.status_code == 200, page.text
    assert "text/html" in (page.headers.get("content-type") or "")
    assert "How to administrate CreoPDM" in page.text
    # On Administration and System Settings the Help pill opens it; elsewhere the user help.
    admin = auth_client.get("/admin")
    assert admin.status_code == 200
    assert 'href="/help/admin"' in admin.text and 'href="/help"' not in admin.text
    settings = auth_client.get("/settings")
    assert settings.status_code == 200
    assert 'href="/help/admin"' in settings.text
    files = auth_client.get("/")
    assert 'href="/help"' in files.text and 'href="/help/admin"' not in files.text

    for username, password in (("eng", "EngPass1"), ("view", "ViewPass1")):
        _login(auth_client, username, password)
        denied = auth_client.get("/help/admin")
        assert denied.status_code == 403, (username, denied.text)
        # The regular help stays open to everyone who is signed in.
        assert auth_client.get("/help").status_code == 200
