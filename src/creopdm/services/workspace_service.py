"""Workspace files are separate from the Git repository working tree."""

from __future__ import annotations

import os
from pathlib import Path

from creopdm.config import ConfigManager
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import PathValidationError, WorkspaceConflictError
from creopdm.logging_setup import get_logger
from creopdm.models.object import EngineeringObject
from creopdm.models.project import Project
from creopdm.utils.classify import classify_filename
from creopdm.utils.files import copy_file, set_file_readonly, set_file_writable
from creopdm.utils.hashing import calculate_sha256
from creopdm.utils.paths import assert_safe_relative_path, ensure_within

logger = get_logger("workspace")


class WorkspaceService:
    def __init__(self, config: ConfigManager) -> None:
        self._config = config

    def root_for(self, project_uuid: str) -> Path:
        path = self._config.workspace_for_project(project_uuid)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def file_path(self, project_uuid: str, relative_path: str) -> Path:
        relative = assert_safe_relative_path(relative_path)
        root = self.root_for(project_uuid)
        return ensure_within(root, root / relative)

    def repository_file(self, project: Project, relative_path: str) -> Path:
        relative = assert_safe_relative_path(relative_path)
        repo = Path(project.repository_path)
        return ensure_within(repo, repo / relative)

    def materialize(
        self,
        project: Project,
        obj: EngineeringObject,
        writable: bool,
        overwrite_modified: bool = False,
    ) -> Path:
        source = self.repository_file(project, obj.relative_path)
        if not source.is_file():
            raise PathValidationError(
                f"Repository file is missing: {obj.filename}",
                details={"relative_path": obj.relative_path},
            )
        destination = self.file_path(project.uuid, obj.relative_path)
        latest = CreoFileManager.latest_in_directory(destination.parent, obj.filename)
        conflict_path = latest if latest is not None and latest.is_file() else (
            destination if destination.exists() else None
        )
        if (
            conflict_path is not None
            and not overwrite_modified
            and self._file_modified(conflict_path, obj)
        ):
            raise WorkspaceConflictError(
                f"{obj.filename} has local changes that would be overwritten.",
                details={"path": str(conflict_path)},
            )
        if (
            obj.current_version is not None
            and destination.is_file()
            and not self._file_modified(destination, obj)
        ):
            self._try_set_mode(destination, writable)
            return destination
        try:
            copy_file(source, destination)
        except OSError as exc:
            if self._is_locked(exc) and destination.is_file():
                logger.warning("Could not replace locked workspace file %s: %s", destination, exc)
                if not self._file_modified(destination, obj):
                    return destination
                raise WorkspaceConflictError(
                    f"{obj.filename} is open in another program. Close it and try Open again.",
                    details={"path": str(destination)},
                ) from exc
            raise
        self._try_set_mode(destination, writable)
        return destination

    def locate_content(self, project_uuid: str, obj: EngineeringObject) -> Path:
        destination = self.file_path(project_uuid, obj.relative_path)
        latest = CreoFileManager.latest_in_directory(destination.parent, obj.filename)
        if latest is None or not latest.is_file():
            raise PathValidationError(
                f"Workspace file not found for {obj.filename}.",
                details={"workspace": str(destination)},
            )
        return latest

    def is_modified(self, project: Project, obj: EngineeringObject) -> bool:
        destination = self.file_path(project.uuid, obj.relative_path)
        if not destination.exists() and CreoFileManager.latest_in_directory(
            destination.parent, obj.filename
        ) is None:
            return False
        try:
            path = self.locate_content(project.uuid, obj)
        except PathValidationError:
            return False
        return self._file_modified(path, obj)

    def materialize_many(
        self,
        session_objects: list[tuple[Project, EngineeringObject]],
    ) -> dict[str, list]:
        ok: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        for project, obj in session_objects:
            try:
                path = self.materialize(project, obj, writable=False)
                ok.append({"uuid": obj.uuid, "filename": obj.filename, "path": str(path)})
            except Exception as exc:
                from creopdm.exceptions import CreoPDMError

                message = exc.message if isinstance(exc, CreoPDMError) else str(exc)
                code = exc.code if isinstance(exc, CreoPDMError) else "APPLICATION_ERROR"
                failed.append(
                    {
                        "uuid": obj.uuid,
                        "filename": obj.filename,
                        "code": code,
                        "message": message,
                    }
                )
        return {"ok": ok, "failed": failed}

    def preferred_add_directory(self, project_uuid: str, owned_relative_paths: list[str] | None = None) -> Path:
        """Folder the Add Files dialog should start in: a checked-out CAD folder when possible."""
        root = self.root_for(project_uuid)
        for relative in owned_relative_paths or []:
            try:
                folder = self.file_path(project_uuid, relative).parent
            except PathValidationError:
                continue
            if folder.is_dir():
                return folder
        cad = root / "CAD"
        cad.mkdir(parents=True, exist_ok=True)
        return cad

    def relative_if_inside(self, project_uuid: str, path: Path) -> str | None:
        root = self.root_for(project_uuid)
        try:
            return self._canonical_relative(root, Path(path))
        except ValueError:
            return None

    def list_untracked(
        self,
        project: Project,
        objects: list[EngineeringObject],
    ) -> list[dict[str, str | int]]:
        """Find workspace files that are not already PDM objects.

        Creo saves new models into the workspace working directory. Numbered
        copies of files already in the project are ignored.
        """
        root = self.root_for(project.uuid)
        known = {CreoFileManager.logical_repo_path(obj.relative_path) for obj in objects}
        grouped: dict[str, list[Path]] = {}
        if root.is_dir():
            for path in self._iter_workspace_files(root):
                relative = path.resolve().relative_to(root.resolve()).as_posix()
                grouped.setdefault(CreoFileManager.logical_repo_path(relative), []).append(path)
        found: list[dict[str, str | int]] = []
        for key, paths in sorted(grouped.items()):
            if key in known:
                continue
            chosen = CreoFileManager.select_latest_creo_version(paths) or paths[0]
            relative = chosen.resolve().relative_to(root.resolve()).as_posix()
            found.append(
                {
                    "filename": Path(relative).name,
                    "relative_path": relative,
                    "path": str(chosen),
                    "size": chosen.stat().st_size if chosen.is_file() else 0,
                    "object_type": classify_filename(Path(relative).name).value,
                }
            )
        return found

    def _iter_workspace_files(self, root: Path):
        skip_dirs = {".git", ".creopdm", "__pycache__"}
        skip_suffixes = {".log", ".idx", ".inf", ".crc", ".tst", ".err", ".ncl", ".lst", ".bak", ".tmp"}
        skip_names = {"trail.txt", "std.err", "std.out"}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name.lower() not in skip_dirs]
            folder = Path(dirpath)
            for name in filenames:
                if name.startswith("."):
                    continue
                if name.lower() in skip_names:
                    continue
                path = folder / name
                suffix = path.suffix.lower()
                numbered = CreoFileManager.normalize_creo_filename(name)
                check = Path(numbered).suffix.lower() if numbered != name else suffix
                if check in skip_suffixes or suffix in skip_suffixes:
                    continue
                yield path

    def sibling_relative(self, obj: EngineeringObject, workspace_file: Path) -> str:
        """Repo-relative path that keeps the workspace filename, including Creo save numbers."""
        current = Path(obj.relative_path.replace("\\", "/"))
        parent = current.parent
        name = workspace_file.name
        if parent.as_posix() == ".":
            return name.replace("\\", "/")
        return (parent / name).as_posix()

    @staticmethod
    def _canonical_relative(root: Path, path: Path) -> str:
        relative = path.resolve().relative_to(root.resolve())
        canonical_name = CreoFileManager.canonical_repository_name(relative.name)
        parent = relative.parent
        if parent.as_posix() == ".":
            return canonical_name
        return (parent / canonical_name).as_posix()

    def purge_local(self, project: Project, obj: EngineeringObject) -> list[str]:
        """Delete workspace copies only. Never touches the project repository."""
        destination = self.file_path(project.uuid, obj.relative_path)
        removed: list[str] = []
        directory = destination.parent
        if not directory.is_dir():
            return removed
        wanted = CreoFileManager.logical_filename(obj.filename).lower()
        for path in list(directory.iterdir()):
            if not path.is_file():
                continue
            if CreoFileManager.logical_filename(path.name).lower() != wanted:
                continue
            try:
                set_file_writable(path)
                path.unlink()
                removed.append(str(path))
            except OSError:
                raise PathValidationError(
                    f"Could not delete the workspace copy of {obj.filename}.",
                    details={"path": str(path)},
                )
        return removed

    def mark_readonly(self, path: Path) -> None:
        try:
            set_file_readonly(path)
        except Exception:
            pass

    def mark_writable(self, path: Path) -> None:
        set_file_writable(path)

    @staticmethod
    def _try_set_mode(path: Path, writable: bool) -> None:
        try:
            if writable:
                set_file_writable(path)
            else:
                set_file_readonly(path)
        except OSError:
            logger.warning("Could not change permissions on %s", path)

    @staticmethod
    def _is_locked(exc: BaseException) -> bool:
        if getattr(exc, "winerror", None) == 32:
            return True
        return isinstance(exc, PermissionError)

    @staticmethod
    def _file_modified(path: Path, obj: EngineeringObject) -> bool:
        current = obj.current_version
        if current is None or not path.is_file():
            return False
        return calculate_sha256(path) != current.content_hash
