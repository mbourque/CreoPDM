"""Session secret, cookie helpers, and agent Bearer tokens for login."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from pathlib import Path

SESSION_COOKIE = "creopdm_session"
SESSION_USER_KEY = "user_uuid"
# Set only after wrong password for a known user; gates /forgot-password.
SESSION_FORGOT_USERNAME_KEY = "forgot_password_username"

# Agent fetches vault content without the browser cookie; JS passes this Bearer.
AGENT_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 14  # match session cookie


def ensure_session_secret(config_dir: Path) -> str:
    """Load or create a random session signing secret under the data dir."""
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "session.secret"
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()
        if len(text) >= 32:
            return text
    secret = secrets.token_urlsafe(48)
    path.write_text(secret + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return secret


def mint_agent_token(user_uuid: str, secret: str, *, now: int | None = None) -> str:
    """Signed token the browser gives creopdm-agent to call CreoPDM as this user."""
    uid = (user_uuid or "").strip()
    if not uid:
        raise ValueError("user_uuid is required")
    issued = int(now if now is not None else time.time())
    expires = issued + AGENT_TOKEN_MAX_AGE_SECONDS
    payload = f"{uid}.{expires}"
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_agent_token(token: str, secret: str, *, now: int | None = None) -> str | None:
    """Return user_uuid if the agent Bearer is valid, else None."""
    text = (token or "").strip()
    parts = text.split(".")
    if len(parts) != 3:
        return None
    uid, exp_text, sig = parts
    if not uid or not exp_text or not sig:
        return None
    try:
        expires = int(exp_text)
    except ValueError:
        return None
    current = int(now if now is not None else time.time())
    if current > expires:
        return None
    payload = f"{uid}.{expires}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    return uid


def bearer_token_from_header(authorization: str | None) -> str | None:
    """Parse `Authorization: Bearer <token>`."""
    raw = (authorization or "").strip()
    if not raw.lower().startswith("bearer "):
        return None
    token = raw[7:].strip()
    return token or None
