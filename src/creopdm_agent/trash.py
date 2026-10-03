"""Move local agent-cache files to the OS trash when possible."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def move_to_trash(path: Path) -> None:
    """Send ``path`` to the Recycle Bin on Windows; otherwise delete permanently.

    Under pytest, always removes so agent tests do not fill the Recycle Bin.
    If the Shell recycle call fails, falls back to a permanent delete.
    """
    import shutil

    target = Path(path)
    if not target.exists():
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=False)
        else:
            target.unlink()
        return
    if sys.platform == "win32":
        try:
            _windows_recycle_bin(target)
        except OSError:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        return
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


def clear_directory_contents(directory: Path) -> tuple[int, list[str]]:
    """Trash all direct children of ``directory`` in one shot; leave the folder.

    Creo's working directory often locks the workspace folder (WinError 32) while
    still allowing children to be removed. Returns ``(removed_count, failures)``.
    """
    import shutil

    root = Path(directory)
    if not root.is_dir():
        return 0, []
    children = sorted(root.iterdir(), key=lambda p: p.name.lower())
    if not children:
        return 0, []

    # Pytest / non-Windows: permanent delete (still one pass, not per-file Shell).
    if os.environ.get("PYTEST_CURRENT_TEST") or sys.platform != "win32":
        removed = 0
        failed: list[str] = []
        for child in children:
            label = child.name
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=False)
                else:
                    child.unlink()
                if child.exists():
                    failed.append(f"{label}: still present after delete")
                else:
                    removed += 1
            except OSError as exc:
                failed.append(f"{label}: {exc}")
        return removed, failed

    # Windows: one SHFileOperation for every top-level child.
    try:
        _windows_recycle_bin_many(children)
    except OSError:
        # Fall back to per-child so we clear what we can and report the rest.
        removed = 0
        failed = []
        for child in children:
            label = child.name
            try:
                move_to_trash(child)
                if child.exists():
                    failed.append(f"{label}: still present after delete")
                else:
                    removed += 1
            except OSError as exc:
                failed.append(f"{label}: {exc}")
        return removed, failed

    failed = []
    removed = 0
    for child in children:
        if child.exists():
            # Recycle left something behind (locked file) — try hard delete once.
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            except OSError as exc:
                failed.append(f"{child.name}: {exc}")
                continue
            if child.exists():
                failed.append(f"{child.name}: still present after delete")
            else:
                removed += 1
        else:
            removed += 1
    return removed, failed


def _windows_recycle_bin(path: Path) -> None:
    """Recycle a single path (compat for callers/tests)."""
    _windows_recycle_bin_many([path])


def _windows_recycle_bin_many(paths: list[Path]) -> None:
    """Recycle one or more paths in a single SHFileOperationW call."""
    import ctypes
    from ctypes import wintypes

    existing = [Path(p).resolve() for p in paths if Path(p).exists()]
    if not existing:
        return

    fo_delete = 3
    fof_silent = 0x0004
    fof_noconfirmation = 0x0010
    fof_allowundo = 0x0040
    fof_noerrorui = 0x0400

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.WORD),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    # Double-null-terminated list: path\0path\0\0
    joined = "\0".join(str(p) for p in existing) + "\0"
    buf = ctypes.create_unicode_buffer(joined)

    op = SHFILEOPSTRUCTW()
    op.wFunc = fo_delete
    op.pFrom = ctypes.cast(buf, wintypes.LPCWSTR)
    op.fFlags = fof_allowundo | fof_noconfirmation | fof_noerrorui | fof_silent

    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result:
        raise OSError(result, f"SHFileOperationW failed for {len(existing)} path(s)")
    if op.fAnyOperationsAborted:
        raise OSError("Recycle Bin operation was aborted.")
