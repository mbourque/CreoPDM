"""Filesystem helpers. Read-only flags are convenience, not the lock authority."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import time
from pathlib import Path

from creopdm.exceptions import PathValidationError
from creopdm.logging_setup import get_logger

logger = get_logger("files")


def format_byte_size(value: object) -> str:
    """Short size label for the UI: 873 B, 269 KB, 1.2 MB."""
    if value is None or value == "":
        return "—"
    try:
        size = int(value)
    except (TypeError, ValueError):
        return "—"
    if size < 0:
        return "—"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        kb = size / 1024
        text = f"{kb:.0f}" if kb >= 10 else f"{kb:.1f}".rstrip("0").rstrip(".")
        return f"{text} KB"
    mb = size / (1024 * 1024)
    text = f"{mb:.0f}" if mb >= 10 else f"{mb:.1f}".rstrip("0").rstrip(".")
    return f"{text} MB"


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


def _path_id(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def copy_file(source: Path, destination: Path) -> bool:
    """Copy source to destination.

    Returns True only when this call created a new file. Same-path copies and
    overwrites return False so callers must not delete destination on rollback.
    """
    created, _digest, _size = copy_file_hashed(source, destination)
    return created


def copy_file_hashed(source: Path, destination: Path) -> tuple[bool, str, int]:
    """Copy source to destination while hashing. One read of the source."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if _path_id(source) == _path_id(destination):
        digest = hashlib.sha256()
        size = 0
        with destination.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
        return False, digest.hexdigest(), size
    created = not destination.exists()
    if destination.exists():
        set_file_writable(destination)
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as src, destination.open("wb") as dest:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dest.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    try:
        shutil.copystat(source, destination, follow_symlinks=True)
    except OSError:
        logger.debug("Could not copy timestamps from %s", source)
    return created, digest.hexdigest(), size


def is_writable(path: Path) -> bool:
    return path.exists() and os.access(path, os.W_OK)


_FILE_ATTRIBUTE_HIDDEN = 0x2
_INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


def is_hidden(path: Path) -> bool:
    """True when Windows marks the path hidden. Dot names count on other systems."""
    if not path.exists():
        return False
    if os.name != "nt":
        return path.name.startswith(".")
    attrs = getattr(path.stat(), "st_file_attributes", 0)
    return bool(attrs & _FILE_ATTRIBUTE_HIDDEN)


def set_hidden(path: Path, hidden: bool = True) -> None:
    """Best-effort Windows hidden attribute. No-op when the path is missing or not Windows."""
    if os.name != "nt" or not path.exists():
        return
    try:
        import ctypes
        from ctypes import wintypes

        get_attrs = ctypes.windll.kernel32.GetFileAttributesW
        set_attrs = ctypes.windll.kernel32.SetFileAttributesW
        get_attrs.argtypes = [wintypes.LPCWSTR]
        get_attrs.restype = wintypes.DWORD
        set_attrs.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        set_attrs.restype = wintypes.BOOL
        target = str(path.resolve())
        attrs = get_attrs(target)
        if attrs == _INVALID_FILE_ATTRIBUTES:
            return
        if hidden:
            if attrs & _FILE_ATTRIBUTE_HIDDEN:
                return
            next_attrs = attrs | _FILE_ATTRIBUTE_HIDDEN
        else:
            if not (attrs & _FILE_ATTRIBUTE_HIDDEN):
                return
            next_attrs = attrs & ~_FILE_ATTRIBUTE_HIDDEN
        if not set_attrs(target, next_attrs):
            logger.warning("Could not change hidden attribute on %s", path)
    except Exception:
        logger.warning("Could not change hidden attribute on %s", path)


def remove_file(path: Path) -> bool:
    """Delete a file. Returns True if it was present."""
    if not path.is_file():
        return False
    set_file_writable(path)
    path.unlink()
    return True


def prune_empty_dirs(
    start: Path,
    root: Path,
    *,
    reserved_names: frozenset[str] | set[str] | None = None,
) -> None:
    """Delete empty folders from start up to, but not including, root.

    Stops at the first non-empty folder, a reserved name, or a path outside root.
    """
    reserved = {name.lower() for name in (reserved_names or ())}
    try:
        root_resolved = root.resolve()
        current = start.resolve()
    except OSError:
        return
    if current == root_resolved:
        return
    try:
        current.relative_to(root_resolved)
    except ValueError:
        return
    while current != root_resolved:
        if current.name.lower() in reserved:
            break
        try:
            if any(current.iterdir()):
                break
            current.rmdir()
        except OSError:
            break
        current = current.parent


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
