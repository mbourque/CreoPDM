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
    MAX_ATTEMPTS_PER_USER_PER_DAY,
    SENT_MESSAGE,
    TOKEN_TTL,
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


def _unlock_forgot(auth_client, username: str) -> str:
    """Wrong password for a known user; return the one-time forgot_token from the page."""
    bad = auth_client.post(
        "/login",
        data={"username": username, "password": "not-the-real-password"},
    )
    assert bad.status_code == 400
    assert "Forgot password?" in bad.text
    assert "forgot_start" in bad.text
    assert 'name="forgot_token"' in bad.text
    marker = 'name="forgot_token" value="'
    assert marker in bad.text
    token = bad.text.split(marker, 1)[1].split('"', 1)[0]
    assert token
    return token


def _open_forgot(auth_client, username: str):
    """Open the email form via POST from the login Forgot button (GET is never allowed)."""
    token = _unlock_forgot(auth_client, username)
    form = auth_client.post(
        "/forgot-password",
        data={"username": username, "forgot_start": "1", "forgot_token": token},
        follow_redirects=False,
    )
    assert form.status_code == 200
    assert 'name="forgot_token"' in form.text
    return form


def _forgot_token_from_html(html: str) -> str:
    marker = 'name="forgot_token" value="'
    assert marker in html
    return html.split(marker, 1)[1].split('"', 1)[0]


