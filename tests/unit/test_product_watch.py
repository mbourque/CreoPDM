"""Unit tests for product watch / email subscribe."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from creopdm.app import build_context, create_app
from creopdm.auth_constants import BuiltinRole
from creopdm.config import ConfigManager
from creopdm.models.user import ProductWatch, User
from creopdm.services.email_service import EmailService
from creopdm.services.notification_service import NotificationEvent, NotificationService
from creopdm.services.product_watch_service import ProductWatchService
from tests.conftest import requires_git
from tests.unit.test_auth import _login, _setup_admin_and_users
from tests.unit.test_email_notifications import _cfg


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def test_migration_creates_product_watches(auth_ctx):
    tables = inspect(auth_ctx.engine).get_table_names()
    assert "product_watches" in tables


def test_product_watch_eligibility_and_unique(auth_ctx, auth_client):
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
    auth_ctx.settings.email.enabled = True
    with auth_ctx.session_factory() as db:
        admin = db.scalar(select(User).where(User.username == "admin"))
        assert admin is not None
        can, reason = auth_ctx.product_watches.watch_eligibility(admin, email_enabled=True)
        assert can is True
        assert reason is None
        admin.email = "sdfsdf@ss"
        can_bad, reason_bad = auth_ctx.product_watches.watch_eligibility(admin, email_enabled=True)
        assert can_bad is False
        assert reason_bad and "valid email" in reason_bad.lower()
        admin.email = ""
        can_empty, reason_empty = auth_ctx.product_watches.watch_eligibility(admin, email_enabled=True)
        assert can_empty is False
        assert reason_empty and "valid email" in reason_empty.lower()


def test_watch_eligibility_does_not_import_email_validator(auth_ctx, monkeypatch):
    """Files page watch must work even if email-validator is missing from the venv."""
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "email_validator" or name.startswith("email_validator."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)

    class U:
        email = "tim@example.com"

    can, reason = auth_ctx.product_watches.watch_eligibility(U(), email_enabled=True)
    assert can is True
    assert reason is None


@requires_git
def test_product_watch_api_subscribe_unsubscribe_and_notify(
    auth_client, auth_ctx, repo_parent, data_dir
):
    """Watchers get one PRODUCT_ACTIVITY email; actor is excluded; disabled email skips."""
    _setup_admin_and_users(
        auth_client,
        auth_ctx,
        ("watcher", BuiltinRole.ENGINEER.value),
    )
    _login(auth_client, "admin", "AdminPass1")
    auth_ctx.settings.email.enabled = True

    product = auth_client.post("/api/products", json={"name": "Watch Product"}).json()
    product_id = product["uuid"]

    # Notifications off → no bell on Files page.
    auth_ctx.settings.email.enabled = False
    home_off = auth_client.get(f"/?product={product_id}")
    assert home_off.status_code == 200
    assert 'id="product-watch-btn"' not in home_off.text
    auth_ctx.settings.email.enabled = True

    home_on = auth_client.get(f"/?product={product_id}")
    assert home_on.status_code == 200
    assert 'id="product-watch-btn"' in home_on.text
    assert 'data-can-watch="1"' in home_on.text
    assert "temporarily unavailable" not in home_on.text
    assert 'id="product-watch-dialog"' in home_on.text

    # Watcher subscribes.
    _login(auth_client, "watcher", "WatcherPass1")
    # Grant membership (setup helper already sets access_all for fixture users).
    status = auth_client.get(f"/api/products/{product_id}/watch")
    assert status.status_code == 200
    assert status.json()["watching"] is False
    assert status.json()["can_watch"] is True
    assert status.json()["email_notifications_enabled"] is True

    sub = auth_client.post(f"/api/products/{product_id}/watch")
    assert sub.status_code == 200, sub.text
    assert sub.json()["watching"] is True
    with auth_ctx.session_factory() as db:
        watcher = db.scalar(select(User).where(User.username == "watcher"))
        assert watcher is not None
        rows = db.scalars(select(ProductWatch).where(ProductWatch.user_id == watcher.id)).all()
        assert len(rows) == 1

    # Second subscribe is idempotent.
    again = auth_client.post(f"/api/products/{product_id}/watch")
    assert again.status_code == 200
    assert again.json()["watching"] is True

    # Admin checks out; watcher notified once; admin (actor) not in recipients.
    _login(auth_client, "admin", "AdminPass1")
    part = auth_client.post(
        f"/api/products/{product_id}/objects",
        files={"file": ("watch.prt", b"x", "application/octet-stream")},
        data={"comment": "init"},
    )
    assert part.status_code == 201, part.text
    object_id = part.json()["uuid"]

    sent: list[tuple] = []

    def capture(to, subject, message):
        sent.append((list(to) if isinstance(to, list) else [to], subject, message))

    email = MagicMock(spec=EmailService)
    email.send.side_effect = capture
    auth_ctx.notifications = NotificationService(
        get_config=lambda: auth_ctx.settings.email,
        email=email,
    )
    auth_ctx.product_watches = ProductWatchService(auth_ctx.notifications)

    checked = auth_client.post(f"/api/objects/{object_id}/checkout")
    assert checked.status_code == 200, checked.text
    assert len(sent) == 1
    recipients, subject, message = sent[0]
    assert recipients == ["watcher@example.com"]
    assert "Checked out" in subject
    assert "Watch Product" in message
    assert "watch.prt" in message
    assert "admin" in message.lower()
    assert " UTC" not in message
    assert "When: " in message
    # Matches Files page local stamp shape (YYYY-MM-DD HH:MM), not "… UTC".
    when_line = next(line for line in message.splitlines() if line.startswith("When: "))
    assert when_line.startswith("When: ")
    assert len(when_line) >= len("When: YYYY-MM-DD HH:MM")

    # Actor watching themselves is not emailed for their own action.
    watch_self = auth_client.post(f"/api/products/{product_id}/watch")
    assert watch_self.status_code == 200
    sent.clear()
    undone = auth_client.post(f"/api/objects/{object_id}/undo-checkout")
    assert undone.status_code == 200, undone.text
    # Only watcher remains (admin excluded as actor).
    assert len(sent) == 1
    assert sent[0][0] == ["watcher@example.com"]

    # Batch checkout → one email with both files.
    part2 = auth_client.post(
        f"/api/products/{product_id}/objects",
        files={"file": ("other.prt", b"y", "application/octet-stream")},
        data={"comment": "second"},
    )
    assert part2.status_code == 201, part2.text
    sent.clear()
    batch = auth_client.post(
        "/api/objects/batch/checkout",
        json={"object_ids": [object_id, part2.json()["uuid"]]},
    )
    assert batch.status_code == 200, batch.text
    assert len(sent) == 1
    assert "watch.prt" in sent[0][2] and "other.prt" in sent[0][2]
    assert "Comment:" not in sent[0][2]

    # Check-in (queue) includes the check-in comment for watchers.
    sent.clear()
    product_info = auth_client.get(f"/api/products/{product_id}").json()
    vault_folder = product_info.get("vault_folder") or product_id
    workspace = Path(data_dir) / "vaults" / vault_folder / "watch.prt"
    workspace.write_bytes(b"watch-revised")
    checked_in = auth_client.post(
        f"/api/products/{product_id}/checkin-queue",
        json={
            "comment": "Fixed hole pattern on base plate",
            "object_ids": [object_id],
            "add_relative_paths": [],
        },
    )
    assert checked_in.status_code == 200, checked_in.text
    assert len(sent) == 1
    assert "Checked in" in sent[0][1]
    assert "watch.prt" in sent[0][2]
    assert "Comment: Fixed hole pattern on base plate" in sent[0][2]

    # Notifications disabled → no mail.
    auth_ctx.settings.email.enabled = False
    sent.clear()
    auth_client.post(f"/api/objects/{object_id}/undo-checkout")
    assert sent == []

    # Unsubscribe.
    auth_ctx.settings.email.enabled = True
    _login(auth_client, "watcher", "WatcherPass1")
    unsub = auth_client.delete(f"/api/products/{product_id}/watch")
    assert unsub.status_code == 200
    assert unsub.json()["watching"] is False
    with auth_ctx.session_factory() as db:
        watcher = db.scalar(select(User).where(User.username == "watcher"))
        assert watcher is not None
        assert (
            db.scalar(
                select(ProductWatch).where(
                    ProductWatch.user_id == watcher.id,
                )
            )
            is None
        )


@requires_git
def test_force_undo_checkout_emails_previous_owner(auth_client, auth_ctx, repo_parent):
    """Force Undo Checkout emails the former checkout owner when notifications are on.

    Owner need not be watching the product. Disabled notifications send nothing.
    """
    _setup_admin_and_users(
        auth_client,
        auth_ctx,
        ("owner", BuiltinRole.ENGINEER.value),
        ("pdm", BuiltinRole.PDM_MANAGER.value),
    )
    _login(auth_client, "admin", "AdminPass1")
    auth_ctx.settings.email.enabled = True
    product = auth_client.post("/api/products", json={"name": "Force Undo Mail"}).json()
    product_id = product["uuid"]
    part = auth_client.post(
        f"/api/products/{product_id}/objects",
        files={"file": ("owned.prt", b"x", "application/octet-stream")},
        data={"comment": "init"},
    )
    assert part.status_code == 201, part.text
    object_id = part.json()["uuid"]

    _login(auth_client, "owner", "OwnerPass1")
    assert auth_client.post(f"/api/objects/{object_id}/checkout").status_code == 200

    sent: list[tuple] = []

    def capture(to, subject, message):
        sent.append((list(to) if isinstance(to, list) else [to], subject, message))

    email = MagicMock(spec=EmailService)
    email.send.side_effect = capture
    auth_ctx.notifications = NotificationService(
        get_config=lambda: auth_ctx.settings.email,
        email=email,
    )
    auth_ctx.product_watches = ProductWatchService(auth_ctx.notifications)

    _login(auth_client, "pdm", "PdmPass1")
    forced = auth_client.post(f"/api/objects/{object_id}/force-undo-checkout")
    assert forced.status_code == 200, forced.text
    # Owner mail (not watching) — watchers list empty so only owner email.
    assert len(sent) == 1
    recipients, subject, message = sent[0]
    assert recipients == ["owner@example.com"]
    assert "Force Undo Checkout" in subject
    assert "owned.prt" in message
    assert "Your checkout was released" in message
    assert "pdm" in message.lower()

    # Notifications off → no owner mail.
    _login(auth_client, "owner", "OwnerPass1")
    assert auth_client.post(f"/api/objects/{object_id}/checkout").status_code == 200
    auth_ctx.settings.email.enabled = False
    sent.clear()
    _login(auth_client, "pdm", "PdmPass1")
    again = auth_client.post(f"/api/objects/{object_id}/force-undo-checkout")
    assert again.status_code == 200, again.text
    assert sent == []


def test_product_activity_event_requires_explicit_recipients():
    email = MagicMock(spec=EmailService)
    notify = NotificationService(get_config=lambda: _cfg(), email=email)
    notify.notify(NotificationEvent.PRODUCT_ACTIVITY, subject="S", message="M")
    email.send.assert_not_called()
    notify.notify(
        NotificationEvent.PRODUCT_ACTIVITY,
        subject="S",
        message="M",
        to="watcher@example.com",
    )
    email.send.assert_called_once_with(["watcher@example.com"], "S", "M")


def test_product_activity_email_includes_checkin_comment(auth_ctx):
    """Watch mail for Checked in adds a Comment line when a check-in note is present."""
    from types import SimpleNamespace

    sent: list[tuple] = []

    def capture(to, subject, message):
        sent.append((list(to) if isinstance(to, list) else [to], subject, message))

    email = MagicMock(spec=EmailService)
    email.send.side_effect = capture
    watches = ProductWatchService(
        NotificationService(get_config=lambda: auth_ctx.settings.email, email=email)
    )
    product = SimpleNamespace(id=1, uuid="prod-uuid", name="Wedge")
    watches.list_watcher_emails = lambda db, product_id, exclude_user_id=None: [  # type: ignore[method-assign]
        "watcher@example.com"
    ]
    watches.notify_product_activity(
        MagicMock(),
        product=product,  # type: ignore[arg-type]
        action="Checked in",
        actor=None,
        actor_label="David (david)",
        filenames=["base-plate.prt"],
        base_url="http://creopdm.local:52113/",
        object_uuid="obj-uuid",
        comment="  Tightened clearance  ",
        email_enabled=True,
    )
    assert len(sent) == 1
    message = sent[0][2]
    assert "Comment: Tightened clearance" in message
    assert "Files: base-plate.prt" in message
    assert "Open: http://creopdm.local:52113/products/prod-uuid/objects/obj-uuid" in message

    sent.clear()
    watches.notify_product_activity(
        MagicMock(),
        product=product,  # type: ignore[arg-type]
        action="Checked out",
        actor=None,
        actor_label="David (david)",
        filenames=["base-plate.prt"],
        base_url="http://creopdm.local:52113/",
        comment="   ",
        email_enabled=True,
    )
    assert len(sent) == 1
    assert "Comment:" not in sent[0][2]


@requires_git
def test_restricted_user_home_with_email_watch_usable(auth_client, auth_ctx):
    """Restricted engineer + notifications on → working watch bell, never INTERNAL_ERROR.

    Catches: missing products on auth user (login 500), and watch eligibility that
    fail-closed to "temporarily unavailable" while Admin → Email shows enabled.
    """
    from creopdm.auth_constants import UserStatus
    from creopdm.models.user import User
    from sqlalchemy import select

    _setup_admin_and_users(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    alpha = auth_client.post("/api/products", json={"name": "Alpha Only"}).json()
    created = auth_client.post(
        "/admin/users/new",
        data={
            "display_name": "Tim",
            "username": "tim",
            "email": "tim@example.com",
            "role": BuiltinRole.ENGINEER.value,
            "status": UserStatus.ACTIVE.value,
            "password": "TimPass1!",
            "password_confirm": "TimPass1!",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    with auth_ctx.session_factory() as db:
        user = db.scalar(select(User).where(User.username == "tim"))
        assert user is not None
        user.must_change_password = False
        user_uuid = user.uuid
        db.commit()

    restricted = auth_client.post(
        f"/admin/membership/users/{user_uuid}",
        data={
            "product_access_present": "1",
            "product_uuid": [alpha["uuid"]],
        },
        follow_redirects=False,
    )
    assert restricted.status_code == 303, restricted.text

    auth_ctx.settings.email.enabled = True
    login = auth_client.post(
        "/login",
        data={"username": "tim", "password": "TimPass1!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/"

    home = auth_client.get("/")
    assert home.status_code == 200, home.text
    assert "INTERNAL_ERROR" not in home.text
    assert "Alpha Only" in home.text
    # Notifications on + valid account email → usable watch control (not the
    # disabled "temporarily unavailable" catch-all that masked ImportError etc.).
    assert 'id="product-watch-btn"' in home.text
    assert 'data-can-watch="1"' in home.text
    assert "temporarily unavailable" not in home.text
    assert "Product watch is temporarily unavailable." not in home.text

    status = auth_client.get(f"/api/products/{alpha['uuid']}/watch")
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["email_notifications_enabled"] is True
    assert body["can_watch"] is True
    assert body.get("reason") in (None, "")

    with auth_ctx.session_factory() as db:
        loaded = auth_ctx.user_accounts.get_by_uuid(db, user_uuid)
        assert loaded is not None
        assert loaded.access_all_products is False
        assert {p.uuid for p in loaded.products} == {alpha["uuid"]}


def test_membership_helper_swallows_unreadable_products(auth_ctx):
    """Detached/broken products collection must not raise (avoids login INTERNAL_ERROR)."""

    class BrokenUser:
        access_all_products = False
        id = 99

        @property
        def products(self):
            raise RuntimeError("detached")

    broken = BrokenUser()
    assert auth_ctx.user_accounts._membership_product_ids(broken) == set()
    assert auth_ctx.user_accounts.filter_accessible_products(broken, []) == []


@requires_git
def test_watch_is_per_user_other_user_stop_does_not_clear(auth_client, auth_ctx):
    """Tim watches; Michael must not see watching; Michael stop must not clear Tim."""
    from creopdm.models.user import ProductWatch, User
    from sqlalchemy import select

    _setup_admin_and_users(
        auth_client,
        auth_ctx,
        ("tim", BuiltinRole.ENGINEER.value),
        ("michael", BuiltinRole.ENGINEER.value),
    )
    auth_ctx.settings.email.enabled = True
    _login(auth_client, "admin", "AdminPass1")
    product = auth_client.post("/api/products", json={"name": "Conveyor"}).json()
    product_id = product["uuid"]

    with auth_ctx.session_factory() as db:
        for name in ("tim", "michael"):
            user = db.scalar(select(User).where(User.username == name))
            assert user is not None
            user.must_change_password = False
            auth_ctx.user_accounts.set_product_access(
                db, user, access_all=False, product_uuids=[product_id]
            )
        db.commit()

    _login(auth_client, "tim", "TimPass1")
    sub = auth_client.post(f"/api/products/{product_id}/watch")
    assert sub.status_code == 200, sub.text
    assert sub.json()["watching"] is True
    tim_home = auth_client.get(f"/?product={product_id}")
    assert tim_home.status_code == 200
    assert 'data-watching="1"' in tim_home.text
    assert 'data-can-watch="1"' in tim_home.text

    _login(auth_client, "michael", "MichaelPass1")
    michael_status = auth_client.get(f"/api/products/{product_id}/watch")
    assert michael_status.status_code == 200
    assert michael_status.json()["watching"] is False
    michael_home = auth_client.get(f"/?product={product_id}")
    assert michael_home.status_code == 200
    assert 'data-watching="0"' in michael_home.text
    assert "is-watching" not in michael_home.text.split("product-watch-btn", 1)[-1].split("</button>", 1)[0]

    # Michael "stop watching" must not remove Tim's row.
    stop = auth_client.delete(f"/api/products/{product_id}/watch")
    assert stop.status_code == 200
    assert stop.json()["watching"] is False
    with auth_ctx.session_factory() as db:
        tim = db.scalar(select(User).where(User.username == "tim"))
        assert tim is not None
        assert (
            db.scalar(
                select(ProductWatch).where(ProductWatch.user_id == tim.id)
            )
            is not None
        )

    _login(auth_client, "tim", "TimPass1")
    still = auth_client.get(f"/api/products/{product_id}/watch")
    assert still.status_code == 200
    assert still.json()["watching"] is True
    tim_again = auth_client.get(f"/?product={product_id}")
    assert tim_again.status_code == 200
    assert 'data-watching="1"' in tim_again.text
