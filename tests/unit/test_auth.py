"""Unit tests for session auth, setup, login, and user admin."""

from __future__ import annotations

import re

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
    for table in ("users", "roles", "permissions", "user_roles", "role_permissions", "user_projects"):
        assert table in inspector.get_table_names()
    cols = {c["name"] for c in inspector.get_columns("users")}
    assert "access_all_projects" in cols
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
    # Keep another ACTIVE users.manage account so disabling admin is allowed.
    with auth_ctx.session_factory() as db:
        UserService().create_user(
            db,
            username="backup",
            display_name="Backup Admin",
            password="BackupPass1",
            role_name=BuiltinRole.ADMINISTRATOR.value,
            must_change_password=False,
        )
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
    assert "<h2><a href=\"/admin/users\">Users</a></h2>" in hub.text or ">Users</a>" in hub.text
    assert "Click a user’s name" in hub.text or "Click a user's name" in hub.text
    # Help copy is plain text, not wrapped in the section link.
    assert 'href="/admin/users">Add and edit' not in hub.text
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
        eng_role = auth_ctx.user_accounts.role_by_name(db, BuiltinRole.ENGINEER.value)
        assert eng_role is not None
        eng_role_uuid = eng_role.uuid

    listed = auth_client.get("/admin/users")
    assert listed.status_code == 200
    assert f'href="/admin/users/{paul_uuid}"' in listed.text
    assert f'href="/admin/roles/{eng_role_uuid}"' in listed.text
    assert "Click a name to edit" in listed.text
    assert "<th>Projects</th>" in listed.text
    assert ">All<" in listed.text or ">All</td>" in listed.text
    assert ">Edit</a>" not in listed.text

    role_page = auth_client.get(f"/admin/roles/{eng_role_uuid}")
    assert role_page.status_code == 200
    assert "Edit role" in role_page.text
    assert "Engineer" in role_page.text

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


