"""Site availability (maintenance) is display-only for non-administrators."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from creopdm.app import build_context, create_app
from creopdm.auth_constants import BuiltinRole, UserStatus
from creopdm.config import ConfigManager
from creopdm.models.user import User
from creopdm.site_availability import (
    DEFAULT_SITE_UNAVAILABLE_MESSAGE,
    SITE_UNAVAILABLE,
    default_unavailable_message,
    is_stock_unavailable_message,
    message_for_unavailable_save,
    site_is_unavailable,
)
from tests.conftest import requires_git


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _setup_admin_and_viewer(auth_client, auth_ctx) -> None:
    auth_client.post(
        "/setup",
        data={
            "display_name": "Admin",
            "username": "admin",
            "email": "admin@example.com",
            "password": "AdminPass1",
            "password_confirm": "AdminPass1",
        },
        follow_redirects=False,
    )
    created = auth_client.post(
        "/admin/users/new",
        data={
            "display_name": "View",
            "username": "view",
            "email": "view@example.com",
            "role": BuiltinRole.VIEWER.value,
            "status": UserStatus.ACTIVE.value,
            "password": "ViewPass1",
            "password_confirm": "ViewPass1",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    with auth_ctx.session_factory() as db:
        user = db.scalar(select(User).where(User.username == "view"))
        assert user is not None
        user.must_change_password = False
        auth_ctx.user_accounts.set_product_access(db, user, access_all=True)
        db.commit()
    auth_client.get("/logout", follow_redirects=False)


def _login(auth_client, username: str, password: str) -> None:
    auth_client.get("/logout", follow_redirects=False)
    ok = auth_client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert ok.status_code == 303, ok.text


def test_settings_defaults_available_and_default_message():
    from datetime import datetime, timezone

    from creopdm.config import AppSettings

    settings = AppSettings()
    assert settings.ui.site_availability == "available"
    assert not site_is_unavailable(settings)
    assert DEFAULT_SITE_UNAVAILABLE_MESSAGE.startswith("CreoPDM is undergoing maintenance")
    when = datetime(2026, 10, 3, 10, 50, tzinfo=timezone.utc)
    stamped = default_unavailable_message(when=when)
    assert stamped.startswith(DEFAULT_SITE_UNAVAILABLE_MESSAGE)
    assert "\n\nSince " in stamped
    assert "at " in stamped and stamped.rstrip().endswith(".")
    assert is_stock_unavailable_message(stamped)
    assert is_stock_unavailable_message(DEFAULT_SITE_UNAVAILABLE_MESSAGE)
    assert not is_stock_unavailable_message("Custom outage note.")
    assert "Since " in message_for_unavailable_save(
        was_unavailable=False, message="", when=when
    )
    assert message_for_unavailable_save(
        was_unavailable=False, message="Custom outage note.", when=when
    ) == "Custom outage note."


@requires_git
def test_unavailable_hides_pages_from_viewer_keeps_api_and_admin(auth_client, auth_ctx):
    _setup_admin_and_viewer(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    product = auth_client.post("/api/products", json={"name": "Avail Prod"}).json()

    custom = auth_client.put(
        "/api/settings",
        json={
            "creo_open_mode": "association",
            "site_availability": SITE_UNAVAILABLE,
            "site_unavailable_message": "Down for a vault move. Back soon.",
        },
    )
    assert custom.status_code == 200, custom.text
    assert custom.json()["site_unavailable_message"] == "Down for a vault move. Back soon."

    # Back to available, then unavailable with stock message → pretty Since stamp.
    assert (
        auth_client.put(
            "/api/settings",
            json={"creo_open_mode": "association", "site_availability": "available"},
        ).status_code
        == 200
    )
    saved = auth_client.put(
        "/api/settings",
        json={
            "creo_open_mode": "association",
            "site_availability": SITE_UNAVAILABLE,
            "site_unavailable_message": DEFAULT_SITE_UNAVAILABLE_MESSAGE,
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["site_availability"] == "unavailable"
    assert body["site_unavailable_message"].startswith(DEFAULT_SITE_UNAVAILABLE_MESSAGE)
    assert "\n\nSince " in body["site_unavailable_message"]
    assert body["default_site_unavailable_message"] == DEFAULT_SITE_UNAVAILABLE_MESSAGE

    # Admin still uses the app and sees the warning pill.
    admin_home = auth_client.get(f"/?product={product['uuid']}")
    assert admin_home.status_code == 200
    assert 'id="site-unavailable-pill"' in admin_home.text
    assert "Unavailable" in admin_home.text
    assert 'href="/settings#site-availability"' in admin_home.text
    # Pill is in the DOM when settings.manage; hidden only when available.
    assert "hidden" not in admin_home.text.split('id="site-unavailable-pill"', 1)[1].split(">", 1)[0]
    assert 'id="object-table"' in admin_home.text
    settings_page = auth_client.get("/settings")
    assert settings_page.status_code == 200
    assert 'id="site-availability"' in settings_page.text
    assert 'id="site-unavailable-pill"' in settings_page.text
    assert "CreoPDM available" in settings_page.text
    assert "CreoPDM unavailable" in settings_page.text
    assert "display-only" in settings_page.text

    # Viewer HTML is replaced; product API still works (no mid-flight disruption).
    _login(auth_client, "view", "ViewPass1")
    blocked = auth_client.get(f"/?product={product['uuid']}")
    assert blocked.status_code == 200
    assert "CreoPDM is unavailable" in blocked.text
    assert "undergoing maintenance" in blocked.text
    assert "Since " in blocked.text
    assert 'id="object-table"' not in blocked.text
    assert auth_client.get(f"/api/products/{product['uuid']}").status_code == 200
    assert auth_client.get("/api/products").status_code == 200

    # Soft-nav style HTML fetch also gets the maintenance page.
    soft = auth_client.get(
        "/",
        headers={"Accept": "text/html", "X-CreoPDM-Soft": "1"},
    )
    assert soft.status_code == 200
    assert "Since " in soft.text


@requires_git
def test_settings_html_and_js_wire_availability(auth_client, auth_ctx):
    _setup_admin_and_viewer(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    page = auth_client.get("/settings")
    assert page.status_code == 200
    assert 'name="site_availability"' in page.text
    assert 'id="site-unavailable-message"' in page.text
    script = auth_client.get("/static/js/app.js")
    assert script.status_code == 200
    assert "function syncSiteAvailabilityOptions(" in script.text
    assert "function syncUnavailableAdminPill(" in script.text
    assert "function prettyUnavailableSince(" in script.text
    assert "syncUnavailableAdminPill(" in script.text
    assert "site_availability" in script.text
    assert "site_unavailable_message" in script.text
    assert 'data-default-base=' in page.text
    assert 'id="site-unavailable-pill"' in page.text