@requires_git
def test_forgot_link_only_after_failed_login(auth_client, auth_ctx):
    _setup_admin_and_users(auth_client, auth_ctx)
    page = auth_client.get("/login")
    assert page.status_code == 200
    assert "Forgot password?" not in page.text

    # Typing /forgot-password (bare or with query) is never allowed.
    for url in ("/forgot-password", "/forgot-password?username=admin"):
        crafted = auth_client.get(url, follow_redirects=False)
        assert crafted.status_code == 303
        assert "/login" in crafted.headers["location"]

    # Wrong password for a known user → offer forgot (session grant + token).
    bad = auth_client.post(
        "/login",
        data={"username": "admin", "password": "wrong"},
    )
    assert bad.status_code == 400
    assert "Forgot password?" in bad.text
    assert 'formaction=/forgot-password' in bad.text or 'formaction="/forgot-password"' in bad.text
    assert 'data-forgot-username="admin"' in bad.text
    token = _forgot_token_from_html(bad.text)

    # Even with a grant, GET still cannot open the form.
    still_blocked = auth_client.get("/forgot-password", follow_redirects=False)
    assert still_blocked.status_code == 303
    still_blocked_q = auth_client.get(
        "/forgot-password?username=admin",
        follow_redirects=False,
    )
    assert still_blocked_q.status_code == 303

    allowed = auth_client.post(
        "/forgot-password",
        data={"username": "admin", "forgot_start": "1", "forgot_token": token},
        follow_redirects=False,
    )
    assert allowed.status_code == 200
    assert 'value="admin"' in allowed.text

    # POST without the one-time token is rejected.
    no_token = auth_client.post(
        "/forgot-password",
        data={"username": "admin", "forgot_start": "1"},
        follow_redirects=False,
    )
    assert no_token.status_code == 303
    assert "/login" in no_token.headers["location"]

    # Changing the login username then clicking Forgot must not keep the old grant.
    token2 = _unlock_forgot(auth_client, "admin")
    changed = auth_client.post(
        "/forgot-password",
        data={"username": "kim1", "forgot_start": "1", "forgot_token": token2},
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert "/login" in changed.headers["location"]
    stale = auth_client.get("/forgot-password", follow_redirects=False)
    assert stale.status_code == 303

    # Fresh client: unknown username → no forgot link / no grant.
    with TestClient(create_app(auth_ctx)) as other:
        unknown = other.post(
            "/login",
            data={"username": "nosuchuser", "password": "whatever"},
        )
        assert unknown.status_code == 400
        assert "Forgot password?" not in unknown.text
        no_user = other.get("/forgot-password", follow_redirects=False)
        assert no_user.status_code == 303
        assert "/login" in no_user.headers["location"]


@requires_git
def test_forgot_password_requires_username_and_matching_email(auth_client, auth_ctx):
    _setup_admin_and_users(auth_client, auth_ctx, ("engineer", BuiltinRole.ENGINEER.value))
    sent = _enable_email(auth_ctx)

    with auth_ctx.session_factory() as db:
        user = db.scalar(select(User).where(User.username == "engineer"))
        assert user is not None
        email = user.email

    bare_forgot = auth_client.get("/forgot-password", follow_redirects=False)
    assert bare_forgot.status_code == 303
    assert "/login" in bare_forgot.headers["location"]

    form = _open_forgot(auth_client, "engineer")
    assert 'name="username"' in form.text
    assert 'value="engineer"' in form.text
    assert "disabled" in form.text
    token = _forgot_token_from_html(form.text)

    # Wrong email: same success screen as a match (no enumeration), no mail, grant spent.
    wrong = auth_client.post(
        "/forgot-password",
        data={
            "username": "engineer",
            "email": "nobody@example.com",
            "forgot_token": token,
        },
    )
    assert wrong.status_code == 200
    assert SENT_MESSAGE.split(".")[0] in wrong.text
    assert "do not match an account" not in wrong.text
    assert "Send reset link" not in wrong.text
    assert sent == []

    # Cannot keep guessing emails with the same grant.
    retry = auth_client.post(
        "/forgot-password",
        data={
            "username": "engineer",
            "email": email,
            "forgot_token": token,
        },
        follow_redirects=False,
    )
    assert retry.status_code == 303
    assert "/login" in retry.headers["location"]

    # Tampered form username (different from session grant) is rejected.
    form = _open_forgot(auth_client, "engineer")
    token = _forgot_token_from_html(form.text)
    tampered = auth_client.post(
        "/forgot-password",
        data={"username": "admin", "email": email, "forgot_token": token},
        follow_redirects=False,
    )
    assert tampered.status_code == 303
    assert "/login" in tampered.headers["location"]

    # Fresh grant for the real matching email.
    form = _open_forgot(auth_client, "engineer")
    token = _forgot_token_from_html(form.text)
    posted = auth_client.post(
        "/forgot-password",
        data={"username": "engineer", "email": email, "forgot_token": token},
    )
    assert posted.status_code == 200
    assert SENT_MESSAGE.split(".")[0] in posted.text
    assert len(sent) == 1
    to, subject, body = sent[0]
    assert to == email or to == [email]
    assert "Reset" in subject
    assert "/reset-password?token=" in body
    assert "username=engineer" in body
    assert "If you did not ask for this" in body
    reset_token = body.split("/reset-password?token=")[1].split("&")[0].strip()

    # After a successful send, GET still cannot open forgot-password.
    assert auth_client.get("/forgot-password", follow_redirects=False).status_code == 303

    # Token alone (no username) is rejected.
    bare = auth_client.get(f"/reset-password?token={reset_token}")
    assert bare.status_code == 400

    page = auth_client.get(f"/reset-password?token={reset_token}&username=engineer")
    assert page.status_code == 200
    assert 'name="username"' in page.text
    assert "disabled" in page.text
    assert 'value="engineer"' in page.text

    # Wrong username on submit is rejected.
    bad_user = auth_client.post(
        "/reset-password",
        data={
            "token": reset_token,
            "username": "admin",
            "new_password": "NewPass99!",
            "new_password_confirm": "NewPass99!",
        },
    )
    assert bad_user.status_code == 400

    saved = auth_client.post(
        "/reset-password",
        data={
            "token": reset_token,
            "username": "engineer",
            "new_password": "NewPass99!",
            "new_password_confirm": "NewPass99!",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert "/login" in saved.headers["location"]
    assert "Password updated" in unquote(saved.headers["location"])

    reuse = auth_client.get(f"/reset-password?token={reset_token}&username=engineer")
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

    # Each try needs a fresh wrong-password grant (one email attempt per grant).
    for i in range(MAX_ATTEMPTS_PER_USER_PER_DAY):
        form = _open_forgot(auth_client, "limited")
        token = _forgot_token_from_html(form.text)
        resp = auth_client.post(
            "/forgot-password",
            data={
                "username": "limited",
                "email": f"wrong{i}@example.com",
                "forgot_token": token,
            },
        )
        assert resp.status_code == 200
        assert SENT_MESSAGE.split(".")[0] in resp.text
        assert sent == []

    with auth_ctx.session_factory() as db:
        user = db.get(User, user_id)
        assert user is not None
        assert user.status == UserStatus.DISABLED.value
        attempts = db.scalars(
            select(PasswordResetAttempt).where(PasswordResetAttempt.user_id == user_id)
        ).all()
        assert len(attempts) >= MAX_ATTEMPTS_PER_USER_PER_DAY

    auth_ctx.notifications.notify.assert_called()

    denied = auth_client.post(
        "/login",
        data={"username": "limited", "password": "LimitedPass1"},
    )
    assert denied.status_code == 400
    assert "disabled" in denied.text.lower()


def test_password_reset_expired_token_rejected(auth_ctx):
    assert TOKEN_TTL == timedelta(minutes=10)
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
        before = datetime.now(timezone.utc)
        result = service.request_reset(
            db,
            username="admin",
            email="admin@example.com",
            base_url="http://test/",
            email_enabled=True,
        )
        after = datetime.now(timezone.utc)
        assert result.sent is True
        assert len(sent) == 1
        body = sent[0][2]
        assert "expires in 10 minutes" in body
        token = body.split("/reset-password?token=")[1].split("&")[0].strip()
        row = db.scalar(select(PasswordResetToken))
        assert row is not None
        expires = row.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        assert before + TOKEN_TTL <= expires <= after + TOKEN_TTL
        # Past the 10-minute window → rejected.
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    with auth_ctx.session_factory() as db:
        assert service.peek_token(db, token) is None
        with pytest.raises(ValidationAppError, match="invalid or has expired"):
            service.reset_password(
                db,
                raw_token=token,
                username="admin",
                new_password="AnotherPass1",
            )
