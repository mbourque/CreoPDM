"""One way to print mass properties, so the Mass tab and the revision comparison always match."""

from __future__ import annotations

from typing import Any

MASS_SIGNIFICANT_DIGITS = 6


def format_mass_value(value: Any) -> str:
    """A number with 6 significant digits (``0.000262951``, ``196232``, ``1.34e-09``).

    Lists (centre of gravity, principal moments) come back as ``[a, b, c]``. Anything that is not a
    number is shown as text. Used by the Details Mass tab / Overview AND by the compare text.
    """
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(format_mass_value(item) for item in value) + "]"
    if isinstance(value, bool):
        return str(value)
    try:
        return f"{float(value):.{MASS_SIGNIFICANT_DIGITS}g}"
    except (TypeError, ValueError):
        return str(value).strip()
