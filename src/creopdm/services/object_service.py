"""Engineering objects: import, classify, and initial version storage."""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session, joinedload

from creopdm.constants import (
    DEFAULT_CREO_MODEL_EXTENSIONS,
    DEFAULT_EXTRA_CAD_EXTENSIONS,
    DEFAULT_OPENABLE_CAD_EXTENSIONS,
    DEFAULT_REVISION,
    INITIAL_ITERATION,
    ActivityAction,
    CheckoutStatus,
    LifecycleState,
)
from creopdm.config import ConfigManager
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import (
    CreoPDMError,
    DuplicateObjectError,
    ObjectAlreadyCheckedOutError,
    ObjectNotFoundError,
    PathValidationError,
    ReleasedObjectError,
    RepositoryError,
    ValidationAppError,
)
from creopdm.logging_setup import get_logger
from creopdm.models.activity import Activity
from creopdm.models.checkout import Checkout
from creopdm.models.dependency import Dependency
from creopdm.models.object import EngineeringObject
from creopdm.models.parameter import Parameter
from creopdm.models.project import Project
from creopdm.models.version import ObjectVersion
from creopdm.services.activity_service import ActivityService
from creopdm.services.lock_manager import ProjectLockManager
from creopdm.storage.base import VersionStore
from creopdm.utils.classify import classify_filename
from creopdm.utils.creo_header import creo_release_for
from creopdm.utils.files import copy_file, set_file_readonly, set_file_writable
from creopdm.utils.hashing import calculate_sha256
from creopdm.utils.identity import CurrentUserProvider
from creopdm.utils.paths import (
    assert_safe_relative_path,
    ensure_within,
    sanitize_filename,
)

logger = get_logger("objects")


