"""Session secret and cookie helpers for login."""

from __future__ import annotations

import secrets
from pathlib import Path

SESSION_COOKIE = "creopdm_session"
SESSION_USER_KEY = "user_uuid"


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
