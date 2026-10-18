"""Rebuild a baseline on this PC: exact versions, hash-verified, read-only, in its own folder.

A baseline never goes into the product's normal workspace folder (that is where check-outs and
unsaved changes live). It gets ``<agent root>/_baselines/<product>/<baseline folder>/`` holding
only the exact versions the baseline captured. Everything is staged and verified first: if any
file is missing or fails its SHA-256 nothing is installed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import stat
import subprocess
import time
import uuid
from pathlib import Path

import httpx

from creopdm_agent.trash import move_to_trash

logger = logging.getLogger("creopdm_agent")

BASELINES_DIRNAME = "_baselines"
MARKER_NAME = ".creopdm-baseline.json"


class BaselineWorkspaceError(Exception):
    """A refusal with an HTTP status and structured detail for the caller."""

    def __init__(self, status: int, message: str, **extra: object) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra

    def detail(self) -> dict[str, object]:
        return {"message": self.message, **self.extra}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _set_read_only(path: Path) -> None:
    os.chmod(path, stat.S_IREAD if os.name == "nt" else 0o444)


def _set_writable(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def _is_windows() -> bool:
    return os.name == "nt"


def _windows_user() -> str:
    try:
        out = subprocess.run(
            ["whoami"], capture_output=True, text=True, check=False,
            # The tray has no console: without an explicit stdin Windows reports "the handle is
            # invalid" and the call fails. CREATE_NO_WINDOW avoids a console flash.
            stdin=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
        name = (out.stdout or "").strip()
        if name:
            return name
    except OSError:
        pass
    domain = os.environ.get("USERDOMAIN", "")
    user = os.environ.get("USERNAME", "")
    return f"{domain}{chr(92)}{user}" if domain and user else user


_last_lock_error = ""


def _icacls(*args: str) -> bool:
    global _last_lock_error
    try:
        result = subprocess.run(
            ["icacls", *args], capture_output=True, text=True, check=False,
            stdin=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
    except OSError as exc:
        logger.warning("icacls could not run: %s", exc)
        _last_lock_error = f"icacls could not run: {exc}"
        return False
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        logger.warning("icacls %s failed: %s", " ".join(args), message)
        _last_lock_error = message or f"icacls exited with {result.returncode}"
    return result.returncode == 0


def _directories(dest_root: Path) -> list[Path]:
    if not dest_root.is_dir():
        return []
    return [dest_root, *sorted(p for p in dest_root.rglob("*") if p.is_dir())]


def lock_directories(dest_root: Path) -> bool:
    """Stop NEW files being created in the baseline folder (Windows).

    A read-only file is not enough: Creo's Save never overwrites, it writes a new numbered
    version (``shaft.prt.2``) beside the original, and a read-only file does not stop that. So the
    folders themselves refuse "add file" and "add subfolder" for this user. Existing files can
    still be read and opened. Returns True when every folder was locked (always False off
    Windows, where the read-only flags are all there is).
    """
    global _last_lock_error
    _last_lock_error = ""
    if not _is_windows():
        return False
    user = _windows_user()
    ok = bool(user)
    if not ok:
        _last_lock_error = "could not determine the Windows user"
    for directory in _directories(dest_root):
        ok = _icacls(str(directory), "/deny", f"{user}:(WD,AD)") and ok
    return ok


def unlock_directories(dest_root: Path) -> None:
    """Lift the folder lock (before replacing files or deleting the folder)."""
    if not _is_windows():
        return
    user = _windows_user()
    for directory in _directories(dest_root):
        _icacls(str(directory), "/remove:d", user)


def baseline_dir(root: Path, product_key: str, folder: str) -> Path:
    """``<root>/_baselines/<product>/<folder>``, never outside ``root``."""
    from creopdm_agent.server import _safe_segment

    base = root.resolve()
    target = (
        base
        / BASELINES_DIRNAME
        / _safe_segment(product_key, "local")
        / _safe_segment(folder, "baseline")
    ).resolve()
    try:
        target.relative_to(base / BASELINES_DIRNAME)
    except ValueError as exc:
        raise BaselineWorkspaceError(403, "Refusing to use a path outside the local workspace.") from exc
    return target


def _dest_relative(item: dict) -> Path:
    from creopdm_agent.server import _cache_dest_relative

    filename = str(item.get("filename") or "")
    return _cache_dest_relative(item.get("relative_path"), filename)


def _marker(dest_root: Path) -> dict | None:
    path = dest_root / MARKER_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _extras(dest_root: Path, expected: set[str]) -> list[str]:
    found: list[str] = []
    if not dest_root.is_dir():
        return found
    for path in sorted(dest_root.rglob("*")):
        if not path.is_file() or path.name == MARKER_NAME:
            continue
        rel = path.relative_to(dest_root).as_posix()
        if rel not in expected:
            found.append(rel)
    return found


def reconstruct(
    root: Path,
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    manifest: dict,
    product_key: str,
    *,
    overwrite: bool = False,
) -> dict:
    """Install the manifest's exact files. All or nothing; returns what happened."""
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise BaselineWorkspaceError(400, "The baseline manifest has no files.")
    folder = str(manifest.get("folder") or "").strip()
    if not folder:
        raise BaselineWorkspaceError(400, "The baseline manifest has no folder name.")
    dest_root = baseline_dir(root, product_key, folder)

    plan: list[tuple[dict, Path, str]] = []
    for item in files:
        digest = str(item.get("sha256") or "").strip().lower()
        if not digest or not item.get("content_path"):
            raise BaselineWorkspaceError(
                400, f"The manifest entry for {item.get('filename')} has no hash or content path."
            )
        rel = _dest_relative(item)
        target = (dest_root / rel).resolve()
        try:
            target.relative_to(dest_root)
        except ValueError as exc:
            raise BaselineWorkspaceError(403, "Refusing a file path outside the baseline folder.") from exc
        plan.append((item, target, digest))

    # Files already there: the right content stays, different content is a conflict the user
    # must confirm (it can only be a local edit or damage; the baseline folder is read-only).
    keep: set[str] = set()
    conflicts: list[str] = []
    for item, target, digest in plan:
        if not target.is_file():
            continue
        if sha256_file(target) == digest:
            keep.add(target.as_posix())
        else:
            conflicts.append(target.relative_to(dest_root).as_posix())
    if conflicts and not overwrite:
        raise BaselineWorkspaceError(
            409,
            f"{len(conflicts)} file{'s' if len(conflicts) != 1 else ''} in the baseline folder "
            "differ from the baseline. Nothing was changed.",
            conflicts=conflicts,
            path=str(dest_root),
        )

    stage = dest_root.parent / f".{dest_root.name}.partial-{uuid.uuid4().hex[:8]}"
    failures: list[dict] = []
    downloaded: list[tuple[Path, Path]] = []
    try:
        for item, target, digest in plan:
            if target.as_posix() in keep:
                continue
            staged = stage / target.relative_to(dest_root)
            staged.parent.mkdir(parents=True, exist_ok=True)
            name = str(item.get("filename") or target.name)
            try:
                response = client.get(f"{base_url}{item['content_path']}", headers=headers)
            except httpx.HTTPError as exc:
                failures.append({"file": name, "reason": f"CreoPDM could not be reached: {exc}"})
                break
            if response.status_code >= 400:
                reason = f"CreoPDM returned {response.status_code}"
                try:
                    body = response.json()
                    message = (body.get("error") or {}).get("message") or body.get("detail")
                    if message:
                        reason = str(message)
                except ValueError:
                    pass
                failures.append({"file": name, "reason": reason})
                continue
            actual = hashlib.sha256(response.content).hexdigest()
            if actual != digest:
                failures.append(
                    {
                        "file": name,
                        "reason": "downloaded content does not match the expected SHA-256 and was rejected",
                    }
                )
                continue
            staged.write_bytes(response.content)
            downloaded.append((staged, target))
        if failures:
            raise BaselineWorkspaceError(
                502,
                f"The baseline was not installed: {len(failures)} file"
                f"{'s' if len(failures) != 1 else ''} could not be provided exactly "
                f"({'; '.join(f['file'] + ' — ' + f['reason'] for f in failures[:3])}).",
                failures=failures,
            )
        # Everything verified: now (and only now) install. The folder lock is lifted just for this.
        unlock_directories(dest_root)
        for staged, target in downloaded:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                _set_writable(target)
            os.replace(staged, target)
        for _item, target, _digest in plan:
            _set_read_only(target)
        marker_path = dest_root / MARKER_NAME
        if marker_path.exists():
            _set_writable(marker_path)
        dest_root.mkdir(parents=True, exist_ok=True)
        marker_path.write_text(
            json.dumps(
                {
                    "baseline": manifest.get("baseline"),
                    "product": manifest.get("product"),
                    "folder": folder,
                    "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "files": [
                        {"path": target.relative_to(dest_root).as_posix(), "sha256": digest}
                        for _item, target, digest in plan
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        # Locked again whatever happened: a half-finished install must not leave it open.
        locked = lock_directories(dest_root) if (dest_root / MARKER_NAME).is_file() else False

    expected = {target.relative_to(dest_root).as_posix() for _i, target, _d in plan}
    return {
        "path": str(dest_root),
        "folder": folder,
        "files_total": len(plan),
        "downloaded": len(downloaded),
        "kept": len(keep),
        "replaced": len(conflicts),
        "extras": _extras(dest_root, expected),
        "read_only": True,
        "folder_locked": locked,
        # Why the lock failed (empty when it worked or is not applicable off Windows).
        "lock_error": "" if locked else _last_lock_error,
    }


def check(root: Path, product_key: str, folder: str) -> dict:
    """Is the baseline folder still exactly the baseline? Missing, changed and extra files."""
    dest_root = baseline_dir(root, product_key, folder)
    marker = _marker(dest_root)
    if marker is None:
        return {"installed": False, "path": str(dest_root), "missing": [], "modified": [], "extras": []}
    missing: list[str] = []
    modified: list[str] = []
    expected: set[str] = set()
    for entry in marker.get("files") or []:
        rel = str(entry.get("path") or "")
        expected.add(rel)
        path = dest_root / rel
        if not path.is_file():
            missing.append(rel)
        elif sha256_file(path) != str(entry.get("sha256") or ""):
            modified.append(rel)
    return {
        "installed": True,
        "path": str(dest_root),
        "missing": missing,
        "modified": modified,
        "extras": _extras(dest_root, expected),
    }


def _remove_empty_dir(path: Path) -> bool:
    """Remove an empty folder tree; False when something (Creo, Explorer) still holds it."""
    for sub in sorted((p for p in path.rglob("*") if p.is_dir()), reverse=True):
        try:
            sub.rmdir()
        except OSError:
            pass
    try:
        path.rmdir()
    except OSError:
        return False
    return True


def open_folder(root: Path, product_key: str, folder: str, opener) -> dict:
    """Show a downloaded baseline copy in Explorer (``opener`` is the platform's folder opener)."""
    dest_root = baseline_dir(root, product_key, folder)
    if not dest_root.is_dir():
        raise BaselineWorkspaceError(
            404, "This baseline has not been downloaded to this PC.", path=str(dest_root)
        )
    opener(dest_root)
    return {"opened": True, "path": str(dest_root)}


def _prune_empty_parents(root: Path, dest_root: Path) -> None:
    """Drop ``_baselines/<product>`` and ``_baselines`` once nothing is left in them."""
    stop = (root.resolve() / BASELINES_DIRNAME)
    current = dest_root.parent
    while current != stop.parent:
        try:
            if current.is_dir() and not any(current.iterdir()):
                current.rmdir()
            else:
                break
        except OSError:
            break
        if current == stop:
            break
        current = current.parent


def remove(root: Path, product_key: str, folder: str) -> dict:
    """Delete one baseline folder (only one this agent installed: it must carry the marker)."""
    dest_root = baseline_dir(root, product_key, folder)
    if not dest_root.is_dir():
        return {"removed": False, "path": str(dest_root)}
    if _marker(dest_root) is None:
        # A leftover with no files in it (for example after an interrupted delete) is safe to clear.
        has_files = any(p.is_file() for p in dest_root.rglob("*"))
        if has_files:
            raise BaselineWorkspaceError(
                409,
                f"The folder {dest_root} has files but was not installed as a baseline by CreoPDM "
                f"(it has no {MARKER_NAME}), so it was not removed. Delete it yourself if you are sure.",
                path=str(dest_root),
            )
    unlock_directories(dest_root)
    try:
        move_to_trash(dest_root)
    except OSError as exc:
        # Creo (as its working directory) or Explorer can hold the folder itself open while its
        # contents can still go: clear what we can and tell the user about the folder.
        logger.warning("Could not remove %s as a whole (%s); clearing its contents", dest_root, exc)
        from creopdm_agent.trash import clear_directory_contents

        clear_directory_contents(dest_root)
    if dest_root.exists():  # the Recycle Bin call can also leave an empty shell behind
        shutil.rmtree(dest_root, ignore_errors=True)
    if dest_root.exists():
        _remove_empty_dir(dest_root)
    in_use = dest_root.exists()
    if not in_use:
        _prune_empty_parents(root, dest_root)
    return {"removed": True, "path": str(dest_root), "folder_in_use": in_use}
