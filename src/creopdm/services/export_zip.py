"""Build zip archives of vault tip files for Export… downloads."""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from pathlib import Path

from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import PathValidationError, ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product
from creopdm.services.agent_cache_zip import _vault_source
from creopdm.services.workspace_service import WorkspaceService
from creopdm.utils.paths import sanitize_filename

logger = get_logger("export_zip")

_UNSAFE_NAME = re.compile(r"[^\w.\-]+", re.UNICODE)


def export_zip_basename(product: Product, *, selected: bool) -> str:
    """Suggested download filename (no path)."""
    raw = (product.name or product.vault_folder or product.uuid or "product").strip()
    leaf = _UNSAFE_NAME.sub("_", raw).strip("._") or "product"
    suffix = "selection" if selected else "export"
    try:
        return sanitize_filename(f"{leaf}-{suffix}.zip")
    except PathValidationError:
        return f"creopdm-{suffix}.zip"


def _export_arcname(relative: str, source_name: str, extras: list[str] | None) -> str:
    """Zip leaf uses the logical vault name (``shaft.prt``, not ``shaft.prt.1``)."""
    parent = Path(relative.replace("\\", "/")).parent.as_posix()
    leaf = CreoFileManager.canonical_repository_name(source_name, extras)
    if parent in {".", ""}:
        return leaf
    return f"{parent}/{leaf}"


def build_export_zip(
    workspaces: WorkspaceService,
    product: Product,
    objects: list[EngineeringObject],
) -> tuple[Path, int]:
    """Zip vault tip files (nested relative paths). Excludes .git / .creopdm bookkeeping.

    Arc names are always logical CAD names so Export matches the vault tip
    (``shaft.prt``), even when a legacy vault file is still numbered.
    """
    if not objects:
        raise ValidationAppError("Nothing to export.")
    extras = workspaces._cad_extensions()
    fd, raw_name = tempfile.mkstemp(suffix=".zip", prefix="creopdm-export-")
    os.close(fd)
    archive = Path(raw_name)
    written = 0
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zf:
            for obj in objects:
                source = _vault_source(workspaces, product, obj)
                relative = str(obj.relative_path or obj.filename or "").replace("\\", "/")
                parts = [part for part in Path(relative).parts if part not in (".",)]
                if any(part.lower() in {".git", ".creopdm"} for part in parts):
                    continue
                arcname = _export_arcname(relative, source.name, extras)
                zf.write(source, arcname=arcname)
                written += 1
                if written == 1 or written % 500 == 0:
                    logger.info("Packed %s/%s files into export zip", written, len(objects))
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    if written == 0:
        archive.unlink(missing_ok=True)
        raise ValidationAppError("No vault files found to export.")
    logger.info(
        "Export zip ready: %s files (%s bytes on disk)",
        written,
        archive.stat().st_size,
    )
    return archive, written
