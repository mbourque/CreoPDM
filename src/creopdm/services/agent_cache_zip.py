"""Agent-cache download helpers: vault zip + manifest for cache hits."""

from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

from creopdm.exceptions import PathValidationError, ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.models.object import EngineeringObject
from creopdm.models.project import Project
from creopdm.services.workspace_service import WorkspaceService

logger = get_logger("agent_cache_zip")


def _vault_source(workspaces: WorkspaceService, project: Project, obj: EngineeringObject) -> Path:
    source = workspaces.repository_file(project, obj.relative_path)
    if not source.is_file():
        source = workspaces._case_insensitive_file(source)
    if not source.is_file():
        workspaces._restore_tracked(project, obj.relative_path)
        source = workspaces.repository_file(project, obj.relative_path)
        if not source.is_file():
            source = workspaces._case_insensitive_file(source)
    if not source.is_file():
        raise PathValidationError(
            f"Repository file is missing: {obj.filename}",
            details={"uuid": obj.uuid, "relative_path": obj.relative_path},
        )
    return source


def manifest_items_for_objects(objects: list[EngineeringObject]) -> list[dict[str, object]]:
    """Build flat cache identities from loaded objects (order preserved)."""
    items: list[dict[str, object]] = []
    for obj in objects:
        version = obj.current_version
        disk_name = Path(str(obj.relative_path or obj.filename).replace("\\", "/")).name
        items.append(
            {
                "object_id": obj.uuid,
                "filename": obj.filename,
                "disk_name": disk_name,
                "content_hash": (version.content_hash if version is not None else "") or "",
                "file_size": int(version.file_size) if version is not None else 0,
            }
        )
    return items


def build_agent_cache_zip(
    workspaces: WorkspaceService,
    project: Project,
    objects: list[EngineeringObject],
) -> tuple[Path, int]:
    """Write vault files to a temp zip (flat names, matching agent cache layout)."""
    if not objects:
        raise ValidationAppError("No files to download.")
    fd, raw_name = tempfile.mkstemp(suffix=".zip", prefix="creopdm-cache-")
    os.close(fd)
    archive = Path(raw_name)
    written = 0
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zf:
            for obj in objects:
                source = _vault_source(workspaces, project, obj)
                arcname = source.name
                zf.write(source, arcname=arcname)
                written += 1
                if written == 1 or written % 500 == 0:
                    logger.info("Packed %s/%s files into agent-cache zip", written, len(objects))
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    if written == 0:
        archive.unlink(missing_ok=True)
        raise ValidationAppError("No vault files found for this download.")
    logger.info(
        "Agent-cache zip ready: %s files (%s bytes on disk)",
        written,
        archive.stat().st_size,
    )
    return archive, written