@requires_git
def test_admin_user_project_access_filters_projects(auth_client, auth_ctx):
    """Admin form multi-select + restrict / empty / restore for one Engineer.

    Broader per-starter-role membership coverage lives in
    test_every_starter_role_login_permission_matrix.
    """
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
    alpha_resp = auth_client.post("/api/projects", json={"name": "Alpha"})
    beta_resp = auth_client.post("/api/projects", json={"name": "Beta"})
    assert alpha_resp.status_code == 201, alpha_resp.text
    assert beta_resp.status_code == 201, beta_resp.text
    alpha = alpha_resp.json()
    beta = beta_resp.json()

    form = auth_client.get("/admin/users/new")
    assert form.status_code == 200
    assert "Project access" in form.text
    assert 'id="access-all-projects"' in form.text
    assert 'name="project_uuid"' in form.text
    assert 'multiple' in form.text
    assert 'id="project-access-list"' in form.text
    assert "type=\"checkbox\" name=\"project_uuid\"" not in form.text
    # Soft-nav strips inline scripts; toggle must live in app.js (document-level).
    assert "getElementById(\"access-all-projects\")" not in form.text
    from pathlib import Path

    script = (
        Path(__file__).resolve().parents[2] / "src" / "creopdm" / "static" / "js" / "app.js"
    ).read_text(encoding="utf-8")
    assert "function syncProjectAccessUi" in script
    assert "__creopdmProjectAccessBound" in script
    assert 'id !== "access-all-projects"' in script
    assert "list.disabled = locked" in script
    assert "syncProjectAccessUi();" in script

    created = auth_client.post(
        "/admin/users/new",
        data={
            "display_name": "Limited",
            "username": "limited",
            "email": "",
            "role": BuiltinRole.ENGINEER.value,
            "status": UserStatus.ACTIVE.value,
            "password": "Limited1!",
            "password_confirm": "Limited1!",
            "project_access_present": "1",
            "project_uuid": [alpha["uuid"]],
        },
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text

    with auth_ctx.session_factory() as db:
        user = db.scalar(select(User).where(User.username == "limited"))
        assert user is not None
        assert user.access_all_projects is False
        assert {p.uuid for p in user.projects} == {alpha["uuid"]}
        user.must_change_password = False
        user_uuid = user.uuid
        db.commit()

    _login(auth_client, "limited", "Limited1!")
    listed = auth_client.get("/api/projects")
    assert listed.status_code == 200
    assert [p["uuid"] for p in listed.json()] == [alpha["uuid"]]
    assert auth_client.get(f"/api/projects/{alpha['uuid']}").status_code == 200
    denied = auth_client.get(f"/api/projects/{beta['uuid']}")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN"
    home = auth_client.get("/")
    assert home.status_code == 200
    assert "Alpha" in home.text
    assert "Beta" not in home.text

    _login(auth_client, "admin", "AdminPass1")
    users_list = auth_client.get("/admin/users")
    assert users_list.status_code == 200
    assert "<th>Projects</th>" in users_list.text
    assert "All" in users_list.text
    assert re.search(
        r'<td>limited</td>\s*<td>\s*<a href="/admin/roles/[^"]+">Engineer</a>\s*</td>\s*<td>ACTIVE</td>\s*<td>1</td>',
        users_list.text,
    ), users_list.text

    cleared = auth_client.post(
        f"/admin/users/{user_uuid}",
        data={
            "display_name": "Limited",
            "email": "",
            "role": BuiltinRole.ENGINEER.value,
            "status": UserStatus.ACTIVE.value,
            "password": "",
            "password_confirm": "",
            "project_access_present": "1",
            # All projects off, no project_uuid → cannot browse
        },
        follow_redirects=False,
    )
    assert cleared.status_code == 303, cleared.text

    _login(auth_client, "limited", "Limited1!")
    empty = auth_client.get("/api/projects")
    assert empty.status_code == 200
    assert empty.json() == []
    assert auth_client.get(f"/api/projects/{alpha['uuid']}").status_code == 403

    _login(auth_client, "admin", "AdminPass1")
    restored = auth_client.post(
        f"/admin/users/{user_uuid}",
        data={
            "display_name": "Limited",
            "email": "",
            "role": BuiltinRole.ENGINEER.value,
            "status": UserStatus.ACTIVE.value,
            "password": "",
            "password_confirm": "",
            "project_access_present": "1",
            "access_all_projects": "1",
        },
        follow_redirects=False,
    )
    assert restored.status_code == 303, restored.text
    _login(auth_client, "limited", "Limited1!")
    all_projects = auth_client.get("/api/projects")
    assert all_projects.status_code == 200
    uuids = {p["uuid"] for p in all_projects.json()}
    assert alpha["uuid"] in uuids and beta["uuid"] in uuids


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


def _setup_admin_and_users(
    auth_client, auth_ctx, *users: tuple[str, str]
) -> None:
    """Create admin via setup, then users as (username, role_name). Passwords: {Name}Pass1."""
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
    for name, role in users:
        created = auth_client.post(
            "/admin/users/new",
            data={
                "display_name": name.title(),
                "username": name,
                "email": "",
                "role": role,
                "status": UserStatus.ACTIVE.value,
                "password": f"{name.title()}Pass1",
                "password_confirm": f"{name.title()}Pass1",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303, created.text
    with auth_ctx.session_factory() as db:
        for name, _role in users:
            user = db.scalar(select(User).where(User.username == name))
            assert user is not None
            user.must_change_password = False
        db.commit()
    auth_client.get("/logout", follow_redirects=False)


def _setup_admin_and_engineers(auth_client, auth_ctx, *usernames: str) -> None:
    _setup_admin_and_users(
        auth_client,
        auth_ctx,
        *((name, BuiltinRole.ENGINEER.value) for name in usernames),
    )


def _login(auth_client, username: str, password: str) -> None:
    auth_client.get("/logout", follow_redirects=False)
    ok = auth_client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert ok.status_code == 303, ok.text


def _assert_forbidden(response) -> None:
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "FORBIDDEN"


@requires_git
def test_paul_checkout_blocks_david(auth_client, auth_ctx, repo_parent):
    """Session users: only the holder may own a checkout (Paul vs David)."""
    _setup_admin_and_engineers(auth_client, auth_ctx, "paul", "david")
    _login(auth_client, "admin", "AdminPass1")
    created_project = auth_client.post("/api/projects", json={"name": "Shared Part"})
    assert created_project.status_code == 201, created_project.text
    project = created_project.json()

    _login(auth_client, "paul", "PaulPass1")
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


@requires_git
def test_viewer_is_read_only(auth_client, auth_ctx, repo_parent):
    """Viewer may browse; mutations and authoring toolbar are forbidden."""
    _setup_admin_and_users(
        auth_client, auth_ctx, ("view", BuiltinRole.VIEWER.value)
    )
    _login(auth_client, "admin", "AdminPass1")
    project = auth_client.post("/api/projects", json={"name": "View Only"}).json()
    created = auth_client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("part.prt", b"payload", "application/octet-stream")},
        data={"comment": "init"},
    )
    assert created.status_code == 201, created.text
    obj = created.json()

    _login(auth_client, "view", "ViewPass1")
    assert auth_client.get(f"/api/projects/{project['uuid']}").status_code == 200
    assert auth_client.get(f"/api/objects/{obj['uuid']}").status_code == 200
    home = auth_client.get(f"/?project={project['uuid']}")
    assert home.status_code == 200
    assert 'data-can-checkout="0"' in home.text
    assert 'data-can-view="1"' in home.text
    assert 'data-can-copy-to-vault="0"' in home.text
    assert 'id="workspace-btn"' not in home.text
    assert 'id="add-menu"' not in home.text
    assert 'id="checkout-menu"' not in home.text
    assert 'id="checkin-menu"' not in home.text
    assert 'id="remove-menu"' not in home.text
    assert 'id="new-project-btn"' not in home.text
    assert "Administration" not in home.text
    assert auth_client.get("/admin/roles", follow_redirects=False).status_code == 403

    _assert_forbidden(auth_client.post("/api/projects", json={"name": "Nope"}))
    _assert_forbidden(
        auth_client.post(
            f"/api/projects/{project['uuid']}/objects",
            files={"file": ("other.prt", b"x", "application/octet-stream")},
            data={"comment": "nope"},
        )
    )
    _assert_forbidden(auth_client.post(f"/api/objects/{obj['uuid']}/checkout"))
    _assert_forbidden(
        auth_client.post(
            "/api/objects/batch/workspace",
            json={"object_ids": [obj["uuid"]]},
        )
    )


@requires_git
def test_engineer_can_author_not_manage_projects(auth_client, auth_ctx, repo_parent):
    """Engineer may add/checkout; cannot create/delete projects or open Administration."""
    _setup_admin_and_users(
        auth_client, auth_ctx, ("eng", BuiltinRole.ENGINEER.value)
    )
    _login(auth_client, "admin", "AdminPass1")
    project = auth_client.post("/api/projects", json={"name": "Eng Project"}).json()

    _login(auth_client, "eng", "EngPass1")
    home = auth_client.get(f"/?project={project['uuid']}")
    assert home.status_code == 200
    assert 'id="add-menu"' in home.text
    assert 'id="checkout-menu"' in home.text
    assert 'id="new-project-btn"' not in home.text
    assert "Administration" not in home.text
    assert auth_client.get("/admin", follow_redirects=False).status_code == 403

    _assert_forbidden(auth_client.post("/api/projects", json={"name": "Nope"}))
    _assert_forbidden(auth_client.delete(f"/api/projects/{project['uuid']}"))

    created = auth_client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt", b"payload", "application/octet-stream")},
        data={"comment": "init"},
    )
    assert created.status_code == 201, created.text
    checked = auth_client.post(f"/api/objects/{created.json()['uuid']}/checkout")
    assert checked.status_code == 200, checked.text


