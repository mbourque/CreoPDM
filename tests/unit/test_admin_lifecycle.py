"""Administration → Lifecycle states page."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.lifecycle_policy import default_lifecycle_policy, get_lifecycle_policy, set_lifecycle_policy
from tests.unit.test_auth import _login, _setup_admin_and_users


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


@pytest.fixture(autouse=True)
def _reset_lifecycle_policy():
    set_lifecycle_policy(default_lifecycle_policy())
    yield
    set_lifecycle_policy(default_lifecycle_policy())


def test_admin_lifecycle_page_lists_matrix(auth_client, auth_ctx):
    from pathlib import Path

    _setup_admin_and_users(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    page = auth_client.get("/admin/lifecycle")
    assert page.status_code == 200, page.text
    assert "Lifecycle states" in page.text
    assert "Permission matrix" in page.text
    assert "Pre-Work" in page.text
    assert "Check Out" in page.text
    assert 'class="data-table lifecycle-matrix"' in page.text
    css = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "creopdm"
        / "static"
        / "css"
        / "app.css"
    ).read_text(encoding="utf-8")
    assert ".lifecycle-matrix th:nth-child(even)" in css
    hub = auth_client.get("/admin")
    assert hub.status_code == 200
    assert 'href="/admin/lifecycle"' in hub.text


def test_lifecycle_states_manage_gates_page(auth_client, auth_ctx):
    """lifecycle_states.manage required; products.manage alone is not enough."""
    from creopdm.auth_constants import (
        PERMISSION_PRODUCTS_MANAGE,
        PERMISSION_PRODUCTS_VIEW,
        UserStatus,
    )
    from creopdm.models.user import User
    from sqlalchemy import select

    _setup_admin_and_users(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    created = auth_client.post(
        "/admin/roles/new",
        data={
            "name": "Products Only",
            "description": "Admin products without lifecycle",
            "permission": [PERMISSION_PRODUCTS_MANAGE, PERMISSION_PRODUCTS_VIEW],
        },
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    user = auth_client.post(
        "/admin/users/new",
        data={
            "display_name": "Prod Admin",
            "username": "prodadmin",
            "email": "prodadmin@example.com",
            "role": "Products Only",
            "status": UserStatus.ACTIVE.value,
            "password": "ProdAdmin1",
            "password_confirm": "ProdAdmin1",
        },
        follow_redirects=False,
    )
    assert user.status_code == 303, user.text
    with auth_ctx.session_factory() as db:
        row = db.scalar(select(User).where(User.username == "prodadmin"))
        assert row is not None
        row.must_change_password = False
        db.commit()
    _login(auth_client, "prodadmin", "ProdAdmin1")
    denied = auth_client.get("/admin/lifecycle")
    assert denied.status_code == 403, denied.text
    assert "lifecycle_states.manage" in denied.text
    hub = auth_client.get("/admin")
    assert hub.status_code == 200
    assert 'href="/admin/products"' in hub.text
    assert 'href="/admin/lifecycle"' not in hub.text
    post_denied = auth_client.post(
        "/admin/lifecycle",
        data={"action": "reset"},
        follow_redirects=False,
    )
    assert post_denied.status_code == 403, post_denied.text


def test_admin_lifecycle_add_custom_state_appears_on_product_form(auth_client, auth_ctx):
    _setup_admin_and_users(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    added = auth_client.post(
        "/admin/lifecycle",
        data={
            "action": "add",
            "new_label": "Lab Trial",
            "new_description": "Custom experiment state",
        },
    )
    assert added.status_code == 200, added.text
    assert "Lab Trial" in added.text
    assert "LAB_TRIAL" in get_lifecycle_policy().known_keys()

    form = auth_client.get("/admin/products/new")
    assert form.status_code == 200, form.text
    assert 'value="LAB_TRIAL"' in form.text
    assert "Lab Trial" in form.text
