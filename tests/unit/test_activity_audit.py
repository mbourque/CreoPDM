"""Utilities Audit log — ActivityService filters, writers, redaction."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, select

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.constants import ActivityAction
from creopdm.models.activity import Activity
from creopdm.services.activity_service import ActivityService, redact_audit_details
from creopdm.utils.identity import StaticUserProvider, UserIdentity
from fastapi.testclient import TestClient
from tests.conftest import requires_git


@pytest.fixture()
def ctx(data_dir):
    return build_context(ConfigManager(), users=StaticUserProvider("Alice", "ENG-PC-17"))


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def test_activity_model_has_audit_columns(ctx):
    cols = {c["name"] for c in inspect(ctx.engine).get_columns("activities")}
    assert {"uuid", "user_uuid", "comment", "action", "timestamp", "details_json"} <= cols


def test_client_ip_from_request_prefers_forwarded_for():
    from creopdm.utils.identity import client_ip_from_request, client_label_from_request

    class _Hdrs(dict):
        def get(self, key, default=None):
            return super().get(key.lower(), default)

    class _Req:
        def __init__(self, forwarded=None, host=None):
            self.headers = _Hdrs()
            if forwarded:
                self.headers["x-forwarded-for"] = forwarded
            self.client = type("C", (), {"host": host})() if host else None

    assert client_ip_from_request(_Req(forwarded="10.1.2.3, 10.0.0.1", host="127.0.0.1")) == "10.1.2.3"
    assert client_ip_from_request(_Req(host="192.168.1.9")) == "192.168.1.9"
    assert client_label_from_request(_Req()) == "unknown"


def test_redact_audit_details_masks_password_fields():
    raw = {
        "smtp_password": "super-secret",
        "password": "also-secret",
        "enabled": True,
        "nested": {"api_token": "tok", "host": "mail.example"},
    }
    safe = redact_audit_details(raw)
    assert safe is not None
    assert safe["smtp_password"] == "[REDACTED]"
    assert safe["password"] == "[REDACTED]"
    assert safe["enabled"] is True
    assert safe["nested"]["api_token"] == "[REDACTED]"
    assert safe["nested"]["host"] == "mail.example"


def test_list_events_filters_action_user_and_object(ctx):
    svc = ActivityService()
    actor = UserIdentity("Alice", "ENG-PC-17", user_uuid="alice-uuid")
    other = UserIdentity("Bob", "ENG-PC-18", user_uuid="bob-uuid")
    with ctx.session_factory() as db:
        svc.record(
            db,
            ActivityAction.USER_CREATED,
            actor,
            details={"username": "pat"},
            comment="welcome",
        )
        svc.record(
            db,
            ActivityAction.CHECKED_IN,
            other,
            details={
                "filename": "bracket.prt",
                "iteration": 2,
                "previous_iteration": 1,
                "git_commit": "8fa24c1abcdef",
            },
            comment="fix hole",
        )
        svc.record(
            db,
            ActivityAction.OBJECT_ADDED,
            actor,
            details={"count": 3, "filenames": ["a.prt", "b.prt", "c.prt"], "filename": "a.prt"},
        )
        svc.record(
            db,
            ActivityAction.SYSTEM_SETTING_CHANGED,
            actor,
            details={"setting": "system", "smtp_password": "leak-me"},
        )
        db.commit()

        by_action = svc.list_events(db, action=ActivityAction.CHECKED_IN.value)
        assert len(by_action) == 1
        assert by_action[0].action == ActivityAction.CHECKED_IN.value
        assert by_action[0].action_label == "Checked in"
        assert by_action[0].object_filename == "bracket.prt"
        assert "iteration 1 → 2" in by_action[0].summary
        assert "git 8fa24c1" in by_action[0].summary

        by_user = svc.list_events(db, username="Alice")
        assert {row.user for row in by_user} == {"Alice"}

        by_object = svc.list_events(db, object_query="bracket")
        assert len(by_object) == 1
        assert by_object[0].comment == "fix hole"

        by_search = svc.list_events(db, q="bracket")
        assert len(by_search) == 1
        assert by_search[0].object_filename == "bracket.prt"

        added = svc.list_events(db, action=ActivityAction.OBJECT_ADDED.value)
        assert len(added) == 1
        assert added[0].object_filename == "a.prt (+2 more)"
        assert "a.prt" in added[0].summary

        settings_rows = svc.list_events(
            db, action=ActivityAction.SYSTEM_SETTING_CHANGED.value
        )
        assert len(settings_rows) == 1
        assert settings_rows[0].details["smtp_password"] == "[REDACTED]"

        since = datetime.now(timezone.utc) + timedelta(days=1)
        assert svc.list_events(db, since=since) == []


@requires_git
def test_checkin_audit_includes_prev_iteration_and_commit(client, data_dir):
    created = client.post("/api/products", json={"name": "Audit Checkin"})
    assert created.status_code == 201, created.text
    product = created.json()
    added = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("pin.prt", b"pin-v1", "application/octet-stream")},
        data={"comment": "Add pin"},
    )
    assert added.status_code == 201, added.text
    obj = added.json()
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    vault_folder = product.get("vault_folder") or product["uuid"]
    workspace = data_dir / "vaults" / vault_folder / "pin.prt"
    workspace.write_bytes(b"pin-v2")
    checked = client.post(
        f"/api/objects/{obj['uuid']}/checkin",
        json={"comment": "Grew the pin"},
    )
    assert checked.status_code == 200, checked.text

    with client.app.state.ctx.session_factory() as db:
        from creopdm.services.activity_service import ActivityService

        rows = ActivityService().list_events(db, action=ActivityAction.CHECKED_IN.value)
        assert rows
        row = rows[0]
        assert row.details.get("previous_iteration") == 1
        assert row.details.get("iteration") == 2
        assert row.details.get("git_commit")
        assert row.object_filename == "pin.prt"
        assert "iteration 1 → 2" in row.summary
        assert "git " in row.summary


def test_login_logout_and_failed_login_are_audited(auth_client, auth_ctx):
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
    with auth_ctx.session_factory() as db:
        from creopdm.services.activity_service import ActivityService

        logins = ActivityService().list_events(db, action=ActivityAction.USER_LOGIN.value)
        # setup signs in without going through /login — no USER_LOGIN required here.
        assert isinstance(logins, list)

    bad = auth_client.post(
        "/login",
        data={"username": "admin", "password": "WrongPass1"},
        follow_redirects=False,
    )
    assert bad.status_code == 400
    with auth_ctx.session_factory() as db:
        from creopdm.services.activity_service import ActivityService

        fails = ActivityService().list_events(db, action=ActivityAction.LOGIN_FAILED.value)
        assert fails
        assert fails[0].details.get("reason") == "bad_password"
        assert fails[0].machine == "testclient"

    ok = auth_client.post(
        "/login",
        data={"username": "admin", "password": "AdminPass1"},
        follow_redirects=False,
    )
    assert ok.status_code in {302, 303}
    auth_client.get("/logout", follow_redirects=False)
    with auth_ctx.session_factory() as db:
        from creopdm.services.activity_service import ActivityService

        logins = ActivityService().list_events(db, action=ActivityAction.USER_LOGIN.value)
        logouts = ActivityService().list_events(db, action=ActivityAction.USER_LOGOUT.value)
        assert logins
        assert logouts
        assert logins[0].user == "admin"
        assert logouts[0].user == "admin"
        # Browser/agent sessions store client IP (TestClient → "testclient"), not "web".
        assert logins[0].machine == "testclient"
        assert logouts[0].machine == "testclient"


@requires_git
def test_force_undo_records_checkout_override(client, identity, data_dir):
    """Force Undo Checkout must not look like a normal undo in the audit trail."""
    from creopdm.services.git_service import GitService

    created = client.post("/api/products", json={"name": "Audit Override"})
    assert created.status_code == 201, created.text
    product = created.json()
    added = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("pin.prt", b"pin-content", "application/octet-stream")},
        data={"comment": "Add pin"},
    )
    assert added.status_code == 201, added.text
    obj = added.json()
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200

    vault_folder = product.get("vault_folder") or product["uuid"]
    vault = data_dir / "vaults" / vault_folder
    git = GitService()
    head_before = git.get_head(vault)

    identity.become("Bob", "ENG-PC-18")
    forced = client.post(f"/api/objects/{obj['uuid']}/force-undo-checkout")
    assert forced.status_code == 200, forced.text
    assert git.get_head(vault) == head_before

    with client.app.state.ctx.session_factory() as db:
        rows = list(
            db.scalars(
                select(Activity)
                .where(Activity.action == ActivityAction.CHECKOUT_OVERRIDE.value)
                .order_by(Activity.id.desc())
            ).all()
        )
        assert rows, "expected CHECKOUT_OVERRIDE activity"
        details = rows[0].details_json or ""
        assert "Alice" in details or "previous_user" in details
        cancelled = list(
            db.scalars(
                select(Activity).where(
                    Activity.action == ActivityAction.CHECKOUT_CANCELLED.value,
                    Activity.object_id == rows[0].object_id,
                )
            ).all()
        )
        # Force-undo must not also write a silent CHECKOUT_CANCELLED for the override.
        assert not any(
            '"previous_user"' in (c.details_json or "") for c in cancelled
        )


def test_settings_save_redacts_password_in_audit(app):
    """SYSTEM_SETTING_CHANGED details must never keep password values."""
    svc = ActivityService()
    actor = UserIdentity("Alice", "ENG-PC-17")
    with app.state.ctx.session_factory() as db:
        svc.record(
            db,
            ActivityAction.SYSTEM_SETTING_CHANGED,
            actor,
            details={
                "setting": "email",
                "smtp_host": "smtp.example",
                "smtp_password": "plain-password-value",
            },
        )
        db.commit()
        rows = svc.list_events(db, action=ActivityAction.SYSTEM_SETTING_CHANGED.value)
        assert rows
        assert rows[0].details["smtp_password"] == "[REDACTED]"
        assert "plain-password-value" not in str(rows[0].details)
        assert rows[0].details["smtp_host"] == "smtp.example"
