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
    assert {
        "uuid",
        "user_uuid",
        "comment",
        "action",
        "timestamp",
        "details_json",
        "product_uuid",
        "product_name",
        "object_uuid",
        "object_filename",
    } <= cols


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
        "workspace": r"C:\Users\michael\vaults\abc",
        "vault_folder": "abc",
        "relative_path": "folder/part.prt",
    }
    safe = redact_audit_details(raw)
    assert safe is not None
    assert safe["smtp_password"] == "[REDACTED]"
    assert safe["password"] == "[REDACTED]"
    assert safe["enabled"] is True
    assert safe["nested"]["api_token"] == "[REDACTED]"
    assert safe["nested"]["host"] == "mail.example"
    assert "workspace" not in safe
    assert safe["vault_folder"] == "abc"
    assert safe["relative_path"] == "folder/part.prt"


def test_audit_search_ignores_hidden_workspace_path(ctx):
    """Search must not hit Product created solely via a vault path containing the needle."""
    svc = ActivityService()
    actor = UserIdentity("admin", "192.168.1.195", user_uuid="admin-uuid")
    with ctx.session_factory() as db:
        svc.record(
            db,
            ActivityAction.PRODUCT_CREATED,
            actor,
            details={
                "workspace": r"C:\Users\michael\CreoPDM\vaults\test-uuid",
                "name": "Test",
                "vault_folder": "test-uuid",
            },
        )
        svc.record(
            db,
            ActivityAction.USER_LOGIN,
            UserIdentity("michael", "192.168.1.195", user_uuid="mike-uuid"),
            details={"username": "michael"},
        )
        db.commit()
        hits = svc.list_events(db, q="michael")
        actions = [row.action for row in hits]
        assert ActivityAction.USER_LOGIN.value in actions
        assert ActivityAction.PRODUCT_CREATED.value not in actions
        # Commit hashes in details still match Search.
        svc.record(
            db,
            ActivityAction.CHECKED_IN,
            actor,
            details={"filename": "a.prt", "git_commit": "michaeldeadbeef01"},
            comment="note",
        )
        db.commit()
        commit_hits = svc.list_events(db, q="michaeldeadbeef")
        assert any(row.action == ActivityAction.CHECKED_IN.value for row in commit_hits)


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

        by_check_group = svc.list_events(
            db,
            action=f"{ActivityAction.CHECKED_IN.value},{ActivityAction.CHECKED_OUT.value}",
        )
        assert len(by_check_group) == 1
        assert by_check_group[0].action == ActivityAction.CHECKED_IN.value

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
        assert added[0].object_filenames == ("a.prt", "b.prt", "c.prt")
        assert added[0].object_more_count == 2
        assert "a.prt" not in added[0].summary
        assert added[0].summary == ""

        settings_rows = svc.list_events(
            db, action=ActivityAction.SYSTEM_SETTING_CHANGED.value
        )
        assert len(settings_rows) == 1
        assert settings_rows[0].details["smtp_password"] == "[REDACTED]"

        since = datetime.now(timezone.utc) + timedelta(days=1)
        assert svc.list_events(db, since=since) == []


def test_audit_events_to_csv_includes_headers_and_rows(ctx):
    from creopdm.services.activity_service import audit_events_to_csv

    svc = ActivityService()
    actor = UserIdentity("Alice", "ENG-PC-17", user_uuid="alice-uuid")
    with ctx.session_factory() as db:
        svc.record(
            db,
            ActivityAction.CHECKED_IN,
            actor,
            details={"filename": "pin.prt", "iteration": 1},
            comment="first",
        )
        db.commit()
        rows = svc.list_events(db, action=ActivityAction.CHECKED_IN.value)
        assert rows
        csv_text = audit_events_to_csv(rows)
    assert "Timestamp,Event,Event code,User,Client,Product,Product UUID,Object,Comment / summary" in csv_text
    assert "Checked in" in csv_text
    assert "CHECKED_IN" in csv_text
    assert "Alice" in csv_text
    assert "pin.prt" in csv_text


def test_import_batch_chunks_merge_into_one_audit_row(ctx):
    """Upload chunks that share import_batch_id become one Object added row."""
    from creopdm.models.product import Product

    svc = ActivityService()
    actor = UserIdentity("Alice", "testclient", user_uuid="alice-uuid")
    with ctx.session_factory() as db:
        product = Product(
            uuid="prod-batch",
            name="Batch Parts",
            vault_folder="batch-parts",
            repository_path="/tmp/batch-parts",
        )
        db.add(product)
        db.flush()
        batch_id = "batch-abc-123"
        first = svc.record_or_merge_import_batch(
            db,
            ActivityAction.OBJECT_ADDED,
            actor,
            product_id=product.id,
            batch_id=batch_id,
            filenames=["a.prt", "b.prt", "c.prt", "d.prt", "e.prt"],
            count_delta=5,
            batch_total=12,
            comment="Add 12 files",
        )
        second = svc.record_or_merge_import_batch(
            db,
            ActivityAction.OBJECT_ADDED,
            actor,
            product_id=product.id,
            batch_id=batch_id,
            filenames=["f.prt", "g.prt", "h.prt", "i.prt", "j.prt"],
            count_delta=5,
            batch_total=12,
            git_commit="deadbeef01",
        )
        third = svc.record_or_merge_import_batch(
            db,
            ActivityAction.OBJECT_ADDED,
            actor,
            product_id=product.id,
            batch_id=batch_id,
            filenames=["k.prt", "l.prt"],
            count_delta=2,
            batch_total=12,
        )
        db.commit()
        assert first.uuid == second.uuid == third.uuid
        rows = svc.list_events(db, action=ActivityAction.OBJECT_ADDED.value)
        assert len(rows) == 1
        row = rows[0]
        assert row.comment == "Add 12 files"
        assert row.object_filename == "a.prt (+11 more)"
        assert row.object_more_count == 11
        assert len(row.object_filenames) == 12
        assert row.object_filenames[0] == "a.prt"
        assert row.object_filenames[-1] == "l.prt"
        assert row.summary == "Add 12 files · git deadbeef"
        assert row.details.get("batch_id") == batch_id
        assert row.details.get("count") == 12


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


