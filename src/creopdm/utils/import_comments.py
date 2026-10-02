"""Stable History comments for Add / import batches."""

from __future__ import annotations


def resolve_add_commit_message(
    comment: str | None,
    *,
    planned_count: int,
    batch_total: int | None = None,
    single_filename: str | None = None,
) -> str:
    """Return the Git / History comment for an Add commit.

    When ``comment`` is blank, prefer ``batch_total`` (full picker count) over
    ``planned_count`` (this request/chunk). Chunked uploads of 5 must not invent
    ``Add 5 files`` for a 935-file Add.
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
        return "Add files"
    if total == 1:
        name = (single_filename or "").strip()
        return f"Add {name}" if name else "Add files"
    return f"Add {total} files"
