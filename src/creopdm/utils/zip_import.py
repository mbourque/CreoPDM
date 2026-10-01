"""Safe zip extract + path planning for Add ▾ → Compressed data…"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import PathValidationError, ValidationAppError
from creopdm.utils.paths import assert_safe_relative_path

# Hard cap for uploaded zip body (plan: 2 GB).
MAX_ZIP_IMPORT_BYTES = 2 * 1024 * 1024 * 1024

_SKIP_ZIP_DIR_NAMES = frozenset(
    {name.lower() for name in (".git", ".creopdm", "__pycache__", "__macosx")}
)
_SKIP_ZIP_FILE_NAMES = frozenset(
    {name.lower() for name in (".ds_store", "thumbs.db", "desktop.ini")}
)
_RESERVED_VAULT_PARTS = frozenset({".git", ".creopdm"})


def assert_zip_filename(name: str) -> str:
    """Return a safe basename; require a .zip suffix."""
    leaf = Path(name or "").name.strip()
    if not leaf:
        raise ValidationAppError("A zip filename is required.")
    if not leaf.lower().endswith(".zip"):
        raise ValidationAppError("Only .zip files are supported.")
    return leaf


def extract_zip_safely(zip_path: Path, dest_dir: Path) -> int:
    """Extract zip entries under dest_dir. Returns file count. Rejects slip / encrypted."""
    target_resolved = dest_dir.resolve()
    extracted = 0
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.flag_bits & 0x1:
                    raise ValidationAppError(
                        "Password-protected zip files are not supported."
                    )
                raw = str(info.filename or "").replace("\\", "/")
                parts = [part for part in raw.split("/") if part and part not in {".", ".."}]
                if not parts:
                    continue
                if any(part.lower() in _SKIP_ZIP_DIR_NAMES for part in parts[:-1]):
                    continue
                if parts and parts[0].lower() in _SKIP_ZIP_DIR_NAMES:
                    continue
                leaf = parts[-1]
                if info.is_dir() or raw.endswith("/"):
                    continue
                if leaf.lower() in _SKIP_ZIP_FILE_NAMES or leaf.startswith("."):
                    continue
                dest = dest_dir.joinpath(*parts)
                try:
                    dest.resolve().relative_to(target_resolved)
                except ValueError as exc:
                    raise PathValidationError(
                        f"Unsafe zip entry: {info.filename}",
                        details={"entry": info.filename},
                    ) from exc
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out)
                extracted += 1
    except zipfile.BadZipFile as exc:
        raise ValidationAppError("That file is not a valid zip archive.") from exc
    except RuntimeError as exc:
        # zipfile raises RuntimeError for encrypted members on some Python builds.
        message = str(exc).lower()
        if "encrypted" in message or "password" in message:
            raise ValidationAppError(
                "Password-protected zip files are not supported."
            ) from exc
        raise
    return extracted


def strip_single_zip_root(extract_dir: Path) -> Path:
    """If the zip has one top-level folder only, import from inside it."""
    if not extract_dir.is_dir():
        return extract_dir
    children = [
        path
        for path in extract_dir.iterdir()
        if path.name.lower() not in _SKIP_ZIP_DIR_NAMES and not path.name.startswith(".")
    ]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extract_dir


def normalize_zip_parent_folder(parent_folder: str = "") -> str:
    """Safe vault-relative parent for zip import, or '' for product root."""
    parent = (parent_folder or "").strip().replace("\\", "/").strip("/")
    if not parent:
        return ""
    path = assert_safe_relative_path(parent)
    parts_lower = {part.lower() for part in path.parts}
    if parts_lower & _RESERVED_VAULT_PARTS:
        raise PathValidationError(
            "That location is reserved for CreoPDM.",
            details={"parent_folder": parent},
        )
    if parts_lower & _SKIP_ZIP_DIR_NAMES:
        raise PathValidationError(
            "That folder cannot be used as an import destination.",
            details={"parent_folder": parent},
        )
    return path.as_posix()


def plan_zip_import_jobs(
    extract_dir: Path,
    *,
    parent_folder: str = "",
    purgeable_extensions: list[str] | None = None,
    ignore_patterns: list[str] | None = None,
) -> list[tuple[Path, str, str]]:
    """Build (source, stored_name, relative) jobs under parent_folder after strip-root."""
    import_root = strip_single_zip_root(extract_dir)
    selected = CreoFileManager.list_latest_in_folder(
        import_root,
        purgeable_extensions,
        ignore_patterns,
        recursive=True,
    )
    parent = normalize_zip_parent_folder(parent_folder)
    jobs: list[tuple[Path, str, str]] = []
    for path in selected:
        try:
            inner = path.relative_to(import_root).as_posix()
        except ValueError:
            inner = path.name
        relative = f"{parent}/{inner}" if parent else inner
        safe = assert_safe_relative_path(relative)
        if {part.lower() for part in safe.parts} & _RESERVED_VAULT_PARTS:
            raise PathValidationError(
                "That location is reserved for CreoPDM.",
                details={"relative_path": relative},
            )
        jobs.append((path, path.name, safe.as_posix()))
    return jobs


def extract_zip_to_temp(zip_path: Path) -> tuple[Path, Path]:
    """Create a temp extract dir, extract into it. Caller must rmtree the parent."""
    parent = Path(tempfile.mkdtemp(prefix="creopdm-zip-"))
    dest = parent / "extracted"
    dest.mkdir(parents=True, exist_ok=True)
    extract_zip_safely(zip_path, dest)
    return parent, dest