def test_account_password_change_is_audited(auth_client, auth_ctx):
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
    changed = auth_client.post(
        "/account/password",
        data={
            "current_password": "AdminPass1",
            "new_password": "AdminPass2",
            "new_password_confirm": "AdminPass2",
        },
        follow_redirects=False,
    )
    assert changed.status_code in {302, 303}, changed.text
    with auth_ctx.session_factory() as db:
        rows = ActivityService().list_events(
            db, action=ActivityAction.PASSWORD_CHANGED.value
        )
        assert rows
        assert rows[0].action_label == "Password changed"
        assert rows[0].user == "admin"
        assert rows[0].details.get("via") == "account"
        assert "username=admin" in (rows[0].summary or "")


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


@requires_git
def test_delete_product_keeps_prior_audit_and_records_deleted(client, data_dir):
    """Product purge must not wipe activities; PRODUCT_DELETED + snapshots remain."""
    created = client.post("/api/products", json={"name": "Audit Keep"})
    assert created.status_code == 201, created.text
    product = created.json()
    added = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("pin.prt", b"pin-v1", "application/octet-stream")},
        data={"comment": "Add pin"},
    )
    assert added.status_code == 201, added.text

    deleted = client.delete(f"/api/products/{product['uuid']}")
    assert deleted.status_code == 204, deleted.text

    with client.app.state.ctx.session_factory() as db:
        svc = ActivityService()
        all_rows = svc.list_events(db, q="Audit Keep")
        assert all_rows, "expected audit rows after product delete"
        actions = {row.action for row in all_rows}
        assert ActivityAction.PRODUCT_CREATED.value in actions
        assert ActivityAction.OBJECT_ADDED.value in actions
        assert ActivityAction.PRODUCT_DELETED.value in actions
        deleted_rows = [
            row for row in all_rows if row.action == ActivityAction.PRODUCT_DELETED.value
        ]
        assert deleted_rows
        assert deleted_rows[0].product_name == "Audit Keep"
        assert deleted_rows[0].product_uuid == product["uuid"]
        assert deleted_rows[0].product_deleted is True
        added_rows = [
            row for row in all_rows if row.action == ActivityAction.OBJECT_ADDED.value
        ]
        assert added_rows
        assert added_rows[0].product_name == "Audit Keep"
        assert added_rows[0].product_deleted is True
        # Live FKs nulled; snapshot columns remain.
        raw = list(db.scalars(select(Activity)).all())
        assert raw
        assert all(row.product_id is None for row in raw)
        assert any((row.product_uuid or "") == product["uuid"] for row in raw)


@requires_git
def test_product_state_change_records_state_changed_audit(client, data_dir):
    """Lifecycle/read-only Save must audit STATE_CHANGED, not Product updated."""
    created = client.post("/api/products", json={"name": "State Audit"})
    assert created.status_code == 201, created.text
    product = created.json()
    ctx = client.app.state.ctx

    with ctx.session_factory() as db:
        ctx.products.update_product(
            db,
            product["uuid"],
            name="State Audit",
            number=None,
            description=None,
            state="RELEASED",
            read_only=True,
        )

    with ctx.session_factory() as db:
        svc = ActivityService()
        rows = svc.list_events(db, q="State Audit")
        actions = [row.action for row in rows]
        assert ActivityAction.STATE_CHANGED.value in actions
        assert ActivityAction.PRODUCT_UPDATED.value not in actions
        state_rows = [
            row for row in rows if row.action == ActivityAction.STATE_CHANGED.value
        ]
        assert state_rows
        assert state_rows[0].action_label == "Product state changed"
        assert "RELEASED" in (state_rows[0].summary or "")
        assert "state" in (state_rows[0].summary or "").lower()

    with ctx.session_factory() as db:
        ctx.products.update_product(
            db,
            product["uuid"],
            name="State Audit Renamed",
            number=None,
            description=None,
            state="ON_HOLD",
            read_only=True,
        )

    with ctx.session_factory() as db:
        svc = ActivityService()
        rows = svc.list_events(db, q="State Audit")
        actions = {row.action for row in rows}
        assert ActivityAction.PRODUCT_UPDATED.value in actions
        assert ActivityAction.STATE_CHANGED.value in actions
        updated = [
            row for row in rows if row.action == ActivityAction.PRODUCT_UPDATED.value
        ]
        assert updated
        assert "renamed" in (updated[0].summary or "").lower()
        # Identity change must not put state fields on PRODUCT_UPDATED.
        assert "old_state" not in (updated[0].details or {})
