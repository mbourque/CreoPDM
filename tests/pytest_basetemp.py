"""Helpers for repo-local pytest basetemp folders (``pytest-tmp-*``)."""

from __future__ import annotations

import shutil
from pathlib import Path


def cleanup_stale_pytest_tmp(root: Path, *, keep: Path | None = None) -> int:
    """Remove leftover ``pytest-tmp*`` dirs from prior runs (best-effort on Windows)."""
    removed = 0
    keep_resolved = keep.resolve() if keep is not None else None
    for stale in sorted(root.glob("pytest-tmp*")):
        try:
            if keep_resolved is not None and stale.resolve() == keep_resolved:
                continue
        except OSError:
            continue
        shutil.rmtree(stale, ignore_errors=True)
        if not stale.exists():
            removed += 1
    return removed
