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
    """Trash every file and subfolder under ``directory``; leave the folder itself.

    Clears *all* contents (CAD, cache index, nested folders — anything).
    Creo's working directory often locks the workspace folder (WinError 32)
    while still allowing children to be removed.

    Returns ``(removed_count, failures)``. Failures are relative paths that
    could not be removed (usually locked by Creo).
    """
    import shutil

    root = Path(directory)
    if not root.is_dir():
        return 0, []
    children = sorted(root.iterdir(), key=lambda p: p.name.lower())
    if not children:
        return 0, []

    removed = 0
    failed: list[str] = []

    # Pytest / non-Windows: permanent delete (still one pass, not per-file Shell).
    if os.environ.get("PYTEST_CURRENT_TEST") or sys.platform != "win32":
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
        sweep_removed, sweep_failed = _hard_purge_remaining(root)
        removed += sweep_removed
        failed.extend(sweep_failed)
        return removed, failed

    # Windows: one SHFileOperation for every top-level child (all names / types).
    try:
        _windows_recycle_bin_many(children)
    except OSError:
        # Fall back to per-child so we clear what we can and report the rest.
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
        sweep_removed, sweep_failed = _hard_purge_remaining(root)
        removed += sweep_removed
        failed.extend(sweep_failed)
        return removed, _dedupe_failures(failed)

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

    # Final sweep: anything still nested under root (partial recycle, cache
    # index, locked-then-unlocked leftovers) must go.
    sweep_removed, sweep_failed = _hard_purge_remaining(root)
    removed += sweep_removed
    failed.extend(sweep_failed)
    return removed, _dedupe_failures(failed)


def _dedupe_failures(failed: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in failed:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _hard_purge_remaining(root: Path) -> tuple[int, list[str]]:
    """Permanently delete every remaining file/dir under ``root`` (deepest first)."""
    import shutil

    if not root.is_dir():
        return 0, []
    removed = 0
    failed: list[str] = []
    leftovers = sorted(
        (p for p in root.rglob("*")),
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for path in leftovers:
        if not path.exists():
            continue
        try:
            rel = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            rel = path.name
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
                removed += 1
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    shutil.rmtree(path)
                removed += 1
            else:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError as exc:
            failed.append(f"{rel}: {exc}")
            continue
        if path.exists():
            failed.append(f"{rel}: still present after delete")
    # Top-level again in case rglob missed a stubborn child.
    for child in list(root.iterdir()):
        if not child.exists():
            continue
        label = child.name
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed += 1
        except OSError as exc:
            failed.append(f"{label}: {exc}")
            continue
        if child.exists():
            failed.append(f"{label}: still present after delete")
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
