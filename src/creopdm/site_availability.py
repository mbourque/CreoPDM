"""Display-only site availability (maintenance) mode.

When unavailable, HTML pages for non-administrators show a message. API and
agent routes are never blocked so in-flight check-ins, uploads, and Git work
are not interrupted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SITE_AVAILABLE = "available"
SITE_UNAVAILABLE = "unavailable"

DEFAULT_SITE_UNAVAILABLE_MESSAGE = (
    "CreoPDM is undergoing maintenance and will be available again soon. "
    "Please check back later, or contact your administrator if you need help."
)

_SINCE_MARKER = "\n\nSince "


def normalize_site_availability(value: object) -> str:
    key = str(value or SITE_AVAILABLE).strip().lower()
    if key == SITE_UNAVAILABLE:
        return SITE_UNAVAILABLE
    return SITE_AVAILABLE


def normalize_site_unavailable_message(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return DEFAULT_SITE_UNAVAILABLE_MESSAGE
    # Keep settings JSON bounded.
    if len(text) > 2000:
        return text[:2000]
    return text


def default_unavailable_message(*, when: datetime | None = None) -> str:
    """Stock maintenance copy plus a pretty local “Since …” stamp."""
    from creopdm.utils.timefmt import format_local_pretty

    stamp = when or datetime.now(timezone.utc)
    pretty = format_local_pretty(stamp) or stamp.astimezone().strftime("%Y-%m-%d %H:%M")
    return f"{DEFAULT_SITE_UNAVAILABLE_MESSAGE}{_SINCE_MARKER}{pretty}."


def is_stock_unavailable_message(value: object) -> bool:
    """True when empty, bare default, or default with a Since line (safe to re-stamp)."""
    text = str(value or "").strip()
    if not text or text == DEFAULT_SITE_UNAVAILABLE_MESSAGE:
        return True
    return text.startswith(DEFAULT_SITE_UNAVAILABLE_MESSAGE + _SINCE_MARKER)


def message_for_unavailable_save(
    *,
    was_unavailable: bool,
    message: object,
    when: datetime | None = None,
) -> str:
    """Stamp a pretty Since date when turning unavailable on with the stock message."""
    text = str(message or "").strip()
    if not was_unavailable and is_stock_unavailable_message(text):
        return default_unavailable_message(when=when)
    return normalize_site_unavailable_message(text)


def site_is_unavailable(settings: Any) -> bool:
    ui = getattr(settings, "ui", None)
    return normalize_site_availability(getattr(ui, "site_availability", SITE_AVAILABLE)) == SITE_UNAVAILABLE


def site_unavailable_message(settings: Any) -> str:
    ui = getattr(settings, "ui", None)
    return normalize_site_unavailable_message(getattr(ui, "site_unavailable_message", ""))


def user_bypasses_site_unavailable(request: Any) -> bool:
    """Administrators who can change System Settings still use the app."""
    return bool(getattr(getattr(request, "state", None), "can_manage_settings", False))
