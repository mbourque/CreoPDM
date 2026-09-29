"""Forgot-password / reset-password flow (token email, rate limits)."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from creopdm.auth_constants import ADMINISTRATION_PERMISSION_KEYS, UserStatus
from creopdm.exceptions import ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.models.password_reset import PasswordResetAttempt, PasswordResetToken
from creopdm.models.user import User
from creopdm.services.email_service import EmailService
from creopdm.services.notification_service import NotificationEvent, NotificationService
from creopdm.services.user_service import UserService, validate_password
from creopdm.utils.passwords import hash_password

logger = get_logger("password_reset")

TOKEN_TTL = timedelta(hours=1)
MAX_SENDS_PER_USER_PER_HOUR = 5
MAX_ATTEMPTS_PER_IP_PER_HOUR = 20
MAX_ATTEMPTS_PER_USER_PER_DAY = 10

MATCH_ERROR = "Username and email do not match an account."
SENT_MESSAGE = (
    "We sent a reset link to that email. Check your inbox and spam folder."
)


@dataclass(frozen=True, slots=True)
class ForgotPasswordResult:
    message: str
    sent: bool = False
    disabled_user: bool = False


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _client_ip(raw: str | None) -> str | None:
    text = (raw or "").strip()
    return text[:64] if text else None


class PasswordResetService:
    def __init__(
        self,
        users: UserService,
        email: EmailService,
        notifications: NotificationService,
    ) -> None:
        self._users = users
        self._email = email
        self._notifications = notifications

    def request_reset(
        self,
        db: Session,
        *,
        username: str,
        email: str,
        base_url: str,
        request_ip: str | None = None,
        email_enabled: bool = True,
    ) -> ForgotPasswordResult:
        """Require username + matching email for that account only."""
        uname = _normalize_username(username)
        normalized = _normalize_email(email)
        ip = _client_ip(request_ip)
        if not uname:
            raise ValidationAppError("Username is required.")
        if not normalized or "@" not in normalized:
            raise ValidationAppError("Enter a valid email address.")

        now = datetime.now(timezone.utc)
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)

        user = self._users.get_by_username(db, uname)
        email_ok = (
            user is not None and _normalize_email(user.email) == normalized
        )

        attempt = PasswordResetAttempt(
            email_normalized=normalized,
            request_ip=ip,
            user_id=user.id if user is not None else None,
            sent=False,
        )
        db.add(attempt)
        db.flush()

        ip_attempts = 0
        if ip:
            ip_attempts = int(
                db.scalar(
                    select(func.count())
                    .select_from(PasswordResetAttempt)
                    .where(
                        PasswordResetAttempt.request_ip == ip,
                        PasswordResetAttempt.created_at >= hour_ago,
                    )
                )
                or 0
            )

        user_hour = 0
        user_day = 0
        if user is not None:
            user_hour = int(
                db.scalar(
                    select(func.count())
                    .select_from(PasswordResetAttempt)
                    .where(
                        PasswordResetAttempt.user_id == user.id,
                        PasswordResetAttempt.created_at >= hour_ago,
                    )
                )
                or 0
            )
            user_day = int(
                db.scalar(
                    select(func.count())
                    .select_from(PasswordResetAttempt)
                    .where(
                        PasswordResetAttempt.user_id == user.id,
                        PasswordResetAttempt.created_at >= day_ago,
                    )
                )
                or 0
            )

        disabled = False
        if user is not None and user_day >= MAX_ATTEMPTS_PER_USER_PER_DAY:
            disabled = self._maybe_disable_for_abuse(db, user, attempt_count=user_day)

        if not email_ok or user is None:
            raise ValidationAppError(MATCH_ERROR)

        if disabled:
            raise ValidationAppError("This account is disabled. Contact an administrator.")

        allow_send = (
            email_enabled
            and user.status == UserStatus.ACTIVE.value
            and ip_attempts < MAX_ATTEMPTS_PER_IP_PER_HOUR
            and user_hour < MAX_SENDS_PER_USER_PER_HOUR
        )
        if not allow_send:
            if not email_enabled:
                raise ValidationAppError(
                    "Password reset email is not configured. Ask an administrator for help."
                )
            raise ValidationAppError(
                "Too many reset attempts. Try again later or contact an administrator."
            )

        for old in db.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            )
        ).all():
            old.used_at = now

        raw = secrets.token_urlsafe(32)
        token = PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_token(raw),
            expires_at=now + TOKEN_TTL,
            request_ip=ip,
        )
        db.add(token)
        db.flush()

        reset_url = (
            f"{base_url.rstrip('/')}/reset-password"
            f"?token={raw}&username={quote(user.username, safe='')}"
        )
        subject = "Reset your CreoPDM password"
        body = (
            f"Hello {user.display_name or user.username},\n\n"
            "We received a request to reset the password for your CreoPDM account "
            f"({user.username}).\n\n"
            f"Open this link to choose a new password (expires in 1 hour):\n{reset_url}\n\n"
            "If you did not ask for this, you can ignore this email — your password "
            "will stay the same. If you keep getting these messages, tell your "
            "CreoPDM administrator.\n\n"
            "— CreoPDM\n"
        )
        try:
            self._email.send(user.email, subject, body)
        except Exception as exc:
            logger.exception("Failed to send password reset email to user_id=%s", user.id)
            # Do not leave a usable token if the caller commits attempt bookkeeping.
            token.used_at = datetime.now(timezone.utc)
            db.flush()
            raise ValidationAppError(
                "Could not send the reset email. Try again later or contact an administrator."
            ) from exc

        attempt.sent = True
        db.flush()
        return ForgotPasswordResult(message=SENT_MESSAGE, sent=True, disabled_user=False)

    def _maybe_disable_for_abuse(self, db: Session, user: User, *, attempt_count: int) -> bool:
        """Disable non–full-admin accounts after too many reset attempts; always notify."""
        is_full_admin = ADMINISTRATION_PERMISSION_KEYS <= self._users.permission_keys_for_user(user)
        disabled = False
        if user.status == UserStatus.ACTIVE.value and not is_full_admin:
            user.status = UserStatus.DISABLED.value
            user.updated_at = datetime.now(timezone.utc)
            disabled = True
            db.flush()
            logger.warning(
                "Disabled user %s after %s password-reset attempts in 24h",
                user.username,
                attempt_count,
            )
        subject = "CreoPDM: password reset abuse"
        if disabled:
            message = (
                f"The account {user.username} ({user.email}) was disabled after "
                f"{attempt_count} password-reset attempts in 24 hours.\n\n"
                "Review Administration → Users if this was unexpected."
            )
        else:
            message = (
                f"The account {user.username} ({user.email}) hit {attempt_count} "
                "password-reset attempts in 24 hours. The account was not disabled "
                "because it holds full Administration access — please investigate."
            )
        self._notifications.notify(
            NotificationEvent.SYSTEM_EVENT,
            subject=subject,
            message=message,
        )
        return disabled

    def peek_token(self, db: Session, raw_token: str) -> User | None:
        """Return the user for a still-valid unused token, or None."""
        token = self._load_valid_token(db, raw_token)
        if token is None:
            return None
        return db.get(User, token.user_id)

    def reset_password(
        self,
        db: Session,
        *,
        raw_token: str,
        username: str,
        new_password: str,
    ) -> User:
        uname = _normalize_username(username)
        if not uname:
            raise ValidationAppError("Username is required.")
        token = self._load_valid_token(db, raw_token)
        if token is None:
            raise ValidationAppError(
                "This reset link is invalid or has expired. Request a new one from the sign-in page."
            )
        user = db.get(User, token.user_id)
        if user is None:
            raise ValidationAppError(
                "This reset link is invalid or has expired. Request a new one from the sign-in page."
            )
        if _normalize_username(user.username) != uname:
            raise ValidationAppError(
                "Username does not match this reset link. Use the username from the email."
            )
        if user.status != UserStatus.ACTIVE.value:
            raise ValidationAppError("This account is disabled. Contact an administrator.")
        user.password_hash = hash_password(validate_password(new_password))
        user.must_change_password = False
        user.updated_at = datetime.now(timezone.utc)
        now = datetime.now(timezone.utc)
        token.used_at = now
        for other in db.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.id != token.id,
            )
        ).all():
            other.used_at = now
        db.flush()
        return user

    def _load_valid_token(self, db: Session, raw_token: str) -> PasswordResetToken | None:
        raw = (raw_token or "").strip()
        if not raw or len(raw) > 200:
            return None
        digest = _hash_token(raw)
        token = db.scalar(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == digest)
        )
        if token is None or token.used_at is not None:
            return None
        now = datetime.now(timezone.utc)
        expires = token.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < now:
            return None
        return token
