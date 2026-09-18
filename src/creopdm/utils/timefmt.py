"""Display UTC timestamps in the workstation's local timezone."""

from __future__ import annotations

from datetime import datetime, timezone


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_local(value: datetime | None) -> datetime | None:
    utc = as_utc(value)
    if utc is None:
        return None
    return utc.astimezone()


def format_local(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Jinja filter: show a stored UTC time using this PC's clock."""
    local = to_local(value)
    if local is None:
        return ""
    return local.strftime(fmt)
