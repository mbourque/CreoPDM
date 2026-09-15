"""Filesystem helpers. Read-only flags are convenience, not the lock authority."""

from __future__ import annotations

import os
import shutil
import stat
import time
from pathlib import Path

from creopdm.exceptions import PathValidationError
from creopdm.logging_setup import get_logger

logger = get_logger("files")


def set_file_readonly(path: Path) -> None:
    """Best-effort read-only attribute. Database locks remain authoritative."""
    if not path.exists():
        raise PathValidationError(f"Cannot set read-only on missing file: {path}")
    mode = path.stat().st_mode
    path.chmod(mode & ~stat.S_IWRITE)


def set_file_writable(path: Path) -> None:
    """Best-effort writable attribute. Database locks remain authoritative."""
    if not path.exists():
        raise PathValidationError(f"Cannot set writable on missing file: {path}")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IWRITE | stat.S_IREAD)


def copy_file(source: Path, destination: Path) -> bool:
    """Copy source to destination.

    Returns True only when this call created a new file. Same-path copies and
    overwrites return False so callers must not delete destination on rollback.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = source.resolve()
    dest = destination.resolve()
    if src == dest:
        return False
    created = not destination.exists()
    if destination.exists():
        set_file_writable(destination)
    shutil.copy2(source, destination)
    return created


def is_writable(path: Path) -> bool:
    return path.exists() and os.access(path, os.W_OK)


def remove_file(path: Path) -> bool:
    """Delete a file. Returns True if it was present."""
    if not path.is_file():
        return False
    set_file_writable(path)
    path.unlink()
    return True


def _cwd_inside(path: Path) -> bool:
    try:
        resolved = path.resolve()
        cwd = Path.cwd().resolve()
    except OSError:
        return False
    if cwd == resolved:
        return True
    try:
        return cwd.is_relative_to(resolved)
    except AttributeError:
        return str(cwd).startswith(str(resolved) + os.sep)


def _leave_directory(path: Path) -> None:
    """Windows cannot delete a folder that is the process current directory."""
    if not _cwd_inside(path):
        return
    try:
        os.chdir(Path.home())
    except OSError:
        pass


def remove_tree(path: Path) -> bool:
    """Delete a directory tree. Returns True if the path is gone.

    Locked Windows folders are retried, then left behind. Callers should treat
    a leftover path as a warning, not a hard failure, when the tree is disposable.
    """
    if not path.exists():
        return True
    _leave_directory(path)

    def _onexc(func, name, exc):
        target = Path(name)
        try:
            if target.exists():
                target.chmod(stat.S_IWRITE | stat.S_IREAD)
            func(name)
        except OSError:
            return

    last_exc: BaseException | None = None
    for attempt in range(6):
        try:
            if not path.exists():
                return True
            shutil.rmtree(path, onexc=_onexc)
            if not path.exists():
                return True
        except OSError as exc:
            last_exc = exc
        time.sleep(0.15 * (attempt + 1))
    if path.exists():
        logger.warning("Could not delete %s: %s", path, last_exc)
        return False
    return True