@requires_git
def test_pdm_manager_can_create_not_delete_or_admin(auth_client, auth_ctx, repo_parent):
    """PDM Manager may create projects; cannot delete or manage users/settings."""
    _setup_admin_and_users(
        auth_client, auth_ctx, ("pdm", BuiltinRole.PDM_MANAGER.value)
    )
    _login(auth_client, "pdm", "PdmPass1")
    created = auth_client.post("/api/projects", json={"name": "PDM Project"})
    assert created.status_code == 201, created.text
    project = created.json()
    home = auth_client.get(f"/?project={project['uuid']}")
    assert home.status_code == 200
    assert 'id="new-project-btn"' in home.text
    assert 'id="delete-project-btn"' not in home.text
    assert "Administration" not in home.text

    _assert_forbidden(auth_client.delete(f"/api/projects/{project['uuid']}"))
    assert auth_client.get("/admin", follow_redirects=False).status_code == 403
    assert auth_client.get("/admin/users", follow_redirects=False).status_code == 403
    assert auth_client.get("/settings", follow_redirects=False).status_code == 403
    _assert_forbidden(auth_client.get("/api/settings"))


@requires_git
def test_admin_can_create_and_delete_project(auth_client, auth_ctx, repo_parent):
    """Administrator retains full project create/delete."""
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
    created = auth_client.post("/api/projects", json={"name": "Admin Project"})
    assert created.status_code == 201, created.text
    project_id = created.json()["uuid"]
    home = auth_client.get(f"/?project={project_id}")
    assert home.status_code == 200
    assert 'id="new-project-btn"' in home.text
    assert 'id="delete-project-btn"' in home.text
    deleted = auth_client.delete(f"/api/projects/{project_id}")
    assert deleted.status_code == 204, deleted.text


