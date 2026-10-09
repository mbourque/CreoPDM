"""Stable History comments for Add / import batches."""

from __future__ import annotations


def resolve_add_commit_message(
    comment: str | None,
    *,
    planned_count: int,
    batch_total: int | None = None,
    single_filename: str | None = None,
    first_check_in: bool = False,
) -> str:
    """Return the Git / History comment for an Add commit.

    When ``comment`` is blank, prefer ``batch_total`` (full picker count) over
    ``planned_count`` (this request/chunk). Chunked uploads of 5 must not invent
    ``Add 5 files`` for a 935-file Add.

    When ``first_check_in`` is true (product had no vault objects yet), prefix
    with ``First check in:`` so History reads e.g. ``First check in: Add 26 files``.
    """
    raw = (comment or "").strip()
    if raw:
        return raw
    try:
        total = int(batch_total or 0)
    except (TypeError, ValueError):
        total = 0
    if total <= 0:
        try:
            total = int(planned_count or 0)
        except (TypeError, ValueError):
            total = 0
    if total <= 0:
        base = "Add files"
    elif total == 1:
        name = (single_filename or "").strip()
        base = f"Add {name}" if name else "Add files"
    else:
        base = f"Add {total} files"
    if first_check_in:
        return f"First check in: {base}"
    return base
