"""Re-auth with the signed-in user's password for destructive actions."""

from __future__ import annotations

from sqlalchemy.orm import Session

from creopdm.context import AppContext
from creopdm.exceptions import ValidationAppError
from creopdm.models.user import User
from creopdm.utils.passwords import verify_password


def require_danger_password(
    ctx: AppContext,
    db: Session,
    password: str,
    *,
    auth_user: User | None = None,
) -> None:
    """Require the current user's password (skipped when auth is disabled for tests)."""
    if password is None or password == "":
        raise ValidationAppError("Enter your password to confirm.")
    if not ctx.auth_enabled:
        return
    user = auth_user
    if user is None:
        identity = ctx.users.get_current_user()
        username = (identity.user_name or "").strip()
        if username:
            user = ctx.user_accounts.get_by_username(db, username)
    if user is None:
        raise ValidationAppError("Sign in again to confirm this action.")
    if not verify_password(password, user.password_hash):
        raise ValidationAppError("Incorrect password.")


__all__ = ["require_danger_password"]
