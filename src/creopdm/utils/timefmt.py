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


def _pretty_from_local_parts(year: int, month: int, day: int, hour: int, minute: int) -> str:
    """Monday, July 23, 2026 at 5:30pm from wall-clock parts."""
    # Use a naive local datetime only to resolve weekday name.
    stamp = datetime(year, month, day, hour, minute)
    hour12 = hour % 12 or 12
    ampm = "am" if hour < 12 else "pm"
    return (
        f"{stamp.strftime('%A')}, {stamp.strftime('%B')} {day}, {year} "
        f"at {hour12}:{minute:02d}{ampm}"
    )


def format_local_pretty(value: datetime | str | None) -> str:
    """Hover title: Monday, July 23, 2026 at 5:30pm (local clock).

    Accepts a UTC datetime, or an already-local display stamp ``YYYY-MM-DD HH:MM``.
    """
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M")
        except ValueError:
            return ""
        return _pretty_from_local_parts(
            parsed.year, parsed.month, parsed.day, parsed.hour, parsed.minute
        )
    local = to_local(value)
    if local is None:
        return ""
    return _pretty_from_local_parts(
        local.year, local.month, local.day, local.hour, local.minute
    )


def same_local_minute(left: datetime | None, right: datetime | None) -> bool:
    """True when both stamps display as the same local minute."""
    a = to_local(left)
    b = to_local(right)
    if a is None or b is None:
        return False
    return a.replace(second=0, microsecond=0) == b.replace(second=0, microsecond=0)
