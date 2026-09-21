"""Workspace files are the Git vault."""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from creopdm.constants import (
    APP_NAME,
    APP_SCHEMA_VERSION,
    DEFAULT_BRANCH,
    PROJECT_JSON_NAME,
    PROJECT_MARKER_DIR,
    SCHEMA_VERSION_NAME,
    STANDARD_PROJECT_FOLDERS,
)
from creopdm.config import ConfigManager
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import PathValidationError, RepositoryError, WorkspaceConflictError
from creopdm.logging_setup import get_logger
from creopdm.models.object import EngineeringObject
from creopdm.models.project import Project
from creopdm.services.git_service import GitService, GitStatus
from creopdm.utils.classify import classify_filename
from creopdm.utils.files import (
    copy_file,
    prune_empty_dirs,
    remove_file,
    remove_tree,
    set_file_readonly,
    set_file_writable,
    set_hidden,
)
from creopdm.utils.hashing import calculate_sha256
from creopdm.utils.identity import UserIdentity
from creopdm.utils.ignore import sync_gitignore
from creopdm.utils.paths import assert_safe_relative_path, ensure_within

logger = get_logger("workspace")

_RESERVED_WORKSPACE_DIRS = frozenset({".git", ".creopdm", "__pycache__"})


class WorkspaceService:
    def __init__(self, config: ConfigManager, git: GitService | None = None) -> None:
        self._config = config
        self._git = git

    def _cad_extensions(self) -> list[str]:
        return self._config.all_cad_extensions()

    def _ignore_patterns(self) -> list[str]:
        return self._config.ignore_patterns()

    def _is_ignored(self, filename: str) -> bool:
        return CreoFileManager.is_ignored(filename, self._ignore_patterns())

    def sync_gitignore(self, vault: Path | None = None) -> None:
        patterns = self._ignore_patterns()
        if vault is not None:
            self._sync_vault_gitignore(vault, patterns)
            return
        root = self._config.workspace_root()
        if not root.is_dir():
            return
        for child in root.iterdir():
            if child.is_dir() and (child / ".git").exists():
                self._sync_vault_gitignore(child, patterns)

    @staticmethod
    def _sync_vault_gitignore(vault: Path, patterns: list[str]) -> None:
        path = vault / ".gitignore"
        set_hidden(path, False)
        sync_gitignore(path, patterns)
        WorkspaceService._hide_bookkeeping(vault)

    @staticmethod
    def _hide_bookkeeping(vault: Path) -> None:
        set_hidden(vault / PROJECT_MARKER_DIR)
        set_hidden(vault / ".gitignore")

    def root_for(self, project_uuid: str) -> Path:
        path = self._config.workspace_for_project(project_uuid)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def explorer_directory(self, project_uuid: str, folder: str = "") -> Path:
        """Workspace folder currently shown in Files, or the project root."""
        from creopdm.utils.folders import normalize_folder_query

        root = self.root_for(project_uuid)
        current = normalize_folder_query(folder)
        if not current:
            return root
        try:
            target = ensure_within(root, root / Path(current))
        except PathValidationError:
            return root
        return target if target.is_dir() else root

    def vault_for(self, project: Project) -> Path:
        return self.root_for(project.uuid)

    def leftover_source(self, project: Project) -> Path | None:
        """Old Creo folder recorded before Git lived in the workspace."""
        raw = (project.repository_path or "").strip()
        if not raw:
            return None
        path = Path(raw)
        try:
            if path.resolve() == self.vault_for(project).resolve():
                return None
        except OSError:
            return path
        return path

    def location_for(self, project: Project) -> Path | None:
        return self.leftover_source(project)

    def ensure_vault(self, project: Project) -> Path:
        """Git lives in the workspace. Move leftover source-folder repos here once."""
        vault = self.root_for(project.uuid)
        location = self.leftover_source(project)
        git = self._git
        if git is None:
            self._hide_bookkeeping(vault)
            return vault
        if git.is_repository(vault):
            if location is not None and git.is_repository(location):
                self.strip_location_git(location)
            self.sync_gitignore(vault)
            self._hide_bookkeeping(vault)
            return vault
        if location is not None and git.is_repository(location):
            logger.info("Moving Git history from %s into workspace %s", location, vault)
            git.clone_into(location, vault)
            if not git.is_repository(vault):
                raise RepositoryError(
                    "Could not move Git history into the vault.",
                    details={"location": str(location), "workspace": str(vault)},
                )
            self.strip_location_git(location)
            self.sync_gitignore(vault)
            self._hide_bookkeeping(vault)
            return vault
        git.init_repository(vault, DEFAULT_BRANCH)
        self.sync_gitignore(vault)
        self._hide_bookkeeping(vault)
        return vault

    def init_vault(self, project_uuid: str, name: str, user: UserIdentity) -> Path:
        if self._git is None:
            raise RepositoryError("Git is required to create a project but was not found on PATH.")
        vault = self.root_for(project_uuid)
        self._git.init_repository(vault, DEFAULT_BRANCH)
        self.sync_gitignore(vault)
        self._write_project_marker(vault, project_uuid, name, None, None)
        with_files = [".gitignore", PROJECT_MARKER_DIR]
        self._git.stage_files(vault, with_files)
        self._git.commit(vault, f"Initialize project {name}", user)
        return vault

    def workspace_relative(self, obj: EngineeringObject) -> str:
        """Keep the project's folder layout in the workspace."""
        relative = str(obj.relative_path or obj.filename).replace("\\", "/")
        return assert_safe_relative_path(relative).as_posix()

    def _workspace_search_dirs(
        self,
        project_uuid: str,
        obj: EngineeringObject | None = None,
    ) -> list[Path]:
        root = self.root_for(project_uuid)
        ordered: list[Path] = []
        seen: set[str] = set()

        def add(path: Path) -> None:
            key = str(path)
            if key in seen:
                return
            seen.add(key)
            ordered.append(path)

        if obj is not None:
            add(self.workspace_file_path(project_uuid, obj).parent)
        add(root)
        for folder in STANDARD_PROJECT_FOLDERS:
            leftover = root / folder
            if leftover.is_dir():
                add(leftover)
        return ordered

    def workspace_file_path(self, project_uuid: str, obj: EngineeringObject) -> Path:
        return self.file_path(project_uuid, self.workspace_relative(obj))

    def file_path(self, project_uuid: str, relative_path: str) -> Path:
        relative = assert_safe_relative_path(relative_path)
        root = self.root_for(project_uuid)
        return ensure_within(root, root / relative)

    def repository_file(self, project: Project, relative_path: str) -> Path:
        relative = assert_safe_relative_path(relative_path)
        root = self.vault_for(project)
        return ensure_within(root, root / relative)

    @staticmethod
    def _case_insensitive_file(path: Path) -> Path:
        """Linux Git and uploads can differ only by case (.JPG vs .jpg)."""
        if path.is_file():
            return path
        parent = path.parent
        if not parent.is_dir():
            return path
        wanted = path.name.casefold()
        try:
            matches = [
                child
                for child in parent.iterdir()
                if child.is_file() and child.name.casefold() == wanted
            ]
        except OSError:
            return path
        return matches[0] if len(matches) == 1 else path

    def materialize(
        self,
        project: Project,
        obj: EngineeringObject,
        writable: bool,
        overwrite_modified: bool = False,
        keep_local: bool = False,
    ) -> Path:
        source = self.repository_file(project, obj.relative_path)
        if not source.is_file():
            source = self._case_insensitive_file(source)
        if not source.is_file():
            self._restore_tracked(project, obj.relative_path)
            source = self.repository_file(project, obj.relative_path)
            if not source.is_file():
                source = self._case_insensitive_file(source)
        if not source.is_file():
            raise PathValidationError(
                f"Repository file is missing: {obj.filename}",
                details={"relative_path": obj.relative_path},
            )
        destination = self.workspace_file_path(project.uuid, obj)
        extras = self._cad_extensions()
        latest = CreoFileManager.latest_in_directory(
            destination.parent, obj.filename, extras
        )
        conflict_path = latest if latest is not None and latest.is_file() else (
            destination if destination.exists() else None
        )
        if conflict_path is not None and self._file_modified(conflict_path, obj):
            older_sibling = (
                conflict_path.resolve() != destination.resolve()
                and CreoFileManager.save_number(conflict_path.name, extras)
                < CreoFileManager.save_number(obj.filename, extras)
            )
            if keep_local:
                self._try_set_mode(conflict_path, writable)
                return conflict_path
            if not overwrite_modified and not older_sibling:
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
        if source.resolve() == destination.resolve():
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
        extras = self._cad_extensions()
        for directory in self._workspace_search_dirs(project_uuid, obj):
            latest = CreoFileManager.latest_in_directory(directory, obj.filename, extras)
            if latest is not None and latest.is_file():
                return latest
        destination = self.workspace_file_path(project_uuid, obj)
        raise PathValidationError(
            f"Vault file not found for {obj.filename}.",
            details={"workspace": str(destination)},
        )

    def stage_workspace_upload(
        self,
        project: Project,
        obj: EngineeringObject,
        filename: str,
        data: bytes,
    ) -> Path:
        """Write agent/browser bytes into the vault working copy (no version yet)."""
        name = Path(filename or "").name.strip()
        if not name:
            raise PathValidationError("A filename is required.")
        if not data:
            raise PathValidationError("The uploaded file is empty.")
        extras = self._cad_extensions()
        logical_upload = CreoFileManager.logical_filename(name, extras)
        logical_obj = CreoFileManager.logical_filename(obj.filename, extras)
        if logical_upload.casefold() != logical_obj.casefold():
            raise PathValidationError(
                f"{name} does not match checked-out file {obj.filename}.",
                details={"filename": name, "expected": obj.filename},
            )
        relative = self.sibling_relative(obj, Path(name))
        destination = self.file_path(project.uuid, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            set_file_writable(destination)
        destination.write_bytes(data)
        set_file_writable(destination)
        logger.info("Staged vault working copy %s (%s bytes)", destination, len(data))
        return destination

    def has_local_copy(self, project: Project, obj: EngineeringObject) -> bool:
        return self.workspace_file_path(project.uuid, obj).is_file()

    def local_copy_uuids(self, project: Project, objects: list[EngineeringObject]) -> set[str]:
        """UUIDs whose workspace files exist, from one directory walk."""
        if not objects:
            return set()
        root = self.root_for(project.uuid)
        names: set[str] = set()
        if root.is_dir():
            skip = {".git", ".creopdm", "__pycache__"}
            root_s = str(root)
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [name for name in dirnames if name.lower() not in skip]
                rel_dir = os.path.relpath(dirpath, root_s).replace("\\", "/")
                for name in filenames:
                    rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                    names.add(rel.lower())
        found: set[str] = set()
        for obj in objects:
            if self.workspace_relative(obj).lower() in names:
                found.add(obj.uuid)
        return found

    def is_modified(self, project: Project, obj: EngineeringObject) -> bool:
        try:
            path = self.locate_content(project.uuid, obj)
        except PathValidationError:
            return False
        return self._file_modified(path, obj)

    def _git_status(self, project: Project) -> GitStatus:
        empty = GitStatus(branch="main", dirty=False, staged=[], unstaged=[], untracked=[], raw="")
        if self._git is None:
            return empty
        vault = self.vault_for(project)
        if not self._git.is_repository(vault):
            return empty
        try:
            return self._git.status(vault)
        except Exception as exc:
            logger.warning("git status failed for %s: %s", project.uuid, exc)
            return empty

    def _status_lookups(
        self,
        project: Project,
        status: GitStatus,
    ) -> tuple[list[str], Path, set[str], dict[str, list[Path]]]:
        extras = self._cad_extensions()
        vault = self.vault_for(project)
        dirty_paths = {item.replace("\\", "/") for item in (*status.staged, *status.unstaged)}
        untracked_by_logical: dict[str, list[Path]] = defaultdict(list)
        if status.dirty:
            for item in status.untracked:
                key = CreoFileManager.logical_repo_path(item, extras)
                untracked_by_logical[key].append(vault / item)
        return extras, vault, dirty_paths, untracked_by_logical

    def pending_workspace_save(self, project: Project, obj: EngineeringObject) -> dict[str, str | int | bool] | None:
        """Describe a workspace copy that is newer than the last checked-in version."""
        try:
            path = self.locate_content(project.uuid, obj)
        except PathValidationError:
            return None
        recorded = obj.filename
        newer_save = path.name.lower() != recorded.lower()
        modified = self._file_modified(path, obj)
        if not newer_save and not modified:
            return None
        stamp = datetime.fromtimestamp(path.stat().st_mtime)
        return {
            "filename": path.name,
            "recorded_filename": recorded,
            "file_size": path.stat().st_size,
            "newer_save": newer_save,
            "modified": modified,
            "next_display": f"{obj.revision}.{obj.iteration + 1}",
            "saved_at": stamp.strftime("%Y-%m-%d %H:%M"),
        }

    def _pending_from_status(
        self,
        project: Project,
        obj: EngineeringObject,
        status: GitStatus,
        extras: list[str] | None = None,
        vault: Path | None = None,
        dirty_paths: set[str] | None = None,
        untracked_by_logical: dict[str, list[Path]] | None = None,
    ) -> dict[str, str | int | bool] | None:
        if not status.dirty:
            return None
        if extras is None or vault is None or dirty_paths is None or untracked_by_logical is None:
            extras, vault, dirty_paths, untracked_by_logical = self._status_lookups(project, status)
        rel = obj.relative_path.replace("\\", "/")
        logical = CreoFileManager.logical_repo_path(rel, extras)
        siblings = [path for path in untracked_by_logical.get(logical, ()) if path.is_file()]
        path: Path | None = None
        newer_save = False
        recorded_number = CreoFileManager.save_number(obj.filename, extras)
        if siblings:
            latest = CreoFileManager.select_latest_creo_version(siblings, extras) or siblings[0]
            if CreoFileManager.save_number(latest.name, extras) > recorded_number:
                path = latest
                newer_save = True
        if path is None and rel in dirty_paths:
            candidate = vault / rel
            if candidate.is_file():
                path = candidate
        if path is None or not path.is_file():
            return None
        stamp = datetime.fromtimestamp(path.stat().st_mtime)
        return {
            "filename": path.name,
            "recorded_filename": obj.filename,
            "file_size": path.stat().st_size,
            "newer_save": newer_save or path.name.lower() != obj.filename.lower(),
            "modified": True,
            "next_display": f"{obj.revision}.{obj.iteration + 1}",
            "saved_at": stamp.strftime("%Y-%m-%d %H:%M"),
        }

    def project_checkin_queue(
        self,
        project: Project,
        objects: list[EngineeringObject],
    ) -> dict[str, list]:
        """Files in the workspace that would be recorded on check-in."""
        status = self._git_status(project)
        extras, vault, dirty_paths, untracked_by_logical = self._status_lookups(project, status)
        saves: list[dict[str, str | int | bool]] = []
        for obj in objects:
            pending = self._pending_from_status(
                project,
                obj,
                status,
                extras=extras,
                vault=vault,
                dirty_paths=dirty_paths,
                untracked_by_logical=untracked_by_logical,
            )
            if pending is None:
                continue
            saves.append(
                {
                    **pending,
                    "uuid": obj.uuid,
                    "kind": "newer_save" if pending["newer_save"] else "modified",
                    "object_type": obj.object_type,
                    "extension": obj.extension,
                }
            )
        return {"saves": saves, "new_files": self.list_untracked(project, objects, status)}

    def watch_stamp(
        self,
        project: Project,
        known_paths: list[tuple[str, str]] | None = None,
    ) -> dict[str, str | int]:
        """Fingerprint of git status so the UI can notice Creo saves without hashing files."""
        status = self._git_status(project)
        digest = hashlib.sha256(status.raw.encode("utf-8")).hexdigest()[:20]
        extras = self._cad_extensions()
        known = {
            CreoFileManager.logical_repo_path(relative, extras): filename
            for relative, filename in known_paths or ()
        }
        dirty_logical = {
            CreoFileManager.logical_repo_path(item, extras)
            for item in (*status.staged, *status.unstaged)
        }
        pending: set[str] = set()
        new_files = 0
        if known:
            pending.update(item for item in dirty_logical if item in known)
            for item in status.untracked:
                name = Path(item).name
                if self._is_ignored(name):
                    continue
                logical = CreoFileManager.logical_repo_path(item, extras)
                recorded = known.get(logical)
                if recorded is None:
                    new_files += 1
                    continue
                if CreoFileManager.save_number(name, extras) > CreoFileManager.save_number(recorded, extras):
                    pending.add(logical)
        else:
            pending.update(dirty_logical)
            new_files = sum(1 for item in status.untracked if not self._is_ignored(Path(item).name))
        return {
            "stamp": digest,
            "pending_saves": len(pending),
            "new_files": new_files,
        }

    def materialize_many(
        self,
        session_objects: list[tuple[Project, EngineeringObject]],
    ) -> dict[str, list]:
        ok: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        for project, obj in session_objects:
            try:
                if self.has_local_copy(project, obj):
                    continue
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

    def copy_into_workspace(
        self,
        project: Project,
        obj: EngineeringObject,
        writable: bool = False,
        keep_local: bool = False,
    ) -> Path | None:
        """Copy a newly added vault file into the workspace. Best-effort."""
        try:
            return self.materialize(project, obj, writable=writable, keep_local=keep_local)
        except Exception:
            logger.exception("Could not copy %s into the workspace", obj.filename)
            return None

    def preferred_add_directory(self, project_uuid: str, owned_relative_paths: list[str] | None = None) -> Path:
        """Workspace root: all working copies live in one folder."""
        return self.root_for(project_uuid)

    def relative_if_inside(self, project_uuid: str, path: Path) -> str | None:
        root = self.root_for(project_uuid)
        try:
            return self._canonical_relative(root, Path(path))
        except ValueError:
            return None

    def import_relative_path(
        self,
        project: Project,
        source: Path,
        base_folder: Path | str | None = None,
    ) -> str | None:
        """Workspace-relative path used when adding a file.

        Choose Folder keeps the chosen folder name as a group, including nested
        files. Choose Files stores the file at the workspace root.
        """
        path = Path(source)
        if not base_folder:
            return None
        base = Path(base_folder)
        try:
            rel = path.resolve().relative_to(base.resolve())
        except ValueError:
            return None
        stored = CreoFileManager.canonical_repository_name(rel.name)
        parent = rel.parent
        if parent.as_posix() == ".":
            return f"{base.name}/{stored}"
        return (Path(base.name) / parent / stored).as_posix()

    def list_untracked(
        self,
        project: Project,
        objects: list[EngineeringObject],
        status: GitStatus | None = None,
    ) -> list[dict[str, str | int]]:
        """Find workspace files that are not already PDM objects."""
        extras = self._cad_extensions()
        known = {CreoFileManager.logical_repo_path(obj.relative_path, extras) for obj in objects}
        snapshot = status if status is not None else self._git_status(project)
        vault = self.vault_for(project)
        grouped: dict[str, list[Path]] = {}
        for relative in snapshot.untracked:
            name = Path(relative).name
            if self._is_ignored(name):
                continue
            path = vault / relative
            if not path.is_file():
                continue
            grouped.setdefault(CreoFileManager.logical_repo_path(relative, extras), []).append(path)
        found: list[dict[str, str | int]] = []
        for key, paths in sorted(grouped.items()):
            if key in known:
                continue
            chosen = CreoFileManager.select_latest_creo_version(paths, extras) or paths[0]
            relative = chosen.resolve().relative_to(vault.resolve()).as_posix()
            size = 0
            stamp = ""
            try:
                info = chosen.stat()
                size = info.st_size
                stamp = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")
            except OSError:
                pass
            found.append(
                {
                    "filename": Path(relative).name,
                    "relative_path": relative,
                    "path": str(chosen),
                    "size": size,
                    "saved_at": stamp,
                    "object_type": classify_filename(
                        Path(relative).name,
                        extra_cad_extensions=self._config.data_cad_extensions(),
                        model_extensions=self._config.model_cad_extensions(),
                        document_extensions=self._config.document_extensions(),
                    ).value,
                }
            )
        return found

    def _iter_workspace_files(self, root: Path):
        skip_dirs = {".git", ".creopdm", "__pycache__"}
        skip_suffixes = {".bak", ".tmp"}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name.lower() not in skip_dirs]
            folder = Path(dirpath)
            for name in filenames:
                if name.startswith("."):
                    continue
                if self._is_ignored(name):
                    continue
                path = folder / name
                suffix = path.suffix.lower()
                numbered = CreoFileManager.normalize_creo_filename(name, self._cad_extensions())
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

    def purge_untracked_paths(
        self,
        project: Project,
        relative_paths: list[str],
        objects: list[EngineeringObject],
    ) -> list[dict[str, str]]:
        """Delete untracked New Files rows from the workspace vault."""
        extras = self._cad_extensions()
        known = {
            CreoFileManager.logical_repo_path(obj.relative_path, extras).lower()
            for obj in objects
        }
        vault = self.vault_for(project)
        targets: set[str] = set()
        requested: list[str] = []
        for raw in relative_paths:
            relative = assert_safe_relative_path(str(raw).replace("\\", "/")).as_posix()
            logical = CreoFileManager.logical_repo_path(relative, extras).lower()
            if logical in known:
                raise PathValidationError(
                    "That file is already in the project. Use Remove from Vault on the Files tab.",
                    details={"relative_path": relative},
                )
            path = ensure_within(vault, vault / relative)
            if not path.is_file():
                raise PathValidationError(
                    f"Vault file not found: {relative}",
                    details={"relative_path": relative},
                )
            targets.add(logical)
            requested.append(relative)

        removed: list[dict[str, str]] = []
        removed_paths: list[str] = []
        skip = _RESERVED_WORKSPACE_DIRS
        for dirpath, dirnames, filenames in os.walk(vault):
            dirnames[:] = [name for name in dirnames if name.lower() not in skip]
            rel_dir = os.path.relpath(dirpath, vault).replace("\\", "/")
            for name in filenames:
                rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                logical = CreoFileManager.logical_repo_path(rel, extras).lower()
                if logical not in targets:
                    continue
                path = Path(dirpath) / name
                try:
                    set_file_writable(path)
                    path.unlink()
                except OSError:
                    raise PathValidationError(
                        f"Could not delete the vault copy of {name}.",
                        details={"path": str(path)},
                    )
                removed_paths.append(str(path))
                removed.append({"relative_path": rel.replace("\\", "/"), "filename": name})

        if not removed and requested:
            raise PathValidationError(
                "No matching vault files were removed.",
                details={"relative_paths": requested},
            )
        self._prune_empty_workspace_dirs(vault, removed_paths)
        return removed

    def purge_local(self, project: Project, obj: EngineeringObject) -> list[str]:
        """Delete workspace copies only. Never touches the project repository."""
        extras = self._cad_extensions()
        wanted = CreoFileManager.logical_filename(obj.filename, extras).lower()
        removed: list[str] = []
        for directory in self._workspace_search_dirs(project.uuid, obj):
            if not directory.is_dir():
                continue
            for path in list(directory.iterdir()):
                if not path.is_file():
                    continue
                if CreoFileManager.logical_filename(path.name, extras).lower() != wanted:
                    continue
                try:
                    set_file_writable(path)
                    path.unlink()
                    removed.append(str(path))
                except OSError:
                    raise PathValidationError(
                        f"Could not delete the vault copy of {obj.filename}.",
                        details={"path": str(path)},
                    )
        self._prune_empty_workspace_dirs(self.root_for(project.uuid), removed)
        return removed

    def purge_local_many(
        self,
        project: Project,
        objects: list[EngineeringObject],
        *,
        ignore_locked: bool = False,
    ) -> list[str]:
        """Delete workspace copies for many objects with one directory walk."""
        if not objects:
            return []
        extras = self._cad_extensions()
        wanted = {
            CreoFileManager.logical_repo_path(obj.relative_path, extras).lower()
            for obj in objects
        }
        root = self.root_for(project.uuid)
        if not root.is_dir():
            return []
        skip = _RESERVED_WORKSPACE_DIRS
        removed: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name.lower() not in skip]
            rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
            for name in filenames:
                rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                logical = CreoFileManager.logical_repo_path(rel, extras).lower()
                if logical not in wanted:
                    continue
                path = Path(dirpath) / name
                try:
                    set_file_writable(path)
                    path.unlink()
                    removed.append(str(path))
                except OSError:
                    if not ignore_locked:
                        raise PathValidationError(
                            f"Could not delete the vault copy of {name}.",
                            details={"path": str(path)},
                        )
        self._prune_empty_workspace_dirs(root, removed)
        return removed

    def _prune_empty_workspace_dirs(self, root: Path, removed: list[str]) -> None:
        parents = {Path(path).parent for path in removed}
        for directory in sorted(parents, key=lambda item: len(item.parts), reverse=True):
            prune_empty_dirs(directory, root, reserved_names=_RESERVED_WORKSPACE_DIRS)

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

    def _restore_tracked(self, project: Project, relative_path: str) -> None:
        if self._git is None:
            return
        vault = self.vault_for(project)
        if not self._git.is_repository(vault):
            return
        try:
            self._git.restore_file(vault, relative_path.replace("\\", "/"), "HEAD")
        except Exception:
            logger.exception("Could not restore %s from Git", relative_path)

    def strip_location_git(self, location: Path) -> None:
        """Remove CreoPDM Git leftovers from the original folder. CAD files stay."""
        remove_tree(location / ".git")
        for name in (".gitignore", ".gitattributes"):
            remove_file(location / name)
        remove_tree(location / PROJECT_MARKER_DIR)
        self._remove_creopdm_readme(location / "README.md")
        for folder in STANDARD_PROJECT_FOLDERS:
            remove_file(location / folder / ".gitkeep")

    @staticmethod
    def _remove_creopdm_readme(path: Path) -> None:
        if not path.is_file():
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return
        if f"Managed by {APP_NAME}" not in text:
            return
        remove_file(path)

    def write_project_marker(
        self,
        project: Project,
        name: str,
        number: str | None,
        description: str | None,
    ) -> None:
        self._write_project_marker(self.vault_for(project), project.uuid, name, number, description)

    def _write_project_marker(
        self,
        vault: Path,
        project_uuid: str,
        name: str,
        number: str | None,
        description: str | None,
    ) -> None:
        marker = vault / PROJECT_MARKER_DIR
        marker.mkdir(parents=True, exist_ok=True)
        path = marker / PROJECT_JSON_NAME
        payload: dict = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except json.JSONDecodeError:
                payload = {}
        payload.update(
            {
                "uuid": project_uuid,
                "name": name,
                "number": number,
                "description": description,
                "default_branch": payload.get("default_branch") or DEFAULT_BRANCH,
                "schema_version": payload.get("schema_version") or APP_SCHEMA_VERSION,
            }
        )
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        schema = marker / SCHEMA_VERSION_NAME
        if not schema.is_file():
            schema.write_text(f"{APP_SCHEMA_VERSION}\n", encoding="utf-8")
        self._hide_bookkeeping(vault)