def test_builtin_role_permission_matrix_seeded(auth_ctx):
    """Migration/startup seed grants matrix keys (Viewer none; Engineer authoring)."""
    from creopdm.auth_constants import (
        PERMISSION_OBJECTS_CHECKOUT,
        PERMISSION_OBJECTS_COPY_TO_VAULT,
        PERMISSION_OBJECTS_VIEW,
        PERMISSION_PROJECTS_CREATE,
        PERMISSION_PROJECTS_DELETE,
        PERMISSION_ROLES_MANAGE,
        PERMISSION_USERS_MANAGE,
        STARTER_ROLE_PERMISSION_KEYS,
    )
    from creopdm.models.user import Permission, RolePermission

    with auth_ctx.session_factory() as db:
        auth_ctx.user_accounts.ensure_builtin_roles(db)
        db.commit()
        keys_by_role: dict[str, set[str]] = {}
        for role in db.scalars(select(Role)).all():
            perm_ids = {
                link.permission_id
                for link in db.scalars(
                    select(RolePermission).where(RolePermission.role_id == role.id)
                ).all()
            }
            keys_by_role[role.name] = {
                p.key
                for p in db.scalars(select(Permission)).all()
                if p.id in perm_ids
            }
    assert keys_by_role[BuiltinRole.VIEWER.value] == {PERMISSION_OBJECTS_VIEW}
    assert PERMISSION_OBJECTS_VIEW in keys_by_role[BuiltinRole.ENGINEER.value]
    assert PERMISSION_OBJECTS_CHECKOUT in keys_by_role[BuiltinRole.ENGINEER.value]
    assert PERMISSION_OBJECTS_COPY_TO_VAULT not in keys_by_role[BuiltinRole.ENGINEER.value]
    assert PERMISSION_PROJECTS_CREATE not in keys_by_role[BuiltinRole.ENGINEER.value]
    assert PERMISSION_PROJECTS_CREATE in keys_by_role[BuiltinRole.PDM_MANAGER.value]
    assert PERMISSION_OBJECTS_COPY_TO_VAULT in keys_by_role[BuiltinRole.PDM_MANAGER.value]
    assert PERMISSION_PROJECTS_DELETE not in keys_by_role[BuiltinRole.PDM_MANAGER.value]
    assert PERMISSION_USERS_MANAGE in keys_by_role[BuiltinRole.ADMINISTRATOR.value]
    assert PERMISSION_ROLES_MANAGE in keys_by_role[BuiltinRole.ADMINISTRATOR.value]
    assert PERMISSION_OBJECTS_COPY_TO_VAULT in keys_by_role[BuiltinRole.ADMINISTRATOR.value]
    for role_name, expected in STARTER_ROLE_PERMISSION_KEYS.items():
        assert keys_by_role[role_name] >= set(expected)


@requires_git
def test_roles_admin_create_custom_and_gate(auth_client, auth_ctx, repo_parent):
    """roles.manage can create a custom role; caps follow DB only."""
    from creopdm.auth_constants import PERMISSION_OBJECTS_CHECKOUT, PERMISSION_OBJECTS_VIEW

    _setup_admin_and_users(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    hub = auth_client.get("/admin")
    assert hub.status_code == 200
    assert 'href="/admin/roles"' in hub.text
    listed = auth_client.get("/admin/roles")
    assert listed.status_code == 200
    assert "Administrator" in listed.text

    created = auth_client.post(
        "/admin/roles/new",
        data={
            "name": "Checkout Only",
            "description": "Can view and lock files",
            "permission": [PERMISSION_OBJECTS_VIEW, PERMISSION_OBJECTS_CHECKOUT],
        },
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text

    user = auth_client.post(
        "/admin/users/new",
        data={
            "display_name": "Lock User",
            "username": "locker",
            "email": "",
            "role": "Checkout Only",
            "status": UserStatus.ACTIVE.value,
            "password": "LockerPass1",
            "password_confirm": "LockerPass1",
        },
        follow_redirects=False,
    )
    assert user.status_code == 303, user.text
    with auth_ctx.session_factory() as db:
        row = db.scalar(select(User).where(User.username == "locker"))
        assert row is not None
        row.must_change_password = False
        db.commit()

    project = auth_client.post("/api/projects", json={"name": "Lock Proj"}).json()
    part = auth_client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("a.prt", b"x", "application/octet-stream")},
        data={"comment": "init"},
    )
    assert part.status_code == 201, part.text

    _login(auth_client, "locker", "LockerPass1")
    home = auth_client.get(f"/?project={project['uuid']}")
    assert home.status_code == 200
    assert 'data-can-view="1"' in home.text
    assert 'data-can-checkout="1"' in home.text
    assert 'id="new-project-btn"' not in home.text
    assert auth_client.get("/admin/roles", follow_redirects=False).status_code == 403
    checked = auth_client.post(f"/api/objects/{part.json()['uuid']}/checkout")
    assert checked.status_code == 200, checked.text
    _assert_forbidden(auth_client.post("/api/projects", json={"name": "Nope"}))


