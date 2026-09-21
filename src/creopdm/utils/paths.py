"""Filesystem path validation. Never treat user paths as trusted."""

from __future__ import annotations

import re
from pathlib import Path

from creopdm.exceptions import PathValidationError

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def normalize_fs_path(path: str | Path) -> Path:
    """Expand and resolve a filesystem path."""
    return Path(path).expanduser().resolve()


def assert_safe_relative_path(relative: str) -> Path:
    """Reject absolute paths, drive letters, and parent-directory traversal."""
    if not relative or not relative.strip():
        raise PathValidationError("A relative file path is required.")
    raw = relative.replace("\\", "/").strip()
    # Drive letters are absolute on Windows; Path() treats them as relative on Linux.
    if _WINDOWS_DRIVE.match(raw):
        raise PathValidationError("Repository file paths must be relative.")
    if raw.startswith("/") or raw.startswith("\\"):
        raise PathValidationError("Repository file paths must be relative.")
    candidate = Path(raw)
    if candidate.is_absolute() or candidate.drive:
        raise PathValidationError("Repository file paths must be relative.")
    parts = candidate.parts
    if any(part in (".", "..") for part in parts):
        raise PathValidationError("Path traversal is not allowed.")
    if any(part.startswith("/") for part in parts):
        raise PathValidationError("Invalid path component.")
    return Path(*parts)


def ensure_within(base: Path, target: Path) -> Path:
    """Ensure target resolves inside base; raise otherwise."""
    base_resolved = normalize_fs_path(base)
    target_resolved = normalize_fs_path(target)
    try:
        target_resolved.relative_to(base_resolved)
    except ValueError as exc:
        raise PathValidationError("Path escapes the project repository.") from exc
    return target_resolved


def is_within(base: Path, target: Path) -> bool:
    try:
        ensure_within(base, target)
        return True
    except PathValidationError:
        return False


def require_within_project(location: Path, target: Path) -> Path:
    """Resolve target and require it to sit inside location."""
    try:
        return ensure_within(location, target)
    except PathValidationError as exc:
        raise PathValidationError(
            "Choose files or folders inside the project location.",
            details={"path": str(target), "location": str(location)},
        ) from exc


def validate_project_location(path: str | Path) -> Path:
    """Validate a user-chosen project repository location."""
    if not str(path).strip():
        raise PathValidationError("A project location is required.")
    resolved = normalize_fs_path(path)
    if resolved.exists() and resolved.is_file():
        raise PathValidationError("Project location must be a directory.")
    parent = resolved.parent
    if not parent.exists():
        raise PathValidationError(f"Parent directory does not exist: {parent}")
    if not parent.is_dir():
        raise PathValidationError("Project location parent is not a directory.")
    return resolved


def sanitize_filename(name: str) -> str:
    """Return a filename with no directory components."""
    cleaned = Path(name.replace("\\", "/")).name.strip()
    if not cleaned or cleaned in (".", ".."):
        raise PathValidationError("Invalid filename.")
    if any(ch in cleaned for ch in '<>:"|?*'):
        raise PathValidationError("Filename contains invalid characters.")
    return cleaned
