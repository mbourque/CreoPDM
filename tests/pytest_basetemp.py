"""Helpers for repo-local pytest workdirs (``pytest-tmp*``, ``pytest-cache``)."""

from __future__ import annotations

import gc
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

# Repo-root dirs created by our pytest setup (see pyproject + conftest).
_CACHE_DIR_NAMES = ("pytest-cache", ".pytest_cache")


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


def iter_pytest_workdir_dirs(root: Path):
    """Yield repo-root pytest temp/cache directories that should be scrubbed."""
    yield from sorted(root.glob("pytest-tmp*"))
    for name in _CACHE_DIR_NAMES:
        path = root / name
        if path.exists():
            yield path


def cleanup_stale_pytest_tmp(
    root: Path,
    *,
    keep: Path | None = None,
    retries: int = 3,
    retry_delay_s: float = 0.15,
) -> int:
    """Remove ``pytest-tmp*`` and ``pytest-cache`` (retries; Windows lock-friendly)."""
    removed = 0
    keep_resolved = keep.resolve() if keep is not None else None
    # Release SQLite / TestClient handles that can block WinError 32 deletes.
    gc.collect()
    attempts = max(1, retries)
    for attempt in range(attempts):
        left = []
        for stale in iter_pytest_workdir_dirs(root):
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


def schedule_deferred_pytest_tmp_cleanup(root: Path, *, delay_s: float = 2.0) -> None:
    """
    Finish deletes after this process exits.

    On Windows, SQLite often still holds ``creopdm.db`` during sessionfinish;
    a short-lived child waits for handles to drop, then scrubs the repo root.
    """
    root_s = str(root.resolve())
    # Keep the child tiny and dependency-free (no importing tests.*).
    code = (
        "import sys,time,shutil\n"
        "from pathlib import Path\n"
        "r=Path(sys.argv[1])\n"
        f"time.sleep({float(delay_s)!r})\n"
        "for p in sorted(r.glob('pytest-tmp*')):\n"
        "    shutil.rmtree(p, ignore_errors=True)\n"
        "for name in ('pytest-cache','.pytest_cache'):\n"
        "    p=r/name\n"
        "    shutil.rmtree(p, ignore_errors=True) if p.exists() else None\n"
    )
    kwargs: dict = {
        "args": [sys.executable, "-c", code, root_s],
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        flags = 0
        for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
            flags |= int(getattr(subprocess, name, 0) or 0)
        if flags:
            kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(**kwargs)
    except OSError:
        # Best-effort — immediate cleanup already ran.
        pass
