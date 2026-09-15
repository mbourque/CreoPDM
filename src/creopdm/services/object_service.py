"""Engineering objects: import, classify, and initial version storage."""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session, joinedload

from creopdm.constants import (
    DEFAULT_REVISION,
    INITIAL_ITERATION,
    ActivityAction,
    LifecycleState,
)
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import (
    CreoPDMError,
    DuplicateObjectError,
    ObjectNotFoundError,
    PathValidationError,
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
from creopdm.utils.classify import classify_filename, default_folder_for
from creopdm.utils.files import copy_file, set_file_readonly
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
    ) -> None:
        self._store = version_store
        self._locks = locks
        self._activities = activities
        self._users = users

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

    def delete_object(self, session: Session, object_uuid: str) -> dict[str, str]:
        """Remove the object from the vault and project metadata.

        Does not touch workspace files; callers should purge those first or after.
        """
        obj = self.get_object(session, object_uuid)
        project = obj.project
        user = self._users.get_current_user()
        filename = obj.filename
        relative = obj.relative_path
        uuid_value = obj.uuid
        repo = Path(project.repository_path)
        with self._locks.acquire(project.uuid):
            captured = self._store.capture_checkpoint(repo)
            try:
                self._store.remove_files(repo, [relative], f"Remove {filename}", user)
            except CreoPDMError:
                raise
            except Exception as exc:
                logger.exception("Git remove failed for %s", relative)
                raise RepositoryError(
                    f"Could not remove {filename} from the project vault.",
                    details={"file": filename, "relative_path": relative},
                ) from exc
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
                logger.exception("Metadata failed after removing %s", relative)
                if captured:
                    self._store.restore_checkpoint(repo, captured)
                raise RepositoryError(
                    "The file was removed from storage but project metadata could not be updated. "
                    "The repository was restored.",
                    details={"file": filename},
                ) from exc
        logger.info("Removed object %s (%s)", uuid_value, relative)
        return {"uuid": uuid_value, "filename": filename, "relative_path": relative}

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
        logical_name = CreoFileManager.logical_filename(stored_name)
        object_type = classify_filename(stored_name)
        extension = Path(logical_name).suffix.lower() or Path(stored_name).suffix.lower()
        stem = Path(logical_name).stem

        if relative_path:
            rel = assert_safe_relative_path(relative_path)
            if rel.name != stored_name:
                rel = rel.parent / stored_name
        else:
            rel = Path(default_folder_for(object_type)) / stored_name
        rel = assert_safe_relative_path(str(rel).replace("\\", "/"))
        relative = rel.as_posix()

        existing = self.existing_logical(session, project.id, relative)
        if existing is not None:
            raise DuplicateObjectError(
                f"{stored_name} is already in this project.",
                details={"relative_path": relative, "existing": existing.filename},
            )

        repo = Path(project.repository_path)
        destination = ensure_within(repo, repo / rel)
        user = self._users.get_current_user()
        content_hash = calculate_sha256(source_path)
        file_size = source_path.stat().st_size
        message = (comment or f"Add {stored_name}").strip()
        if not message:
            raise ValidationAppError("A comment is required when adding a file.")

        captured_head = self._store.capture_checkpoint(repo)
        object_uuid = str(uuid.uuid4())
        version_uuid = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        with self._locks.acquire(project.uuid):
            copy_file(source_path, destination)
            try:
                git_hash = self._store.store_version(
                    repo,
                    [relative],
                    message,
                    user,
                )
            except Exception:
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
        logical = CreoFileManager.logical_repo_path(relative)
        objects = session.scalars(
            select(EngineeringObject).where(EngineeringObject.project_id == project_id)
        )
        for item in objects:
            if exclude_id is not None and item.id == exclude_id:
                continue
            if CreoFileManager.logical_repo_path(item.relative_path) == logical:
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

    @staticmethod
    def _remove_copied_file(destination: Path) -> None:
        try:
            if destination.exists():
                destination.unlink()
        except OSError:
            logger.warning("Could not remove copied file after failed import: %s", destination)
