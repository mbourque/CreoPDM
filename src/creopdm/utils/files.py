"""Filesystem helpers. Read-only flags are convenience, not the lock authority."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from creopdm.exceptions import PathValidationError


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


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        set_file_writable(destination)
    shutil.copy2(source, destination)


def is_writable(path: Path) -> bool:
    return path.exists() and os.access(path, os.W_OK)