@requires_git
def test_role_with_no_permissions_cannot_browse(auth_client, auth_ctx, repo_parent):
    """A signed-in user with zero permissions must not browse projects or files."""
    _setup_admin_and_users(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    created = auth_client.post(
        "/admin/roles/new",
        data={"name": "Empty Role", "description": "No caps"},
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    user = auth_client.post(
        "/admin/users/new",
        data={
            "display_name": "Nobody",
            "username": "nobody",
            "email": "",
            "role": "Empty Role",
            "status": UserStatus.ACTIVE.value,
            "password": "NobodyPass1",
            "password_confirm": "NobodyPass1",
        },
        follow_redirects=False,
    )
    assert user.status_code == 303, user.text
    with auth_ctx.session_factory() as db:
        row = db.scalar(select(User).where(User.username == "nobody"))
        assert row is not None
        row.must_change_password = False
        db.commit()
    project = auth_client.post("/api/projects", json={"name": "Hidden"}).json()

    login = auth_client.post(
        "/login",
        data={"username": "nobody", "password": "NobodyPass1"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/no-access"

    page = auth_client.get("/no-access")
    assert page.status_code == 200
    assert "No Files access" in page.text
    assert "objects.view" in page.text

    home = auth_client.get("/", follow_redirects=False)
    assert home.status_code == 303
    assert home.headers["location"] == "/no-access"
    _assert_forbidden(auth_client.get("/api/projects"))
    _assert_forbidden(auth_client.get(f"/api/projects/{project['uuid']}"))
    assert auth_client.get("/admin", follow_redirects=False).status_code == 403


@requires_git
def test_admin_without_objects_view_lands_on_administration(auth_client, auth_ctx):
    """Admin/settings-only role (no objects.view) signs in to /admin, not a JSON error."""
    from creopdm.auth_constants import (
        PERMISSION_PROJECTS_CREATE,
        PERMISSION_PROJECTS_DELETE,
        PERMISSION_PROJECTS_EDIT,
        PERMISSION_ROLES_MANAGE,
        PERMISSION_SETTINGS_MANAGE,
        PERMISSION_USERS_MANAGE,
    )

    _setup_admin_and_users(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    role = auth_client.post(
        "/admin/roles/new",
        data={
            "name": "Admin Desk",
            "description": "Users/roles/settings/projects only",
            "permission": [
                PERMISSION_USERS_MANAGE,
                PERMISSION_ROLES_MANAGE,
                PERMISSION_SETTINGS_MANAGE,
                PERMISSION_PROJECTS_CREATE,
                PERMISSION_PROJECTS_EDIT,
                PERMISSION_PROJECTS_DELETE,
            ],
        },
        follow_redirects=False,
    )
    assert role.status_code == 303, role.text
    created = auth_client.post(
        "/admin/users/new",
        data={
            "display_name": "Desk Admin",
            "username": "desk",
            "email": "",
            "role": "Admin Desk",
            "status": UserStatus.ACTIVE.value,
            "password": "DeskPass1!",
            "password_confirm": "DeskPass1!",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    with auth_ctx.session_factory() as db:
        row = db.scalar(select(User).where(User.username == "desk"))
        assert row is not None
        row.must_change_password = False
        db.commit()

    login = auth_client.post(
        "/login",
        data={"username": "desk", "password": "DeskPass1!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/admin"

    hub = auth_client.get("/admin")
    assert hub.status_code == 200
    assert "Administration" in hub.text
    assert 'href="/">Projects</a>' not in hub.text
    assert "No Files access" not in hub.text
    assert '"error"' not in hub.text or "FORBIDDEN" not in hub.text

    home = auth_client.get("/", follow_redirects=False)
    assert home.status_code == 303
    assert home.headers["location"] == "/admin"

    users = auth_client.get("/admin/users")
    assert users.status_code == 200
    assert 'href="/">Projects</a>' not in users.text
    assert 'href="/admin">Administration</a>' in users.text


@requires_git
def test_role_permission_edit_survives_restart(auth_client, auth_ctx, data_dir, repo_parent):
    """Removing objects.checkout from Engineer is not re-seeded on rebuild."""
    from creopdm.auth_constants import PERMISSION_OBJECTS_CHECKOUT
    from creopdm.config import ConfigManager

    _setup_admin_and_users(
        auth_client, auth_ctx, ("eng", BuiltinRole.ENGINEER.value)
    )
    with auth_ctx.session_factory() as db:
        eng = auth_ctx.user_accounts.role_by_name(db, BuiltinRole.ENGINEER.value)
        assert eng is not None
        keys = [p.key for p in eng.permissions if p.key != PERMISSION_OBJECTS_CHECKOUT]
        auth_ctx.user_accounts.update_role(
            db, eng.uuid, permission_keys=keys
        )
        db.commit()

    rebuilt = build_context(ConfigManager())
    with rebuilt.session_factory() as db:
        eng = rebuilt.user_accounts.role_by_name(db, BuiltinRole.ENGINEER.value)
        assert eng is not None
        assert PERMISSION_OBJECTS_CHECKOUT not in {p.key for p in eng.permissions}

    with TestClient(create_app(rebuilt)) as client:
        _login(client, "eng", "EngPass1")
        home = client.get("/")
        assert home.status_code == 200
        assert 'data-can-checkout="0"' in home.text
        assert 'id="checkout-menu"' not in home.text


def test_cannot_strip_last_users_manage(auth_client, auth_ctx):
    """Saving Admin without users.manage is rejected when it is the only path."""
    from creopdm.auth_constants import PERMISSION_OBJECTS_CHECKOUT

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
    with auth_ctx.session_factory() as db:
        admin_role = auth_ctx.user_accounts.role_by_name(
            db, BuiltinRole.ADMINISTRATOR.value
        )
        assert admin_role is not None
        role_uuid = admin_role.uuid
    denied = auth_client.post(
        f"/admin/roles/{role_uuid}",
        data={
            "name": "Administrator",
            "description": "oops",
            "permission": PERMISSION_OBJECTS_CHECKOUT,
        },
        follow_redirects=False,
    )
    assert denied.status_code == 400, denied.text
    assert "users.manage" in denied.text


def test_engineer_cannot_open_roles_admin(auth_client, auth_ctx):
    _setup_admin_and_users(
        auth_client, auth_ctx, ("eng", BuiltinRole.ENGINEER.value)
    )
    _login(auth_client, "eng", "EngPass1")
    assert auth_client.get("/admin/roles", follow_redirects=False).status_code == 403
    assert auth_client.get("/admin/roles/new", follow_redirects=False).status_code == 403


@requires_git
def test_agent_bearer_can_download_content(auth_client, auth_ctx, repo_parent):
    """creopdm-agent Bearer (minted for the signed-in user) unlocks /content."""
    import re

    from creopdm.auth_session import mint_agent_token

    _setup_admin_and_users(
        auth_client, auth_ctx, ("view", BuiltinRole.VIEWER.value)
    )
    _login(auth_client, "admin", "AdminPass1")
    project = auth_client.post("/api/projects", json={"name": "Agent Open"}).json()
    created = auth_client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("part.prt", b"vault-bytes", "application/octet-stream")},
        data={"comment": "init"},
    )
    assert created.status_code == 201, created.text
    obj_id = created.json()["uuid"]

    _login(auth_client, "view", "ViewPass1")
    home = auth_client.get("/")
    assert home.status_code == 200
    match = re.search(r'data-agent-token="([^"]*)"', home.text)
    assert match and match.group(1), "signed-in page must expose agent Bearer"

    auth_client.get("/logout", follow_redirects=False)
    bare = auth_client.get(f"/api/objects/{obj_id}/content")
    assert bare.status_code == 401

    with auth_ctx.session_factory() as db:
        user = db.scalar(select(User).where(User.username == "view"))
        assert user is not None
        secret = auth_client.app.state.session_secret
        token = mint_agent_token(user.uuid, secret)

    ok = auth_client.get(
        f"/api/objects/{obj_id}/content",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.content == b"vault-bytes"


def _assert_permission_gate(response, *, allowed: bool, label: str) -> None:
    """Permission gates return 403; allowed probes may succeed or fail for other reasons."""
    if allowed:
        assert response.status_code != 403, (
            f"{label}: expected allow (not 403), got {response.status_code}: {response.text[:300]}"
        )
        return
    assert response.status_code == 403, (
        f"{label}: expected 403, got {response.status_code}: {response.text[:300]}"
    )
    # API JSON bodies carry FORBIDDEN; HTML admin pages are plain 403 markup.
    ctype = (response.headers.get("content-type") or "").lower()
    if "json" in ctype:
        assert response.json()["error"]["code"] == "FORBIDDEN"


@requires_git
def test_every_starter_role_login_permission_matrix(auth_client, auth_ctx, repo_parent):
    """Create one user per starter role; each logs in; assert every permission allow/deny.

    Ephemeral DB (data_dir fixture) — users do not persist after the test.
    Driven by STARTER_ROLE_PERMISSION_KEYS so seed drift fails this test.

    Also asserts per-user project membership (All / selected / none) for each
    starter account — orthogonal to role permission keys.
    """
    from uuid import uuid4

    from creopdm.auth_constants import (
        BUILTIN_PERMISSIONS,
        PERMISSION_OBJECTS_ADD,
        PERMISSION_OBJECTS_CHECKIN,
        PERMISSION_OBJECTS_CHECKOUT,
        PERMISSION_OBJECTS_COPY_TO_VAULT,
        PERMISSION_OBJECTS_METADATA,
        PERMISSION_OBJECTS_REMOVE,
        PERMISSION_OBJECTS_REVERT,
        PERMISSION_OBJECTS_VIEW,
        PERMISSION_PROJECTS_CREATE,
        PERMISSION_PROJECTS_DELETE,
        PERMISSION_PROJECTS_EDIT,
        PERMISSION_ROLES_MANAGE,
        PERMISSION_SETTINGS_MANAGE,
        PERMISSION_USERS_MANAGE,
        STARTER_ROLE_PERMISSION_KEYS,
    )

    # One account per starter role (admin from /setup; others via Users admin).
    role_accounts = [
        ("admin", BuiltinRole.ADMINISTRATOR.value, "AdminPass1"),
        ("pdm", BuiltinRole.PDM_MANAGER.value, "PdmPass1"),
        ("eng", BuiltinRole.ENGINEER.value, "EngPass1"),
        ("view", BuiltinRole.VIEWER.value, "ViewPass1"),
    ]
    assert {role for _, role, _ in role_accounts} == set(STARTER_ROLE_PERMISSION_KEYS)

    _setup_admin_and_users(
        auth_client,
        auth_ctx,
        ("pdm", BuiltinRole.PDM_MANAGER.value),
        ("eng", BuiltinRole.ENGINEER.value),
        ("view", BuiltinRole.VIEWER.value),
    )

    # Shared fixtures created as admin (always allowed).
    _login(auth_client, "admin", "AdminPass1")
    form = auth_client.get("/admin/users/new")
    assert form.status_code == 200
    assert "Project access" in form.text
    assert 'id="access-all-projects"' in form.text

    project = auth_client.post("/api/projects", json={"name": "Role Matrix"}).json()
    project_id = project["uuid"]
    other = auth_client.post("/api/projects", json={"name": "Other Matrix"})
    assert other.status_code == 201, other.text
    other_id = other.json()["uuid"]
    # Multi-select options appear once projects exist.
    form_with_projects = auth_client.get("/admin/users/new")
    assert form_with_projects.status_code == 200
    assert 'multiple' in form_with_projects.text
    assert 'name="project_uuid"' in form_with_projects.text
    assert 'id="project-access-list"' in form_with_projects.text
    created = auth_client.post(
        f"/api/projects/{project_id}/objects",
        files={"file": ("matrix.prt", b"matrix-bytes", "application/octet-stream")},
        data={"comment": "seed"},
    )
    assert created.status_code == 201, created.text
    object_id = created.json()["uuid"]
    # Disposable project for delete probes (recreated when consumed).
    disposable = auth_client.post(
        "/api/projects", json={"name": f"Disposable-{uuid4().hex[:8]}"}
    )
    assert disposable.status_code == 201, disposable.text
    disposable_id = disposable.json()["uuid"]

    all_perm_keys = tuple(key for key, _ in BUILTIN_PERMISSIONS)

    for username, role_name, password in role_accounts:
        allowed = set(STARTER_ROLE_PERMISSION_KEYS[role_name])
        _login(auth_client, username, password)

        # Browse requires objects.view.
        assert auth_client.get(f"/api/projects/{project_id}").status_code == (
            200 if PERMISSION_OBJECTS_VIEW in allowed else 403
        )
        if PERMISSION_OBJECTS_VIEW in allowed:
            assert auth_client.get(f"/api/objects/{object_id}").status_code == 200
            home = auth_client.get(f"/?project={project_id}")
            assert home.status_code == 200
            assert f'data-can-checkout="{"1" if PERMISSION_OBJECTS_CHECKOUT in allowed else "0"}"' in home.text
            assert f'data-can-view="1"' in home.text
            assert f'data-can-copy-to-vault="{"1" if PERMISSION_OBJECTS_COPY_TO_VAULT in allowed else "0"}"' in home.text
            if PERMISSION_OBJECTS_COPY_TO_VAULT in allowed:
                assert 'id="workspace-btn"' in home.text
            else:
                assert 'id="workspace-btn"' not in home.text
            if PERMISSION_OBJECTS_ADD in allowed:
                assert 'id="add-menu"' in home.text
            else:
                assert 'id="add-menu"' not in home.text
            if PERMISSION_PROJECTS_CREATE in allowed:
                assert 'id="new-project-btn"' in home.text
            else:
                assert 'id="new-project-btn"' not in home.text
            if PERMISSION_USERS_MANAGE in allowed or PERMISSION_ROLES_MANAGE in allowed or PERMISSION_SETTINGS_MANAGE in allowed:
                assert "Administration" in home.text
            else:
                assert "Administration" not in home.text
            # Default All projects: both fixtures visible.
            listed_all = auth_client.get("/api/projects")
            assert listed_all.status_code == 200
            listed_uuids = {p["uuid"] for p in listed_all.json()}
            assert project_id in listed_uuids and other_id in listed_uuids, (
                f"{role_name}/{username}: default All projects must include both fixtures"
            )
        else:
            _assert_forbidden(auth_client.get(f"/api/objects/{object_id}"))
            _assert_forbidden(auth_client.get(f"/?project={project_id}"))

        probes: dict[str, object] = {
            PERMISSION_USERS_MANAGE: auth_client.get("/admin/users", follow_redirects=False),
            PERMISSION_ROLES_MANAGE: auth_client.get("/admin/roles", follow_redirects=False),
            PERMISSION_SETTINGS_MANAGE: auth_client.get("/api/settings", follow_redirects=False),
            PERMISSION_OBJECTS_VIEW: auth_client.get(f"/api/projects/{project_id}"),
            PERMISSION_PROJECTS_CREATE: auth_client.post(
                "/api/projects",
                json={"name": f"Create-{username}-{uuid4().hex[:6]}"},
            ),
            PERMISSION_PROJECTS_EDIT: auth_client.patch(
                f"/api/projects/{project_id}",
                json={
                    "name": "Role Matrix",
                    "description": f"edited-by-{username}",
                },
            ),
            PERMISSION_OBJECTS_ADD: auth_client.post(
                f"/api/projects/{project_id}/objects",
                files={
                    "file": (
                        f"add-{username}.prt",
                        b"add-bytes",
                        "application/octet-stream",
                    )
                },
                data={"comment": "add probe"},
            ),
            PERMISSION_OBJECTS_CHECKOUT: auth_client.post(
                f"/api/objects/{object_id}/checkout"
            ),
            PERMISSION_OBJECTS_CHECKIN: auth_client.post(
                f"/api/objects/{object_id}/checkin",
                json={"comment": "checkin probe"},
            ),
            PERMISSION_OBJECTS_REMOVE: auth_client.post(
                "/api/objects/batch/remove",
                json={"object_ids": ["00000000-0000-0000-0000-000000000000"]},
            ),
            PERMISSION_OBJECTS_REVERT: auth_client.post(
                f"/api/objects/{object_id}/versions/{uuid4()}/revert"
            ),
            PERMISSION_OBJECTS_METADATA: auth_client.post(
                f"/api/objects/{object_id}/creo-metadata",
                json={},
            ),
            PERMISSION_OBJECTS_COPY_TO_VAULT: auth_client.post(
                "/api/objects/batch/workspace",
                json={"object_ids": ["00000000-0000-0000-0000-000000000000"]},
            ),
        }

        # Delete: try disposable when allowed; otherwise attempt delete on shared
        # project (must 403 without destroying fixtures).
        if PERMISSION_PROJECTS_DELETE in allowed:
            delete_resp = auth_client.delete(f"/api/projects/{disposable_id}")
            probes[PERMISSION_PROJECTS_DELETE] = delete_resp
            # Recreate disposable for the next role that can delete.
            _login(auth_client, "admin", "AdminPass1")
            again = auth_client.post(
                "/api/projects", json={"name": f"Disposable-{uuid4().hex[:8]}"}
            )
            assert again.status_code == 201, again.text
            disposable_id = again.json()["uuid"]
            _login(auth_client, username, password)
        else:
            probes[PERMISSION_PROJECTS_DELETE] = auth_client.delete(
                f"/api/projects/{project_id}"
            )

        assert set(probes) == set(all_perm_keys), (
            f"{role_name}: probe set must cover every built-in permission"
        )

        for key in all_perm_keys:
            _assert_permission_gate(
                probes[key],
                allowed=key in allowed,
                label=f"{role_name}/{username} {key}",
            )

        # Leave shared object Available for the next account's checkout probe.
        state = auth_client.get(f"/api/objects/{object_id}")
        if state.status_code == 200 and state.json().get("owned_by_me"):
            undone = auth_client.post(f"/api/objects/{object_id}/undo-checkout")
            assert undone.status_code == 200, undone.text

        # Project membership (per user, not per role permission key).
        with auth_ctx.session_factory() as db:
            row = db.scalar(select(User).where(User.username == username))
            assert row is not None
            user_uuid = row.uuid
            display_name = row.display_name
            assert row.access_all_projects is True

        _login(auth_client, "admin", "AdminPass1")
        restricted = auth_client.post(
            f"/admin/users/{user_uuid}",
            data={
                "display_name": display_name,
                "email": "",
                "role": role_name,
                "status": UserStatus.ACTIVE.value,
                "password": "",
                "password_confirm": "",
                "project_access_present": "1",
                "project_uuid": [project_id],
            },
            follow_redirects=False,
        )
        assert restricted.status_code == 303, restricted.text

        _login(auth_client, username, password)
        if PERMISSION_OBJECTS_VIEW in allowed:
            only = auth_client.get("/api/projects")
            assert only.status_code == 200, only.text
            assert {p["uuid"] for p in only.json()} == {project_id}, (
                f"{role_name}/{username}: restricted membership must show only Role Matrix"
            )
            assert auth_client.get(f"/api/projects/{project_id}").status_code == 200
            denied_other = auth_client.get(f"/api/projects/{other_id}")
            assert denied_other.status_code == 403, denied_other.text
            assert denied_other.json()["error"]["code"] == "FORBIDDEN"

        _login(auth_client, "admin", "AdminPass1")
        cleared = auth_client.post(
            f"/admin/users/{user_uuid}",
            data={
                "display_name": display_name,
                "email": "",
                "role": role_name,
                "status": UserStatus.ACTIVE.value,
                "password": "",
                "password_confirm": "",
                "project_access_present": "1",
            },
            follow_redirects=False,
        )
        assert cleared.status_code == 303, cleared.text

        _login(auth_client, username, password)
        if PERMISSION_OBJECTS_VIEW in allowed:
            empty = auth_client.get("/api/projects")
            assert empty.status_code == 200
            assert empty.json() == [], (
                f"{role_name}/{username}: no selected projects → empty list"
            )
            assert auth_client.get(f"/api/projects/{project_id}").status_code == 403

        # Restore All projects so later roles still share fixtures (and admin stays usable).
        _login(auth_client, "admin", "AdminPass1")
        restored = auth_client.post(
            f"/admin/users/{user_uuid}",
            data={
                "display_name": display_name,
                "email": "",
                "role": role_name,
                "status": UserStatus.ACTIVE.value,
                "password": "",
                "password_confirm": "",
                "project_access_present": "1",
                "access_all_projects": "1",
            },
            follow_redirects=False,
        )
        assert restored.status_code == 303, restored.text
        if username == "admin":
            _login(auth_client, "admin", "AdminPass1")
            assert auth_client.get("/admin/users").status_code == 200
