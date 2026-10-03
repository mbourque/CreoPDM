"""Display-only site availability (maintenance) mode.

When unavailable, HTML pages for non-administrators show a message. API and
agent routes are never blocked so in-flight check-ins, uploads, and Git work
are not interrupted.
"""

from __future__ import annotations

from typing import Any

SITE_AVAILABLE = "available"
SITE_UNAVAILABLE = "unavailable"

DEFAULT_SITE_UNAVAILABLE_MESSAGE = (
    "CreoPDM is undergoing maintenance and will be available again soon. "
    "Please check back later, or contact your administrator if you need help."
)


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


def site_is_unavailable(settings: Any) -> bool:
    ui = getattr(settings, "ui", None)
    return normalize_site_availability(getattr(ui, "site_availability", SITE_AVAILABLE)) == SITE_UNAVAILABLE


def site_unavailable_message(settings: Any) -> str:
    ui = getattr(settings, "ui", None)
    return normalize_site_unavailable_message(getattr(ui, "site_unavailable_message", ""))


def user_bypasses_site_unavailable(request: Any) -> bool:
    """Administrators who can change System Settings still use the app."""
    return bool(getattr(getattr(request, "state", None), "can_manage_settings", False))
