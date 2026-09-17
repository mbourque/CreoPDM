"""Engineering objects: import, classify, and initial version storage."""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import dataclass
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
from creopdm.utils.files import copy_file, copy_file_hashed, set_file_readonly, set_file_writable
from creopdm.utils.hashing import calculate_sha256
from creopdm.utils.identity import CurrentUserProvider
from creopdm.utils.paths import (
    assert_safe_relative_path,
    ensure_within,
    sanitize_filename,
)

logger = get_logger("objects")


@dataclass
class ImportJobResult:
    source: Path
    filename: str
    obj: EngineeringObject | None = None
    error: CreoPDMError | None = None


@dataclass
class _ImportPlan:
    source: Path
    stored_name: str
    relative: str
    logical: str
    stem: str
    extension: str
    object_type: str
    content_hash: str
    file_size: int
    creo_release: str | None
    kind: str
    existing: EngineeringObject | None = None
    old_relative: str | None = None


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
        results = self.import_files(
            session,
            project,
            [(source_path, original_name, relative_path)],
            comment,
        )
        if not results:
            raise PathValidationError("The selected file does not exist.")
        outcome = results[0]
        if outcome.error is not None:
            raise outcome.error
        if outcome.obj is None:
            raise PathValidationError("The selected file does not exist.")
        return outcome.obj

    def import_files(
        self,
        session: Session,
        project: Project,
        jobs: list[tuple[Path, str | None, str | None]],
        comment: str | None = None,
    ) -> list[ImportJobResult]:
        """Copy accepted files, then one Git add and one commit.

        Ignored, duplicate, and older saves are skipped per file. A later Creo
        numbered save of an existing object becomes the next iteration.
        """
        if not jobs:
            return []
        extras = self._cad_extensions()
        ignore = self._config.ignore_patterns() if self._config else None
        user = self._users.get_current_user()
        index = self._logical_index(session, project.id)
        checkouts = self._active_checkouts(session, [obj.id for obj in index.values()])
        results: list[ImportJobResult] = []
        plans: list[_ImportPlan] = []
        pending_logical: dict[str, str] = {}
        for source_path, original_name, relative_path in jobs:
            planned, error = self._plan_import(
                project,
                source_path,
                original_name,
                relative_path,
                extras,
                ignore,
                index,
                checkouts,
                user.user_name,
                pending_logical,
            )
            filename = (original_name or source_path.name) if source_path else ""
            if error is not None:
                results.append(ImportJobResult(source=source_path, filename=Path(filename).name, error=error))
                continue
            assert planned is not None
            pending_logical[planned.logical] = planned.stored_name
            plans.append(planned)
            results.append(ImportJobResult(source=source_path, filename=planned.stored_name))

        if not plans:
            return results

        git_plans = [item for item in plans if item.kind in {"new", "later"}]
        stage_plans = [item for item in plans if item.kind == "stage"]
        raw_comment = (comment or "").strip()
        if git_plans:
            if raw_comment:
                message = raw_comment
            elif len(git_plans) == 1:
                message = f"Add {git_plans[0].stored_name}"
            else:
                message = f"Add {len(git_plans)} files"
        else:
            message = raw_comment or "Add files"

        created: list[Path] = []
        repo = self._vault(project)
        now = datetime.now(timezone.utc)

        with self._locks.acquire(project.uuid):
            for plan in stage_plans:
                if plan.existing is None:
                    self._mark_result(
                        results,
                        plan,
                        error=RepositoryError("Missing object for later save."),
                    )
                    continue
                try:
                    self._stage_later_workspace_save(
                        project,
                        plan.existing,
                        plan.source,
                        plan.stored_name,
                    )
                except CreoPDMError as except_error:
                    self._mark_result(results, plan, error=except_error)
                except Exception as exc:
                    self._mark_result(results, plan, error=RepositoryError(str(exc)))
            captured_head = self._store.capture_checkpoint(repo) if git_plans else None
            try:
                total = len(git_plans)
                for index, plan in enumerate(git_plans, start=1):
                    destination = ensure_within(repo, repo / Path(plan.relative))
                    created_copy, digest, size = copy_file_hashed(plan.source, destination)
                    plan.content_hash = digest
                    plan.file_size = size
                    plan.creo_release = creo_release_for(destination, plan.stored_name)
                    if created_copy:
                        created.append(destination)
                    if index == 1 or index == total or index % 25 == 0:
                        logger.info("Copied %s/%s from source", index, total)
                if git_plans:
                    add_paths = [plan.relative for plan in git_plans]
                    remove_paths = list(
                        dict.fromkeys(
                            plan.old_relative
                            for plan in git_plans
                            if plan.kind == "later"
                            and plan.old_relative
                            and plan.old_relative != plan.relative
                        )
                    )
                    git_hash = self._store.store_version(
                        repo,
                        add_paths,
                        message,
                        user,
                        remove_relative_paths=remove_paths,
                    )
                    self._record_batch_versions(
                        session,
                        project,
                        git_plans,
                        git_hash,
                        message,
                        user.user_name,
                        now,
                    )
                    self._record_import_activity(session, project, git_plans, user)
                    for plan in git_plans:
                        destination = ensure_within(repo, repo / Path(plan.relative))
                        try:
                            set_file_readonly(destination)
                        except Exception:
                            logger.warning("Could not mark %s read-only after import", destination)
            except Exception as exc:
                logger.exception("Batch import failed for %s files", len(git_plans))
                if captured_head:
                    self._store.restore_checkpoint(repo, captured_head)
                for path in created:
                    self._remove_copied_file(path)
                if isinstance(exc, CreoPDMError):
                    raise
                raise RepositoryError(
                    "The files could not be added to the project.",
                    details={"count": len(git_plans)},
                ) from exc

        for plan in git_plans:
            if plan.existing is not None:
                self._mark_result(results, plan, obj=plan.existing)
        for plan in stage_plans:
            if plan.existing is not None:
                self._mark_result(results, plan, obj=plan.existing)
        logger.info("Imported %s files (%s git, %s staged)", len(plans), len(git_plans), len(stage_plans))
        return results

    def _plan_import(
        self,
        _project: Project,
        source_path: Path,
        original_name: str | None,
        relative_path: str | None,
        extras: list[str],
        ignore: list[str] | None,
        index: dict[str, EngineeringObject],
        checkouts: dict[int, Checkout],
        user_name: str,
        pending_logical: dict[str, str],
    ) -> tuple[_ImportPlan | None, CreoPDMError | None]:
        try:
            if not source_path.is_file():
                raise PathValidationError(
                    "The selected file was not found.",
                    details={"path": str(source_path)},
                )
            display_name = sanitize_filename(original_name or source_path.name)
            stored_name = CreoFileManager.canonical_repository_name(display_name)
            if CreoFileManager.is_ignored(stored_name, ignore):
                raise PathValidationError(
                    f"{stored_name} is an ignored session file and is not stored in CreoPDM.",
                    details={"filename": stored_name},
                )
            logical_name = CreoFileManager.logical_filename(stored_name, extras)
            data_extras = self._config.data_cad_extensions() if self._config else None
            models = self._config.model_cad_extensions() if self._config else None
            object_type = classify_filename(
                stored_name,
                extra_cad_extensions=data_extras,
                model_extensions=models,
                document_extensions=self._config.document_extensions() if self._config else None,
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
            logical = CreoFileManager.logical_repo_path(relative, extras)
            if logical in pending_logical:
                other = pending_logical[logical]
                raise DuplicateObjectError(
                    f"{stored_name} is already being added as {other}.",
                    details={"relative_path": relative, "existing": other},
                )
            existing = index.get(logical)
            kind = "new"
            old_relative: str | None = None
            if existing is not None:
                incoming_n = CreoFileManager.save_number(stored_name, extras)
                recorded_n = CreoFileManager.save_number(existing.filename, extras)
                if incoming_n > recorded_n:
                    if existing.lifecycle_state != LifecycleState.IN_WORK.value:
                        raise ReleasedObjectError(
                            f"{existing.filename} is {existing.lifecycle_state.replace('_', ' ').title()} "
                            "and cannot take a later save.",
                            details={"uuid": existing.uuid},
                        )
                    active = checkouts.get(existing.id)
                    if active is not None:
                        if active.user_name != user_name:
                            raise ObjectAlreadyCheckedOutError(
                                f"{existing.filename} is checked out by {active.user_name}.",
                                details={"uuid": existing.uuid, "user": active.user_name},
                            )
                        kind = "stage"
                    else:
                        kind = "later"
                    relative = self._later_save_relative(existing, stored_name)
                    old_relative = existing.relative_path.replace("\\", "/")
                elif incoming_n < recorded_n:
                    raise DuplicateObjectError(
                        f"{stored_name} is an older save of {existing.filename}, which is already in this project.",
                        details={"relative_path": existing.relative_path, "existing": existing.filename},
                    )
                else:
                    raise DuplicateObjectError(
                        f"{stored_name} is already in this project as {existing.filename}.",
                        details={"relative_path": existing.relative_path, "existing": existing.filename},
                    )
            content_hash = ""
            file_size = 0
            creo_release = None
            return (
                _ImportPlan(
                    source=source_path,
                    stored_name=stored_name,
                    relative=relative,
                    logical=logical,
                    stem=stem,
                    extension=extension,
                    object_type=object_type.value,
                    content_hash=content_hash,
                    file_size=file_size,
                    creo_release=creo_release,
                    kind=kind,
                    existing=existing,
                    old_relative=old_relative,
                ),
                None,
            )
        except CreoPDMError as exc:
            return None, exc

    def _logical_index(self, session: Session, project_id: int) -> dict[str, EngineeringObject]:
        extras = self._cad_extensions()
        objects = session.scalars(
            select(EngineeringObject).where(EngineeringObject.project_id == project_id)
        )
        return {
            CreoFileManager.logical_repo_path(obj.relative_path, extras): obj
            for obj in objects
        }

    def _active_checkouts(self, session: Session, object_ids: list[int]) -> dict[int, Checkout]:
        found: dict[int, Checkout] = {}
        for start in range(0, len(object_ids), 400):
            chunk = object_ids[start : start + 400]
            rows = session.scalars(
                select(Checkout).where(
                    Checkout.object_id.in_(chunk),
                    Checkout.status == CheckoutStatus.ACTIVE.value,
                )
            )
            for row in rows:
                found[row.object_id] = row
        return found

    @staticmethod
    def _mark_result(
        results: list[ImportJobResult],
        plan: _ImportPlan,
        obj: EngineeringObject | None = None,
        error: CreoPDMError | None = None,
    ) -> None:
        for item in results:
            if item.source != plan.source or item.filename != plan.stored_name:
                continue
            if error is not None:
                item.error = error
            elif obj is not None and item.error is None:
                item.obj = obj
            return

    def _record_batch_versions(
        self,
        session: Session,
        project: Project,
        plans: list[_ImportPlan],
        git_hash: str,
        message: str,
        user_name: str,
        now: datetime,
    ) -> None:
        for plan in plans:
            if plan.kind == "new":
                obj = EngineeringObject(
                    uuid=str(uuid.uuid4()),
                    project_id=project.id,
                    number=plan.stem.upper(),
                    name=plan.stem,
                    filename=plan.stored_name,
                    extension=plan.extension,
                    object_type=plan.object_type,
                    relative_path=plan.relative,
                    revision=DEFAULT_REVISION,
                    iteration=INITIAL_ITERATION,
                    lifecycle_state=LifecycleState.IN_WORK.value,
                    created_at=now,
                    updated_at=now,
                )
                session.add(obj)
                plan.existing = obj
            elif plan.kind == "later" and plan.existing is not None:
                obj = plan.existing
                obj.filename = plan.stored_name
                obj.relative_path = plan.relative
                obj.updated_at = now
                obj.iteration = obj.iteration + 1
        session.flush()
        pairs: list[tuple[EngineeringObject, ObjectVersion]] = []
        for plan in plans:
            obj = plan.existing
            if obj is None:
                continue
            version = ObjectVersion(
                uuid=str(uuid.uuid4()),
                object_id=obj.id,
                revision=obj.revision or DEFAULT_REVISION,
                iteration=obj.iteration,
                git_commit_hash=git_hash,
                content_hash=plan.content_hash,
                file_size=plan.file_size,
                filename=plan.stored_name,
                relative_path=plan.relative,
                creo_release=plan.creo_release,
                created_by=user_name,
                created_at=now,
                comment=message,
            )
            session.add(version)
            pairs.append((obj, version))
        session.flush()
        for obj, version in pairs:
            obj.current_version_id = version.id
            obj.updated_at = now
        session.flush()

    def _record_import_activity(self, session: Session, project: Project, plans: list[_ImportPlan], user) -> None:
        new_plans = [plan for plan in plans if plan.kind == "new"]
        later_plans = [plan for plan in plans if plan.kind == "later"]
        if len(new_plans) == 1:
            plan = new_plans[0]
            self._activities.record(
                session,
                ActivityAction.OBJECT_ADDED,
                user,
                project_id=project.id,
                object_id=plan.existing.id if plan.existing is not None else None,
                details={"filename": plan.stored_name, "relative_path": plan.relative},
            )
        elif new_plans:
            self._activities.record(
                session,
                ActivityAction.OBJECT_ADDED,
                user,
                project_id=project.id,
                object_id=None,
                details={
                    "count": len(new_plans),
                    "filenames": [plan.stored_name for plan in new_plans[:20]],
                },
            )
        if len(later_plans) == 1:
            plan = later_plans[0]
            iteration = plan.existing.iteration if plan.existing is not None else None
            self._activities.record(
                session,
                ActivityAction.CHECKED_IN,
                user,
                project_id=project.id,
                object_id=plan.existing.id if plan.existing is not None else None,
                details={
                    "filename": plan.stored_name,
                    "relative_path": plan.relative,
                    "iteration": iteration,
                },
            )
        elif later_plans:
            self._activities.record(
                session,
                ActivityAction.CHECKED_IN,
                user,
                project_id=project.id,
                object_id=None,
                details={"count": len(later_plans), "iteration": True},
            )

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
