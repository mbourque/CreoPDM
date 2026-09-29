"""Forgot-password / reset-password flow (token email, rate limits)."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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
# Soft cap: still show success, but do not send another mail.
MAX_SENDS_PER_EMAIL_PER_HOUR = 5
MAX_ATTEMPTS_PER_IP_PER_HOUR = 20
# Hard cap: disable the account (non–full-admin) and email administrators.
MAX_ATTEMPTS_PER_EMAIL_PER_DAY = 10

GENERIC_SENT_MESSAGE = (
    "If an account exists for that email address, we sent a link to reset the password. "
    "Check your inbox and spam folder."
)


@dataclass(frozen=True, slots=True)
class ForgotPasswordResult:
    message: str
    sent: bool = False
    disabled_user: bool = False


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


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

    def get_user_by_email(self, db: Session, email: str) -> User | None:
        normalized = _normalize_email(email)
        if not normalized:
            return None
        return db.scalar(
            select(User).where(func.lower(User.email) == normalized).limit(1)
        )

    def request_reset(
        self,
        db: Session,
        *,
        email: str,
        base_url: str,
        request_ip: str | None = None,
        email_enabled: bool = True,
    ) -> ForgotPasswordResult:
        """Always return a generic message (no email enumeration)."""
        normalized = _normalize_email(email)
        ip = _client_ip(request_ip)
        if not normalized or "@" not in normalized:
            raise ValidationAppError("Enter a valid email address.")

        now = datetime.now(timezone.utc)
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)

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
        email_hour = int(
            db.scalar(
                select(func.count())
                .select_from(PasswordResetAttempt)
                .where(
                    PasswordResetAttempt.email_normalized == normalized,
                    PasswordResetAttempt.created_at >= hour_ago,
                )
            )
            or 0
        )
        email_day = int(
            db.scalar(
                select(func.count())
                .select_from(PasswordResetAttempt)
                .where(
                    PasswordResetAttempt.email_normalized == normalized,
                    PasswordResetAttempt.created_at >= day_ago,
                )
            )
            or 0
        )

        user = self.get_user_by_email(db, normalized)
        attempt = PasswordResetAttempt(
            email_normalized=normalized,
            request_ip=ip,
            user_id=user.id if user is not None else None,
            sent=False,
        )
        db.add(attempt)
        db.flush()

        disabled = False
        if user is not None and email_day + 1 >= MAX_ATTEMPTS_PER_EMAIL_PER_DAY:
            disabled = self._maybe_disable_for_abuse(db, user, email_day=email_day + 1)

        allow_send = (
            email_enabled
            and user is not None
            and user.status == UserStatus.ACTIVE.value
            and ip_attempts < MAX_ATTEMPTS_PER_IP_PER_HOUR
            and email_hour < MAX_SENDS_PER_EMAIL_PER_HOUR
            and not disabled
        )
        if not allow_send:
            if user is not None and not email_enabled:
                logger.info("Password reset skipped; email notifications disabled")
            return ForgotPasswordResult(message=GENERIC_SENT_MESSAGE, sent=False, disabled_user=disabled)

        # Invalidate unused tokens for this user.
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

        reset_url = f"{base_url.rstrip('/')}/reset-password?token={raw}"
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
        except Exception:
            logger.exception("Failed to send password reset email to user_id=%s", user.id)
            # Still return generic success; token remains usable if mail is retried manually.
            return ForgotPasswordResult(message=GENERIC_SENT_MESSAGE, sent=False, disabled_user=disabled)

        attempt.sent = True
        db.flush()
        return ForgotPasswordResult(message=GENERIC_SENT_MESSAGE, sent=True, disabled_user=disabled)

    def _maybe_disable_for_abuse(self, db: Session, user: User, *, email_day: int) -> bool:
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
                email_day,
            )
        subject = "CreoPDM: password reset abuse"
        if disabled:
            message = (
                f"The account {user.username} ({user.email}) was disabled after "
                f"{email_day} password-reset attempts in 24 hours.\n\n"
                "Review Administration → Users if this was unexpected."
            )
        else:
            message = (
                f"The account {user.username} ({user.email}) hit {email_day} "
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

    def reset_password(self, db: Session, *, raw_token: str, new_password: str) -> User:
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
        if user.status != UserStatus.ACTIVE.value:
            raise ValidationAppError("This account is disabled. Contact an administrator.")
        user.password_hash = hash_password(validate_password(new_password))
        user.must_change_password = False
        user.updated_at = datetime.now(timezone.utc)
        now = datetime.now(timezone.utc)
        token.used_at = now
        # Invalidate any other outstanding tokens.
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
