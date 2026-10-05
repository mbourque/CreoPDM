"""Utilities Audit log — ActivityService filters, writers, redaction."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, select

from creopdm.app import build_context
from creopdm.config import ConfigManager
from creopdm.constants import ActivityAction
from creopdm.models.activity import Activity
from creopdm.services.activity_service import ActivityService, redact_audit_details
from creopdm.utils.identity import StaticUserProvider, UserIdentity
from tests.conftest import requires_git


@pytest.fixture()
def ctx(data_dir):
    return build_context(ConfigManager(), users=StaticUserProvider("Alice", "ENG-PC-17"))


def test_activity_model_has_audit_columns(ctx):
    cols = {c["name"] for c in inspect(ctx.engine).get_columns("activities")}
    assert {"uuid", "user_uuid", "comment", "action", "timestamp", "details_json"} <= cols


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
            details={"filename": "bracket.prt", "iteration": 2},
            comment="fix hole",
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
        assert by_action[0].object_filename == "bracket.prt"
        assert "iteration 2" in by_action[0].summary

        by_user = svc.list_events(db, username="ali")
        assert {row.user for row in by_user} == {"Alice"}

        by_object = svc.list_events(db, object_query="bracket")
        assert len(by_object) == 1
        assert by_object[0].comment == "fix hole"

        settings_rows = svc.list_events(
            db, action=ActivityAction.SYSTEM_SETTING_CHANGED.value
        )
        assert len(settings_rows) == 1
        assert settings_rows[0].details["smtp_password"] == "[REDACTED]"

        since = datetime.now(timezone.utc) + timedelta(days=1)
        assert svc.list_events(db, since=since) == []


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
