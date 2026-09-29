"""Forgot-password / reset-password flow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from creopdm.app import build_context, create_app
from creopdm.auth_constants import BuiltinRole, UserStatus
from creopdm.config import ConfigManager
from creopdm.exceptions import ValidationAppError
from creopdm.models.password_reset import PasswordResetAttempt, PasswordResetToken
from creopdm.models.user import User
from creopdm.services.password_reset_service import (
    GENERIC_SENT_MESSAGE,
    MAX_ATTEMPTS_PER_EMAIL_PER_DAY,
    PasswordResetService,
)
from tests.conftest import requires_git
from tests.unit.test_auth import _login, _setup_admin_and_users


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _enable_email(auth_ctx, monkeypatch=None):
    auth_ctx.settings.email.enabled = True
    auth_ctx.settings.email.from_address = "creopdm@example.com"
    auth_ctx.settings.email.administrator_email = "admin@example.com"
    sent: list[tuple] = []

    def capture(to, subject, message):
        sent.append((to, subject, message))

    auth_ctx.email.send = capture  # type: ignore[method-assign]
    auth_ctx.notifications.notify = MagicMock()
    return sent


@requires_git
def test_forgot_link_only_after_failed_login(auth_client, auth_ctx):
    _setup_admin_and_users(auth_client, auth_ctx)
    page = auth_client.get("/login")
    assert page.status_code == 200
    assert "Forgot password?" not in page.text

    bad = auth_client.post(
        "/login",
        data={"username": "admin", "password": "wrong"},
    )
    assert bad.status_code == 400
    assert "Forgot password?" in bad.text
    assert 'href="/forgot-password"' in bad.text


@requires_git
def test_forgot_password_sends_email_and_reset_works(auth_client, auth_ctx):
    _setup_admin_and_users(auth_client, auth_ctx, ("engineer", BuiltinRole.ENGINEER.value))
    sent = _enable_email(auth_ctx)

    with auth_ctx.session_factory() as db:
        user = db.scalar(select(User).where(User.username == "engineer"))
        assert user is not None
        email = user.email

    form = auth_client.get("/forgot-password")
    assert form.status_code == 200
    assert "Email" in form.text

    posted = auth_client.post("/forgot-password", data={"email": email})
    assert posted.status_code == 200
    assert GENERIC_SENT_MESSAGE.split(".")[0] in posted.text
    assert len(sent) == 1
    to, subject, body = sent[0]
    assert to == email or to == [email]
    assert "Reset" in subject
    assert "/reset-password?token=" in body
    assert "If you did not ask for this" in body
    token = body.split("/reset-password?token=")[1].split()[0].strip()

    # Unknown email still looks the same (no enumeration).
    again = auth_client.post("/forgot-password", data={"email": "nobody@example.com"})
    assert again.status_code == 200
    assert GENERIC_SENT_MESSAGE.split(".")[0] in again.text
    assert len(sent) == 1

    page = auth_client.get(f"/reset-password?token={token}")
    assert page.status_code == 200
    assert "Choose a new password" in page.text
    assert "engineer" in page.text

    saved = auth_client.post(
        "/reset-password",
        data={
            "token": token,
            "new_password": "NewPass99!",
            "new_password_confirm": "NewPass99!",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert "/login" in saved.headers["location"]
    assert "Password updated" in unquote(saved.headers["location"])

    # Token single-use.
    reuse = auth_client.get(f"/reset-password?token={token}")
    assert reuse.status_code == 400

    _login(auth_client, "engineer", "NewPass99!")
    home = auth_client.get("/", follow_redirects=False)
    assert home.status_code in {200, 303}


@requires_git
def test_forgot_password_spam_disables_non_admin(auth_client, auth_ctx):
    _setup_admin_and_users(auth_client, auth_ctx, ("limited", BuiltinRole.ENGINEER.value))
    sent = _enable_email(auth_ctx)

    with auth_ctx.session_factory() as db:
        user = db.scalar(select(User).where(User.username == "limited"))
        assert user is not None
        email = user.email
        user_id = user.id

    for _ in range(MAX_ATTEMPTS_PER_EMAIL_PER_DAY):
        auth_client.post("/forgot-password", data={"email": email})

    with auth_ctx.session_factory() as db:
        user = db.get(User, user_id)
        assert user is not None
        assert user.status == UserStatus.DISABLED.value
        attempts = db.scalars(
            select(PasswordResetAttempt).where(PasswordResetAttempt.user_id == user_id)
        ).all()
        assert len(attempts) >= MAX_ATTEMPTS_PER_EMAIL_PER_DAY

    auth_ctx.notifications.notify.assert_called()
    assert len(sent) >= 1

    denied = auth_client.post(
        "/login",
        data={"username": "limited", "password": "LimitedPass1"},
    )
    assert denied.status_code == 400
    assert "disabled" in denied.text.lower()


def test_password_reset_expired_token_rejected(auth_ctx):
    service: PasswordResetService = auth_ctx.password_resets
    sent = _enable_email(auth_ctx)
    with auth_ctx.session_factory() as db:
        auth_ctx.user_accounts.create_first_admin(
            db,
            username="admin",
            display_name="Admin",
            password="AdminPass1",
            email="admin@example.com",
        )
        db.commit()

    with auth_ctx.session_factory() as db:
        result = service.request_reset(
            db,
            email="admin@example.com",
            base_url="http://test/",
            email_enabled=True,
        )
        assert result.sent is True
        assert len(sent) == 1
        body = sent[0][2]
        token = body.split("/reset-password?token=")[1].split()[0].strip()
        row = db.scalar(select(PasswordResetToken))
        assert row is not None
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()

    with auth_ctx.session_factory() as db:
        assert service.peek_token(db, token) is None
        with pytest.raises(ValidationAppError, match="invalid or has expired"):
            service.reset_password(db, raw_token=token, new_password="AnotherPass1")
