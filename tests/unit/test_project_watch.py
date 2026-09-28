"""Unit tests for project watch / email subscribe."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from creopdm.app import build_context, create_app
from creopdm.auth_constants import BuiltinRole
from creopdm.config import ConfigManager
from creopdm.models.user import ProjectWatch, User
from creopdm.services.email_service import EmailService
from creopdm.services.notification_service import NotificationEvent, NotificationService
from creopdm.services.project_watch_service import ProjectWatchService
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


def test_migration_creates_project_watches(auth_ctx):
    tables = inspect(auth_ctx.engine).get_table_names()
    assert "project_watches" in tables


def test_project_watch_eligibility_and_unique(auth_ctx, auth_client):
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
        can, reason = auth_ctx.project_watches.watch_eligibility(admin, email_enabled=True)
        assert can is True
        assert reason is None
        admin.email = "sdfsdf@ss"
        can_bad, reason_bad = auth_ctx.project_watches.watch_eligibility(admin, email_enabled=True)
        assert can_bad is False
        assert reason_bad and "valid email" in reason_bad.lower()


@requires_git
def test_project_watch_api_subscribe_unsubscribe_and_notify(auth_client, auth_ctx, repo_parent):
    """Watchers get one PROJECT_ACTIVITY email; actor is excluded; disabled email skips."""
    _setup_admin_and_users(
        auth_client,
        auth_ctx,
        ("watcher", BuiltinRole.ENGINEER.value),
    )
    _login(auth_client, "admin", "AdminPass1")
    auth_ctx.settings.email.enabled = True

    project = auth_client.post("/api/projects", json={"name": "Watch Proj"}).json()
    project_id = project["uuid"]

    # Notifications off → no bell on Files page.
    auth_ctx.settings.email.enabled = False
    home_off = auth_client.get(f"/?project={project_id}")
    assert home_off.status_code == 200
    assert 'id="project-watch-btn"' not in home_off.text
    auth_ctx.settings.email.enabled = True

    home_on = auth_client.get(f"/?project={project_id}")
    assert home_on.status_code == 200
    assert 'id="project-watch-btn"' in home_on.text
    assert 'id="project-watch-dialog"' in home_on.text

    # Watcher subscribes.
    _login(auth_client, "watcher", "WatcherPass1")
    # Grant membership (setup helper already sets access_all for fixture users).
    status = auth_client.get(f"/api/projects/{project_id}/watch")
    assert status.status_code == 200
    assert status.json()["watching"] is False
    assert status.json()["can_watch"] is True
    assert status.json()["email_notifications_enabled"] is True

    sub = auth_client.post(f"/api/projects/{project_id}/watch")
    assert sub.status_code == 200, sub.text
    assert sub.json()["watching"] is True
    with auth_ctx.session_factory() as db:
        watcher = db.scalar(select(User).where(User.username == "watcher"))
        assert watcher is not None
        rows = db.scalars(select(ProjectWatch).where(ProjectWatch.user_id == watcher.id)).all()
        assert len(rows) == 1

    # Second subscribe is idempotent.
    again = auth_client.post(f"/api/projects/{project_id}/watch")
    assert again.status_code == 200
    assert again.json()["watching"] is True

    # Admin checks out; watcher notified once; admin (actor) not in recipients.
    _login(auth_client, "admin", "AdminPass1")
    part = auth_client.post(
        f"/api/projects/{project_id}/objects",
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
    auth_ctx.project_watches = ProjectWatchService(auth_ctx.notifications)

    checked = auth_client.post(f"/api/objects/{object_id}/checkout")
    assert checked.status_code == 200, checked.text
    assert len(sent) == 1
    recipients, subject, message = sent[0]
    assert recipients == ["watcher@example.com"]
    assert "Checked out" in subject
    assert "Watch Proj" in message
    assert "watch.prt" in message
    assert "admin" in message.lower()

    # Actor watching themselves is not emailed for their own action.
    watch_self = auth_client.post(f"/api/projects/{project_id}/watch")
    assert watch_self.status_code == 200
    sent.clear()
    undone = auth_client.post(f"/api/objects/{object_id}/undo-checkout")
    assert undone.status_code == 200, undone.text
    # Only watcher remains (admin excluded as actor).
    assert len(sent) == 1
    assert sent[0][0] == ["watcher@example.com"]

    # Batch checkout → one email with both files.
    part2 = auth_client.post(
        f"/api/projects/{project_id}/objects",
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

    # Notifications disabled → no mail.
    auth_ctx.settings.email.enabled = False
    sent.clear()
    auth_client.post(f"/api/objects/{object_id}/undo-checkout")
    assert sent == []

    # Unsubscribe.
    auth_ctx.settings.email.enabled = True
    _login(auth_client, "watcher", "WatcherPass1")
    unsub = auth_client.delete(f"/api/projects/{project_id}/watch")
    assert unsub.status_code == 200
    assert unsub.json()["watching"] is False
    with auth_ctx.session_factory() as db:
        watcher = db.scalar(select(User).where(User.username == "watcher"))
        assert watcher is not None
        assert (
            db.scalar(
                select(ProjectWatch).where(
                    ProjectWatch.user_id == watcher.id,
                )
            )
            is None
        )


def test_project_activity_event_requires_explicit_recipients():
    email = MagicMock(spec=EmailService)
    notify = NotificationService(get_config=lambda: _cfg(), email=email)
    notify.notify(NotificationEvent.PROJECT_ACTIVITY, subject="S", message="M")
    email.send.assert_not_called()
    notify.notify(
        NotificationEvent.PROJECT_ACTIVITY,
        subject="S",
        message="M",
        to="watcher@example.com",
    )
    email.send.assert_called_once_with(["watcher@example.com"], "S", "M")
