"""Move local agent-cache files to the OS trash when possible."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def prepare_path_for_delete(path: Path) -> None:
    """Clear Windows Hidden/System/Readonly on ``path`` (and nested if a folder).

    Single prep used by Clear workspace, Remove-from-Product workspace cleanup,
    and any other ``move_to_trash`` caller — CreoPDM marks older ``.N`` tips
    Hidden, and Shell/unlink can leave them behind without this.
    """
    target = Path(path)
    if not target.exists():
        return
    _clear_windows_delete_attrs(target)
    if target.is_dir():
        for nested in _iter_all_under(target):
            _clear_windows_delete_attrs(nested)


def move_to_trash(path: Path) -> None:
    """Send ``path`` to the Recycle Bin on Windows; otherwise delete permanently.

    Always runs :func:`prepare_path_for_delete` first (Hidden/System/Readonly).
    Under pytest, always removes so agent tests do not fill the Recycle Bin.
    If the Shell recycle call fails, falls back to a permanent delete.
    Raises ``OSError`` when the path still exists after all attempts.
    """
    import shutil
    import stat as stat_mod

    target = Path(path)
    if not target.exists():
        return
    prepare_path_for_delete(target)

    def _force_gone() -> None:
        prepare_path_for_delete(target)
        if not target.exists():
            return
        try:
            mode = target.stat().st_mode
            target.chmod(mode | stat_mod.S_IWRITE | stat_mod.S_IREAD)
        except OSError:
            pass
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=False)
        else:
            target.unlink()

    if os.environ.get("PYTEST_CURRENT_TEST"):
        _force_gone()
        if target.exists():
            raise OSError(f"Still present after delete: {target}")
        return
    if sys.platform == "win32":
        try:
            _windows_recycle_bin(target)
        except OSError:
            _force_gone()
            if target.exists():
                raise
            return
        if target.exists():
            _force_gone()
        if target.exists():
            raise OSError(f"Still present after delete: {target}")
        return
    _force_gone()
    if target.exists():
        raise OSError(f"Still present after delete: {target}")


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

    # Windows: one SHFileOperation for every top-level child (all names / types,
    # including Hidden/System — prepare_path_for_delete clears attrs first).
    for child in children:
        prepare_path_for_delete(child)
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


def _clear_windows_delete_attrs(path: Path) -> None:
    """Drop Readonly/Hidden/System so delete/recycle can take the path."""
    if sys.platform != "win32":
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
        target = str(Path(path).resolve())
        attrs = int(get_attrs(target))
        invalid = 0xFFFFFFFF
        if attrs == invalid:
            return
        file_attribute_readonly = 0x1
        file_attribute_hidden = 0x2
        file_attribute_system = 0x4
        cleaned = attrs & ~(
            file_attribute_readonly | file_attribute_hidden | file_attribute_system
        )
        if cleaned != attrs:
            set_attrs(target, cleaned)
    except OSError:
        return
    except Exception:
        return


# Back-compat name used by older tests / callers.
_clear_windows_hidden_system = _clear_windows_delete_attrs


def _iter_all_under(root: Path) -> list[Path]:
    """Every file/dir under ``root`` (deepest first), including Hidden/System.

    Uses ``os.walk`` so nothing is missed; pair with ``_clear_windows_hidden_system``
    before delete — Windows Hidden attribute (not just ``.`` names) can block recycle.
    """
    if not root.is_dir():
        return []
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
        base = Path(dirpath)
        for name in filenames:
            found.append(base / name)
        for name in dirnames:
            found.append(base / name)
    return found


def _hard_purge_remaining(root: Path) -> tuple[int, list[str]]:
    """Permanently delete every remaining file/dir under ``root`` (deepest first)."""
    import shutil

    if not root.is_dir():
        return 0, []
    removed = 0
    failed: list[str] = []
    for path in _iter_all_under(root):
        if not path.exists():
            continue
        try:
            rel = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            rel = path.name
        prepare_path_for_delete(path)
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
    # Top-level again (iterdir includes hidden/dot names).
    for child in list(root.iterdir()):
        if not child.exists():
            continue
        label = child.name
        prepare_path_for_delete(child)
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