class ObjectService:
    def __init__(
        self,
        version_store: VersionStore,
        locks: ProjectLockManager,
        activities: ActivityService,
        users: CurrentUserProvider,
        config: ConfigManager | None = None,
    ) -> None:
        self._store = version_store
        self._locks = locks
        self._activities = activities
        self._users = users
        self._config = config

    def _vault(self, project: Project) -> Path:
        if self._config is None:
            raise RepositoryError("Workspace configuration is missing.")
        path = self._config.workspace_for_project(project.uuid)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _cad_extensions(self) -> list[str]:
        if self._config is None:
            return list(
                (
                    *DEFAULT_CREO_MODEL_EXTENSIONS,
                    *DEFAULT_OPENABLE_CAD_EXTENSIONS,
                    *DEFAULT_EXTRA_CAD_EXTENSIONS,
                )
            )
        return self._config.all_cad_extensions()

    def list_objects(
        self,
        session: Session,
        project_id: int,
        query: str | None = None,
        object_type: str | None = None,
        lifecycle_state: str | None = None,
    ) -> list[EngineeringObject]:
        stmt = select(EngineeringObject).options(
            joinedload(EngineeringObject.current_version),
            joinedload(EngineeringObject.project),
        ).where(EngineeringObject.project_id == project_id)
        if object_type:
            stmt = stmt.where(EngineeringObject.object_type == object_type)
        if lifecycle_state:
            stmt = stmt.where(EngineeringObject.lifecycle_state == lifecycle_state)
        if query:
            like = f"%{query.strip()}%"
            param_match = select(Parameter.object_id).where(
                or_(Parameter.name.ilike(like), Parameter.value.ilike(like))
            )
            stmt = stmt.where(
                or_(
                    EngineeringObject.name.ilike(like),
                    EngineeringObject.number.ilike(like),
                    EngineeringObject.filename.ilike(like),
                    EngineeringObject.object_type.ilike(like),
                    EngineeringObject.revision.ilike(like),
                    EngineeringObject.lifecycle_state.ilike(like),
                    EngineeringObject.id.in_(param_match),
                )
            )
        return list(
            session.scalars(
                stmt.order_by(
                    EngineeringObject.updated_at.desc(),
                    EngineeringObject.filename.asc(),
                )
            ).unique()
        )

    def list_path_index(self, session: Session, project_id: int) -> list[tuple[str, str]]:
        """Imported relative_path and filename only. Used by workspace watch."""
        rows = session.execute(
            select(EngineeringObject.relative_path, EngineeringObject.filename).where(
                EngineeringObject.project_id == project_id
            )
        ).all()
        return [(str(relative), str(filename)) for relative, filename in rows]

    def get_object(self, session: Session, object_uuid: str) -> EngineeringObject:
        obj = session.scalar(
            select(EngineeringObject)
            .options(
                joinedload(EngineeringObject.project),
                joinedload(EngineeringObject.current_version),
            )
            .where(EngineeringObject.uuid == object_uuid)
        )
        if obj is None:
            raise ObjectNotFoundError("Object not found.", details={"uuid": object_uuid})
        return obj

    def get_objects(self, session: Session, object_uuids: list[str]) -> list[EngineeringObject]:
        """Load objects by uuid, preserving request order and skipping unknown ids."""
        wanted = [item for item in object_uuids if item]
        if not wanted:
            return []
        found: dict[str, EngineeringObject] = {}
        for start in range(0, len(wanted), 400):
            chunk = wanted[start : start + 400]
            rows = session.scalars(
                select(EngineeringObject)
                .options(
                    joinedload(EngineeringObject.project),
                    joinedload(EngineeringObject.current_version),
                )
                .where(EngineeringObject.uuid.in_(chunk))
            ).unique()
            for obj in rows:
                found[obj.uuid] = obj
        return [found[item] for item in wanted if item in found]

    def delete_object(self, session: Session, object_uuid: str) -> dict[str, str]:
        """Unregister the object from the project. Never deletes the original file.

        Workspace copies are purged by the caller. Git tracking is dropped with
        --cached so a leftover file in the original project folder stays on disk.
        """
        obj = self.get_object(session, object_uuid)
        project = obj.project
        user = self._users.get_current_user()
        filename = obj.filename
        relative = obj.relative_path
        uuid_value = obj.uuid
        repo = self._vault(project)
        with self._locks.acquire(project.uuid):
            captured = self._store.capture_checkpoint(repo)
            try:
                self._store.remove_files(
                    repo,
                    [relative],
                    f"Unregister {filename}",
                    user,
                    keep_working_copy=True,
                )
            except Exception:
                if (repo / ".git").exists():
                    logger.exception("Git untrack failed for %s", relative)
                    raise RepositoryError(
                        f"Could not unregister {filename} from project history.",
                        details={"file": filename, "relative_path": relative},
                    )
                logger.warning("Git history missing; unregistering %s from the project list only", filename)
            try:
                self._delete_metadata(session, obj)
                self._activities.record(
                    session,
                    ActivityAction.OBJECT_REMOVED,
                    user,
                    project_id=project.id,
                    object_id=None,
                    details={"filename": filename, "relative_path": relative, "uuid": uuid_value},
                )
            except Exception as exc:
                logger.exception("Metadata failed after unregistering %s", relative)
                if captured:
                    self._store.restore_checkpoint(repo, captured)
                raise RepositoryError(
                    "Project metadata could not be updated. The original file was not deleted.",
                    details={"file": filename},
                ) from exc
        logger.info("Unregistered object %s (%s); original file left in place", uuid_value, relative)
        return {"uuid": uuid_value, "filename": filename, "relative_path": relative}

    def delete_objects(self, session: Session, objects: list[EngineeringObject]) -> list[dict[str, str]]:
        """Unregister many objects with one Git untrack and one commit per project."""
        if not objects:
            return []
        if len(objects) == 1:
            return [self.delete_object(session, objects[0].uuid)]
        grouped: dict[int, list[EngineeringObject]] = {}
        for obj in objects:
            grouped.setdefault(obj.project_id, []).append(obj)
        removed: list[dict[str, str]] = []
        for group in grouped.values():
            removed.extend(self._delete_objects_in_project(session, group))
        return removed

    def _delete_objects_in_project(
        self,
        session: Session,
        objects: list[EngineeringObject],
    ) -> list[dict[str, str]]:
        project = objects[0].project
        user = self._users.get_current_user()
        relatives = [obj.relative_path.replace("\\", "/") for obj in objects]
        repo = self._vault(project)
        count = len(objects)
        message = f"Unregister {count} files"
        summaries = [
            {"uuid": obj.uuid, "filename": obj.filename, "relative_path": obj.relative_path}
            for obj in objects
        ]
        with self._locks.acquire(project.uuid):
            captured = self._store.capture_checkpoint(repo)
            try:
                self._store.remove_files(
                    repo,
                    relatives,
                    message,
                    user,
                    keep_working_copy=True,
                )
            except Exception:
                if (repo / ".git").exists():
                    logger.exception("Git untrack failed for %s files", count)
                    raise RepositoryError(
                        f"Could not unregister {count} files from project history.",
                        details={"count": count},
                    )
                logger.warning(
                    "Git history missing; unregistering %s files from the project list only",
                    count,
                )
            try:
                self._delete_metadata_many(session, objects)
                self._activities.record(
                    session,
                    ActivityAction.OBJECT_REMOVED,
                    user,
                    project_id=project.id,
                    object_id=None,
                    details={
                        "count": count,
                        "filenames": [item["filename"] for item in summaries[:20]],
                    },
                )
            except Exception as exc:
                logger.exception("Metadata failed after unregistering %s files", count)
                if captured:
                    self._store.restore_checkpoint(repo, captured)
                raise RepositoryError(
                    "The files were untracked but project metadata could not be updated. "
                    "The repository was restored and the files were not removed from the list.",
                    details={"count": count},
                ) from exc
        logger.info("Unregistered %s objects; original files left in place", count)
        return summaries

    def _delete_metadata(self, session: Session, obj: EngineeringObject) -> None:
        object_id = obj.id
        current = obj.current_version
        obj.current_version = None
        obj.current_version_id = None
        session.flush()
        if current is not None:
            session.expunge(current)
        session.execute(delete(Parameter).where(Parameter.object_id == object_id))
        session.execute(delete(Checkout).where(Checkout.object_id == object_id))
        session.execute(
            delete(Dependency).where(
                or_(
                    Dependency.parent_object_id == object_id,
                    Dependency.child_object_id == object_id,
                )
            )
        )
        session.execute(update(Activity).where(Activity.object_id == object_id).values(object_id=None))
        session.expire(obj, ["versions", "current_version", "checkouts", "parameters"])
        session.execute(delete(ObjectVersion).where(ObjectVersion.object_id == object_id))
        session.delete(obj)
        session.flush()

    def _delete_metadata_many(self, session: Session, objects: list[EngineeringObject]) -> None:
        ids = [obj.id for obj in objects]
        if not ids:
            return
        for obj in objects:
            obj.current_version = None
            obj.current_version_id = None
        session.flush()
        for start in range(0, len(ids), 400):
            chunk = ids[start : start + 400]
            session.execute(delete(Parameter).where(Parameter.object_id.in_(chunk)))
            session.execute(delete(Checkout).where(Checkout.object_id.in_(chunk)))
            session.execute(
                delete(Dependency).where(
                    or_(
                        Dependency.parent_object_id.in_(chunk),
                        Dependency.child_object_id.in_(chunk),
                    )
                )
            )
            session.execute(update(Activity).where(Activity.object_id.in_(chunk)).values(object_id=None))
            session.execute(delete(ObjectVersion).where(ObjectVersion.object_id.in_(chunk)))
            session.execute(delete(EngineeringObject).where(EngineeringObject.id.in_(chunk)))
        session.flush()

    def import_file(
        self,
        session: Session,
        project: Project,
        source_path: Path,
        original_name: str | None = None,
        relative_path: str | None = None,
        comment: str | None = None,
    ) -> EngineeringObject:
        if not source_path.is_file():
            raise PathValidationError("The selected file does not exist.")

        display_name = sanitize_filename(original_name or source_path.name)
        stored_name = CreoFileManager.canonical_repository_name(display_name)
        ignore = self._config.ignore_patterns() if self._config else None
        if CreoFileManager.is_ignored(stored_name, ignore):
            raise PathValidationError(
                f"{stored_name} is an ignored session file and is not stored in CreoPDM.",
                details={"filename": stored_name},
            )
        logical_name = CreoFileManager.logical_filename(stored_name, self._cad_extensions())
        extras = self._config.data_cad_extensions() if self._config else None
        models = self._config.model_cad_extensions() if self._config else None
        object_type = classify_filename(
            stored_name,
            extra_cad_extensions=extras,
            model_extensions=models,
        )
        extension = Path(logical_name).suffix.lower() or Path(stored_name).suffix.lower()
        stem = Path(logical_name).stem

        if relative_path:
            rel = assert_safe_relative_path(relative_path)
            if rel.name != stored_name:
                rel = rel.parent / stored_name
        else:
            rel = Path(stored_name)
        rel = assert_safe_relative_path(str(rel).replace("\\", "/"))
        relative = rel.as_posix()
        reserved = {part.lower() for part in rel.parts}
        if reserved & {".git", ".creopdm"}:
            raise PathValidationError("That location is reserved for CreoPDM.")

        existing = self.existing_logical(session, project.id, relative)
        if existing is not None:
            extras_all = self._cad_extensions()
            incoming_n = CreoFileManager.save_number(stored_name, extras_all)
            recorded_n = CreoFileManager.save_number(existing.filename, extras_all)
            if incoming_n > recorded_n:
                return self._import_later_save(
                    session,
                    project,
                    existing,
                    source_path,
                    stored_name,
                    comment,
                )
            if incoming_n < recorded_n:
                raise DuplicateObjectError(
                    f"{stored_name} is an older save of {existing.filename}, which is already in this project.",
                    details={"relative_path": existing.relative_path, "existing": existing.filename},
                )
            raise DuplicateObjectError(
                f"{stored_name} is already in this project as {existing.filename}.",
                details={"relative_path": existing.relative_path, "existing": existing.filename},
            )

        repo = self._vault(project)
        destination = ensure_within(repo, repo / rel)
        user = self._users.get_current_user()
        content_hash = calculate_sha256(source_path)
        file_size = source_path.stat().st_size
        creo_release = creo_release_for(source_path, stored_name)
        message = (comment or f"Add {stored_name}").strip()
        if not message:
            raise ValidationAppError("A comment is required when adding a file.")

        captured_head = self._store.capture_checkpoint(repo)
        object_uuid = str(uuid.uuid4())
        version_uuid = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        with self._locks.acquire(project.uuid):
            created_copy = copy_file(source_path, destination)
            try:
                git_hash = self._store.store_version(
                    repo,
                    [relative],
                    message,
                    user,
                )
            except Exception:
                if created_copy:
                    self._remove_copied_file(destination)
                raise

            obj = EngineeringObject(
                uuid=object_uuid,
                project_id=project.id,
                number=stem.upper(),
                name=stem,
                filename=stored_name,
                extension=extension,
                object_type=object_type.value,
                relative_path=relative,
                revision=DEFAULT_REVISION,
                iteration=INITIAL_ITERATION,
                lifecycle_state=LifecycleState.IN_WORK.value,
                created_at=now,
                updated_at=now,
            )
            session.add(obj)
            session.flush()

            version = ObjectVersion(
                uuid=version_uuid,
                object_id=obj.id,
                revision=DEFAULT_REVISION,
                iteration=INITIAL_ITERATION,
                git_commit_hash=git_hash,
                content_hash=content_hash,
                file_size=file_size,
                filename=stored_name,
                relative_path=relative,
                creo_release=creo_release,
                created_by=user.user_name,
                created_at=now,
                comment=message,
            )
            session.add(version)
            session.flush()
            obj.current_version_id = version.id
            obj.updated_at = now
            try:
                session.flush()
            except Exception as exc:
                logger.exception("Metadata failed after storing %s", relative)
                if captured_head:
                    self._store.restore_checkpoint(repo, captured_head)
                raise RepositoryError(
                    "The file was stored but project metadata could not be updated. "
                    "The repository was restored and the file was not added.",
                    details={"file": stored_name},
                ) from exc
            try:
                set_file_readonly(destination)
            except Exception:
                logger.warning("Could not mark %s read-only after import", destination)

            self._activities.record(
                session,
                ActivityAction.OBJECT_ADDED,
                user,
                project_id=project.id,
                object_id=obj.id,
                details={"filename": stored_name, "relative_path": relative},
            )
            logger.info("Added object %s (%s)", obj.uuid, relative)
            return obj

    def _import_later_save(
        self,
        session: Session,
        project: Project,
        existing: EngineeringObject,
        source_path: Path,
        stored_name: str,
        comment: str | None,
    ) -> EngineeringObject:
        """Record a higher Creo save number as the next iteration of an existing object."""
        if existing.lifecycle_state != LifecycleState.IN_WORK.value:
            raise ReleasedObjectError(
                f"{existing.filename} is {existing.lifecycle_state.replace('_', ' ').title()} "
                "and cannot take a later save.",
                details={"uuid": existing.uuid},
            )
        active = session.scalar(
            select(Checkout).where(
                Checkout.object_id == existing.id,
                Checkout.status == CheckoutStatus.ACTIVE.value,
            )
        )
        user = self._users.get_current_user()
        if active is not None:
            if active.user_name != user.user_name:
                raise ObjectAlreadyCheckedOutError(
                    f"{existing.filename} is checked out by {active.user_name}.",
                    details={"uuid": existing.uuid, "user": active.user_name},
                )
            self._stage_later_workspace_save(project, existing, source_path, stored_name)
            return existing
        relative = self._later_save_relative(existing, stored_name)
        old_relative = existing.relative_path.replace("\\", "/")
        repo = self._vault(project)
        destination = ensure_within(repo, repo / Path(relative))
        content_hash = calculate_sha256(source_path)
        file_size = source_path.stat().st_size
        creo_release = creo_release_for(source_path, stored_name)
        message = (comment or f"Add {stored_name}").strip()
        if not message:
            raise ValidationAppError("A comment is required when adding a file.")
        captured_head = self._store.capture_checkpoint(repo)
        now = datetime.now(timezone.utc)
        new_iteration = existing.iteration + 1
        with self._locks.acquire(project.uuid):
            created_copy = copy_file(source_path, destination)
            try:
                git_hash = self._store.store_version(
                    repo,
                    [relative],
                    message,
                    user,
                    remove_relative_paths=[old_relative] if old_relative != relative else [],
                )
            except Exception:
                if created_copy:
                    self._remove_copied_file(destination)
                raise
            existing.filename = stored_name
            existing.relative_path = relative
            existing.updated_at = now
            existing.iteration = new_iteration
            version = ObjectVersion(
                uuid=str(uuid.uuid4()),
                object_id=existing.id,
                revision=existing.revision or DEFAULT_REVISION,
                iteration=new_iteration,
                git_commit_hash=git_hash,
                content_hash=content_hash,
                file_size=file_size,
                filename=stored_name,
                relative_path=relative,
                creo_release=creo_release,
                created_by=user.user_name,
                created_at=now,
                comment=message,
            )
            session.add(version)
            session.flush()
            existing.current_version_id = version.id
            try:
                session.flush()
            except Exception as exc:
                logger.exception("Metadata failed after storing later save %s", relative)
                if captured_head:
                    self._store.restore_checkpoint(repo, captured_head)
                raise RepositoryError(
                    "The later save was stored but project metadata could not be updated. "
                    "The repository was restored and the file was not added.",
                    details={"file": stored_name},
                ) from exc
            try:
                set_file_readonly(destination)
            except Exception:
                logger.warning("Could not mark %s read-only after import", destination)
            self._activities.record(
                session,
                ActivityAction.CHECKED_IN,
                user,
                project_id=project.id,
                object_id=existing.id,
                details={"filename": stored_name, "relative_path": relative, "iteration": new_iteration},
            )
            logger.info("Recorded later save %s as %s.%s", stored_name, existing.revision, new_iteration)
            return existing

    @staticmethod
    def _later_save_relative(existing: EngineeringObject, stored_name: str) -> str:
        parent = Path(str(existing.relative_path or "").replace("\\", "/")).parent
        relative = stored_name if parent.as_posix() == "." else (parent / stored_name).as_posix()
        return assert_safe_relative_path(relative).as_posix()

    def _stage_later_workspace_save(
        self,
        project: Project,
        existing: EngineeringObject,
        source_path: Path,
        stored_name: str,
    ) -> Path:
        """Put a later Creo save in the workspace. Check-in records the version."""
        relative = self._later_save_relative(existing, stored_name)
        destination = ensure_within(self._vault(project), self._vault(project) / Path(relative))
        with self._locks.acquire(project.uuid):
            copy_file(source_path, destination)
            try:
                set_file_writable(destination)
            except Exception:
                logger.warning("Could not mark %s writable after adding a later save", destination)
        logger.info("Staged later save %s in the workspace for %s", stored_name, existing.filename)
        return destination

    def import_upload(
        self,
        session: Session,
        project: Project,
        filename: str,
        data: bytes,
        relative_path: str | None = None,
        comment: str | None = None,
    ) -> EngineeringObject:
        if not data:
            raise ValidationAppError("The uploaded file is empty.")
        safe_name = sanitize_filename(filename)
        with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{safe_name}") as handle:
            handle.write(data)
            temp_path = Path(handle.name)
        try:
            return self.import_file(
                session,
                project,
                temp_path,
                original_name=safe_name,
                relative_path=relative_path,
                comment=comment,
            )
        finally:
            temp_path.unlink(missing_ok=True)

    def object_history(self, session: Session, object_uuid: str) -> list[ObjectVersion]:
        obj = self.get_object(session, object_uuid)
        stmt = (
            select(ObjectVersion)
            .where(ObjectVersion.object_id == obj.id)
            .order_by(ObjectVersion.iteration.desc(), ObjectVersion.id.desc())
        )
        return list(session.scalars(stmt))

    def existing_logical(
        self,
        session: Session,
        project_id: int,
        relative: str,
        exclude_id: int | None = None,
    ) -> EngineeringObject | None:
        extras = self._cad_extensions()
        logical = CreoFileManager.logical_repo_path(relative, extras)
        objects = session.scalars(
            select(EngineeringObject).where(EngineeringObject.project_id == project_id)
        )
        for item in objects:
            if exclude_id is not None and item.id == exclude_id:
                continue
            if CreoFileManager.logical_repo_path(item.relative_path, extras) == logical:
                return item
        return None

    def search(
        self,
        session: Session,
        project: Project,
        query: str | None = None,
        object_type: str | None = None,
        lifecycle_state: str | None = None,
    ) -> list[EngineeringObject]:
        return self.list_objects(
            session,
            project.id,
            query=query,
            object_type=object_type,
            lifecycle_state=lifecycle_state,
        )

    def list_folder_view(
        self,
        session: Session,
        project_id: int,
        current_folder: str = "",
    ) -> tuple[list[EngineeringObject], list[dict]]:
        """Folders from the imported catalog; full rows only for files in this folder."""
        from creopdm.utils.folders import folder_index, normalize_folder_query

        current = normalize_folder_query(current_folder)
        stmt = select(
            EngineeringObject.relative_path,
            EngineeringObject.updated_at,
            EngineeringObject.uuid,
        ).where(EngineeringObject.project_id == project_id)
        if current:
            stmt = stmt.where(EngineeringObject.relative_path.startswith(f"{current}/"))
        rows = session.execute(stmt).all()
        folder_entries, file_rels = folder_index(list(rows), current)
        files: list[EngineeringObject] = []
        if file_rels:
            files = list(
                session.scalars(
                    select(EngineeringObject)
                    .options(
                        joinedload(EngineeringObject.current_version),
                        joinedload(EngineeringObject.project),
                    )
                    .where(
                        EngineeringObject.project_id == project_id,
                        EngineeringObject.relative_path.in_(file_rels),
                    )
                    .order_by(EngineeringObject.filename.asc())
                ).unique()
            )
        return files, folder_entries

    @staticmethod
    def _remove_copied_file(destination: Path) -> None:
        try:
            if destination.exists():
                destination.unlink()
        except OSError:
            logger.warning("Could not remove copied file after failed import: %s", destination)
