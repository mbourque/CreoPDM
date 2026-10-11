"""Helpers for repo-local pytest basetemp folders (``pytest-tmp*``)."""

from __future__ import annotations

import gc
import os
import shutil
import stat
import time
from pathlib import Path


def _unlock_and_retry(func, path, _exc=None):
    """Make read-only paths writable so rmtree can finish on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        return
    try:
        func(path)
    except OSError:
        pass


def _rmtree_force(path: Path) -> bool:
    """Remove a directory tree; return True if it is gone."""
    if not path.exists():
        return True
    try:
        shutil.rmtree(path, onexc=_unlock_and_retry)
    except TypeError:
        # Python < 3.12
        try:
            shutil.rmtree(path, onerror=_unlock_and_retry)
        except OSError:
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


def cleanup_stale_pytest_tmp(
    root: Path,
    *,
    keep: Path | None = None,
    retries: int = 3,
    retry_delay_s: float = 0.15,
) -> int:
    """Remove leftover ``pytest-tmp*`` dirs (retries; best-effort on Windows locks)."""
    removed = 0
    keep_resolved = keep.resolve() if keep is not None else None
    # Release SQLite / TestClient handles that can block WinError 32 deletes.
    gc.collect()
    attempts = max(1, retries)
    for attempt in range(attempts):
        left = []
        for stale in sorted(root.glob("pytest-tmp*")):
            try:
                if keep_resolved is not None and stale.resolve() == keep_resolved:
                    continue
            except OSError:
                left.append(stale)
                continue
            if _rmtree_force(stale):
                removed += 1
            elif stale.exists():
                left.append(stale)
        if not left:
            break
        if attempt + 1 < attempts:
            time.sleep(retry_delay_s)
            gc.collect()
    return removed
