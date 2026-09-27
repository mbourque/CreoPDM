"""Unit tests for session auth, setup, login, and user admin."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from creopdm.app import build_context, create_app
from creopdm.auth_constants import BuiltinRole, UserStatus
from creopdm.config import ConfigManager
from creopdm.models.checkout import Checkout
from creopdm.models.object import EngineeringObject
from creopdm.models.user import Role, User
from creopdm.services.user_service import UserService
from creopdm.utils.identity import SessionAwareUserProvider, UserIdentity, set_request_identity
from creopdm.utils.passwords import hash_password, verify_password
from tests.conftest import requires_git


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def test_password_hash_round_trip_never_stores_plaintext():
    plain = "SecretPass1"
    hashed = hash_password(plain)
    assert plain not in hashed
    assert hashed != plain
    assert verify_password(plain, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_migration_seeds_builtin_roles(auth_ctx):
    inspector = inspect(auth_ctx.engine)
    for table in ("users", "roles", "permissions", "user_roles", "role_permissions"):
        assert table in inspector.get_table_names()
    with auth_ctx.session_factory() as db:
        names = {r.name for r in db.scalars(select(Role)).all()}
    assert names >= {
        BuiltinRole.ADMINISTRATOR.value,
        BuiltinRole.PDM_MANAGER.value,
        BuiltinRole.ENGINEER.value,
        BuiltinRole.VIEWER.value,
    }


def test_setup_creates_first_admin_and_blocks_second(auth_client, auth_ctx):
    first = auth_client.get("/setup", follow_redirects=False)
    assert first.status_code == 200
    assert "Create administrator" in first.text

    created = auth_client.post(
        "/setup",
        data={
            "display_name": "Admin User",
            "username": "admin",
            "password": "AdminPass1",
            "password_confirm": "AdminPass1",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    assert created.headers["location"] == "/"

    with auth_ctx.session_factory() as db:
        user = db.scalar(select(User).where(User.username == "admin"))
        assert user is not None
        assert user.display_name == "Admin User"
        assert "AdminPass1" not in user.password_hash
        assert verify_password("AdminPass1", user.password_hash)
        assert UserService().primary_role_name(user) == BuiltinRole.ADMINISTRATOR.value

    blocked = auth_client.get("/setup", follow_redirects=False)
    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/login"

    again = auth_client.post(
        "/setup",
        data={
            "display_name": "Other",
            "username": "other",
            "password": "OtherPass1",
            "password_confirm": "OtherPass1",
        },
        follow_redirects=False,
    )
    assert again.status_code == 303
    assert again.headers["location"] == "/login"


def test_login_logout_and_disabled_user(auth_client, auth_ctx):
    auth_client.post(
        "/setup",
        data={
            "display_name": "Admin",
            "username": "admin",
            "password": "AdminPass1",
            "password_confirm": "AdminPass1",
        },
        follow_redirects=False,
    )
    auth_client.get("/logout", follow_redirects=False)

    bad = auth_client.post(
        "/login",
        data={"username": "admin", "password": "wrong-password"},
        follow_redirects=False,
    )
    assert bad.status_code == 400
    assert "Invalid username or password" in bad.text

    ok = auth_client.post(
        "/login",
        data={"username": "admin", "password": "AdminPass1"},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    assert ok.headers["location"] == "/"

    home = auth_client.get("/", follow_redirects=False)
    assert home.status_code == 200
    assert "Admin" in home.text
    assert "Logout" in home.text
    assert "Administration" in home.text

    auth_client.get("/logout", follow_redirects=False)
    with auth_ctx.session_factory() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        UserService().update_user(db, admin.uuid, status=UserStatus.DISABLED.value)
        db.commit()

    disabled = auth_client.post(
        "/login",
        data={"username": "admin", "password": "AdminPass1"},
        follow_redirects=False,
    )
    assert disabled.status_code == 400
    assert "disabled" in disabled.text.lower()


def test_admin_can_create_user_non_admin_cannot(auth_client, auth_ctx):
    auth_client.post(
        "/setup",
        data={
            "display_name": "Admin",
            "username": "admin",
            "password": "AdminPass1",
            "password_confirm": "AdminPass1",
        },
        follow_redirects=False,
    )
    listed = auth_client.get("/admin/users")
    assert listed.status_code == 200
    assert "Add user" in listed.text

    created = auth_client.post(
        "/admin/users/new",
        data={
            "display_name": "Eng User",
            "username": "engineer1",
            "email": "",
            "role": BuiltinRole.ENGINEER.value,
            "status": UserStatus.ACTIVE.value,
            "password": "Engineer1",
            "password_confirm": "Engineer1",
        },
        follow_redirects=False,
    )
    # Successful add returns to the users list (not the new user's edit page).
    assert created.status_code == 303
    assert created.headers["location"] == "/admin/users"

    auth_client.get("/logout", follow_redirects=False)
    with auth_ctx.session_factory() as db:
        eng = db.scalar(select(User).where(User.username == "engineer1"))
        assert eng is not None
        eng.must_change_password = False
        db.commit()

    login = auth_client.post(
        "/login",
        data={"username": "engineer1", "password": "Engineer1"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    denied = auth_client.get("/admin/users", follow_redirects=False)
    assert denied.status_code == 403

    home = auth_client.get("/", follow_redirects=False)
    assert home.status_code == 200
    assert 'href="/settings"' not in home.text
    assert 'href="/admin"' not in home.text
    assert auth_client.get("/settings", follow_redirects=False).status_code == 403
    assert auth_client.get("/admin", follow_redirects=False).status_code == 403
    assert auth_client.get("/api/settings", follow_redirects=False).status_code == 403
    assert auth_client.get("/api/settings").json()["error"]["code"] == "FORBIDDEN"


def test_admin_can_open_settings(auth_client):
    auth_client.post(
        "/setup",
        data={
            "display_name": "Admin",
            "username": "admin",
            "password": "AdminPass1",
            "password_confirm": "AdminPass1",
        },
        follow_redirects=False,
    )
    home = auth_client.get("/")
    assert 'href="/admin"' in home.text
    assert 'href="/settings"' not in home.text.split("<main")[0]
    hub = auth_client.get("/admin")
    assert hub.status_code == 200
    assert "Users" in hub.text
    assert 'href="/admin/users"' in hub.text
    assert 'href="/settings"' in hub.text
    assert auth_client.get("/settings").status_code == 200
    assert auth_client.get("/api/settings").status_code == 200


def test_admin_can_edit_user(auth_client, auth_ctx):
    auth_client.post(
        "/setup",
        data={
            "display_name": "Admin",
            "username": "admin",
            "password": "AdminPass1",
            "password_confirm": "AdminPass1",
        },
        follow_redirects=False,
    )
    created = auth_client.post(
        "/admin/users/new",
        data={
            "display_name": "Paul",
            "username": "paul",
            "email": "",
            "role": BuiltinRole.ENGINEER.value,
            "status": UserStatus.ACTIVE.value,
            "password": "PaulPass1",
            "password_confirm": "PaulPass1",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303

    with auth_ctx.session_factory() as db:
        paul = db.scalar(select(User).where(User.username == "paul"))
        assert paul is not None
        paul_uuid = paul.uuid

    listed = auth_client.get("/admin/users")
    assert listed.status_code == 200
    assert f'href="/admin/users/{paul_uuid}"' in listed.text
    assert "Click a name to edit" in listed.text
    assert ">Edit</a>" not in listed.text

    detail = auth_client.get(f"/admin/users/{paul_uuid}")
    assert detail.status_code == 200
    assert "Edit user" in detail.text
    assert 'value="paul"' in detail.text or ">paul<" in detail.text

    saved = auth_client.post(
        f"/admin/users/{paul_uuid}",
        data={
            "display_name": "Paul Updated",
            "email": "paul@example.com",
            "role": BuiltinRole.VIEWER.value,
            "status": UserStatus.DISABLED.value,
            "password": "",
            "password_confirm": "",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"] == "/admin/users"

    with auth_ctx.session_factory() as db:
        paul = db.scalar(select(User).where(User.username == "paul"))
        assert paul is not None
        assert paul.display_name == "Paul Updated"
        assert paul.email == "paul@example.com"
        assert paul.status == UserStatus.DISABLED.value
        assert UserService().primary_role_name(paul) == BuiltinRole.VIEWER.value


def test_unauthenticated_api_returns_401(auth_client):
    auth_client.post(
        "/setup",
        data={
            "display_name": "Admin",
            "username": "admin",
            "password": "AdminPass1",
            "password_confirm": "AdminPass1",
        },
        follow_redirects=False,
    )
    auth_client.get("/logout", follow_redirects=False)
    response = auth_client.get("/api/projects", follow_redirects=False)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_health_remains_public(auth_client):
    response = auth_client.get("/api/health")
    assert response.status_code == 200


def test_session_aware_provider_uses_request_identity():
    provider = SessionAwareUserProvider()
    set_request_identity(None)
    with pytest.raises(RuntimeError):
        provider.get_current_user()
    set_request_identity(UserIdentity(user_name="session.user", machine_name="web"))
    assert provider.get_current_user().user_name == "session.user"
    set_request_identity(None)


@requires_git
def test_checkout_uses_static_provider_username(client, repo_parent, identity, data_dir):
    """Regression: checkout.user_name is the provider username, not OS getpass."""
    identity.become("session.alice", "TEST-PC")
    project = client.post("/api/projects", json={"name": "Auth Checkout"}).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt", b"payload", "application/octet-stream")},
        data={"comment": "init"},
    )
    assert created.status_code == 201, created.text
    obj = created.json()
    checked = client.post(f"/api/objects/{obj['uuid']}/checkout")
    assert checked.status_code == 200, checked.text
    assert checked.json()["checkout_user"] == "session.alice"

    ctx = client.app.state.ctx
    with ctx.session_factory() as db:
        eng = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == obj["uuid"]))
        assert eng is not None
        row = db.scalar(select(Checkout).where(Checkout.object_id == eng.id))
        assert row is not None
        assert row.user_name == "session.alice"


def _setup_admin_and_engineers(auth_client, auth_ctx, *usernames: str) -> None:
    auth_client.post(
        "/setup",
        data={
            "display_name": "Admin",
            "username": "admin",
            "password": "AdminPass1",
            "password_confirm": "AdminPass1",
        },
        follow_redirects=False,
    )
    for name in usernames:
        created = auth_client.post(
            "/admin/users/new",
            data={
                "display_name": name.title(),
                "username": name,
                "email": "",
                "role": BuiltinRole.ENGINEER.value,
                "status": UserStatus.ACTIVE.value,
                "password": f"{name.title()}Pass1",
                "password_confirm": f"{name.title()}Pass1",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303, created.text
    with auth_ctx.session_factory() as db:
        for name in usernames:
            user = db.scalar(select(User).where(User.username == name))
            assert user is not None
            user.must_change_password = False
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


@requires_git
def test_paul_checkout_blocks_david(auth_client, auth_ctx, repo_parent):
    """Session users: only the holder may own a checkout (Paul vs David)."""
    _setup_admin_and_engineers(auth_client, auth_ctx, "paul", "david")
    _login(auth_client, "paul", "PaulPass1")
    project = auth_client.post("/api/projects", json={"name": "Shared Part"}).json()
    created = auth_client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt", b"payload", "application/octet-stream")},
        data={"comment": "init"},
    )
    assert created.status_code == 201, created.text
    obj = created.json()
    checked = auth_client.post(f"/api/objects/{obj['uuid']}/checkout")
    assert checked.status_code == 200, checked.text
    assert checked.json()["checkout_user"] == "paul"

    _login(auth_client, "david", "DavidPass1")
    denied = auth_client.post(f"/api/objects/{obj['uuid']}/checkout")
    assert denied.status_code == 409, denied.text
    body = denied.json()["error"]
    assert body["code"] == "OBJECT_ALREADY_CHECKED_OUT"
    assert body["details"]["user"] == "paul"

    listed = auth_client.get(f"/api/objects/{obj['uuid']}")
    assert listed.json()["checkout_user"] == "paul"
    assert listed.json()["owned_by_me"] is False
