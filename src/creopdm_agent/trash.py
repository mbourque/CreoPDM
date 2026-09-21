"""Move local agent-cache files to the OS trash when possible."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def move_to_trash(path: Path) -> None:
    """Send ``path`` to the Recycle Bin on Windows; otherwise delete permanently.

    Under pytest, always unlinks so agent tests do not fill the Recycle Bin.
    If the Shell recycle call fails, falls back to a permanent delete.
    """
    target = Path(path)
    if not target.exists():
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        target.unlink()
        return
    if sys.platform == "win32":
        try:
            _windows_recycle_bin(target)
        except OSError:
            target.unlink()
            return
        if target.exists():
            target.unlink()
        return
    target.unlink()


def _windows_recycle_bin(path: Path) -> None:
    import ctypes
    from ctypes import wintypes

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

    abs_path = str(path.resolve())
    # Double-null-terminated path list required by SHFileOperationW.
    buf = ctypes.create_unicode_buffer(len(abs_path) + 2)
    buf.value = abs_path

    op = SHFILEOPSTRUCTW()
    op.wFunc = fo_delete
    op.pFrom = ctypes.cast(buf, wintypes.LPCWSTR)
    op.fFlags = fof_allowundo | fof_noconfirmation | fof_noerrorui | fof_silent

    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result:
        raise OSError(result, f"SHFileOperationW failed for {abs_path}")
    if op.fAnyOperationsAborted:
        raise OSError("Recycle Bin operation was aborted.")
