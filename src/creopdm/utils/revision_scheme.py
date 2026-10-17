"""Revision scheme: the one place that knows what comes after revision "A".

Default scheme is alphabetic (A, B, … Z, AA, AB, …). Callers never build a revision string
themselves; the server asks this module so the rule can later become configurable.
"""

from __future__ import annotations

from creopdm.constants import DEFAULT_REVISION
from creopdm.exceptions import ReviseRevisionSchemeError


def get_initial_revision() -> str:
    return DEFAULT_REVISION


def validate_revision(revision: str | None) -> str:
    """Return the revision when it is a valid alphabetic revision, else raise."""
    text = (revision or "").strip()
    if not text or not text.isascii() or not text.isalpha() or text != text.upper():
        raise ReviseRevisionSchemeError(
            f'"{revision}" is not a valid revision for the alphabetic scheme (A, B, … Z, AA, …).',
            details={"revision": revision or ""},
        )
    return text


def get_next_revision(revision: str | None) -> str:
    """A → B, Z → AA, AZ → BA, ZZ → AAA (spreadsheet-column order)."""
    chars = list(validate_revision(revision))
    i = len(chars) - 1
    while i >= 0:
        if chars[i] != "Z":
            chars[i] = chr(ord(chars[i]) + 1)
            return "".join(chars)
        chars[i] = "A"
        i -= 1
    return "A" + "".join(chars)
