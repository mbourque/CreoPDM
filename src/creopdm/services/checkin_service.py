"""PDM check-in: vault the workspace file, increment iteration, release the lock."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy import select

from creopdm.constants import ActivityAction, CheckoutStatus, DEFAULT_REVISION, LifecycleState
from creopdm.creo.base import CreoConnector, CreoModelRef
from creopdm.exceptions import (
    CheckoutOwnershipError,
    CreoPDMError,
    PathValidationError,
    ReleasedObjectError,
    RepositoryError,
    ValidationAppError,
)
from creopdm.logging_setup import get_logger
from creopdm.models.object import EngineeringObject
from creopdm.models.parameter import Parameter
from creopdm.models.version import ObjectVersion
from creopdm.services.activity_service import ActivityService
from creopdm.services.checkout_service import CheckoutService
from creopdm.services.lock_manager import ProjectLockManager
from creopdm.services.object_service import ObjectService
from creopdm.services.workspace_service import WorkspaceService
from creopdm.storage.base import VersionStore
from creopdm.utils.creo_header import creo_release_for
from creopdm.utils.files import copy_file, set_file_readonly, set_file_writable
from creopdm.utils.hashing import calculate_sha256
from creopdm.utils.identity import CurrentUserProvider

logger = get_logger("checkin")


class CheckinService:
    def __init__(
        self,
        objects: ObjectService,
        checkouts: CheckoutService,
        workspaces: WorkspaceService,
        version_store: VersionStore,
        locks: ProjectLockManager,
        activities: ActivityService,
        users: CurrentUserProvider,
        creo: CreoConnector,
    ) -> None:
        self._objects = objects
        self._checkouts = checkouts
        self._workspaces = workspaces
        self._store = version_store
        self._locks = locks
        self._activities = activities
        self._users = users
        self._creo = creo

    def set_connector(self, connector: CreoConnector) -> None:
        self._creo = connector

    def preview(self, session: Session, object_uuid: str) -> dict[str, str | bool | list]:
        obj = self._objects.get_object(session, object_uuid)
        project = obj.project
        user = self._users.get_current_user()
        checkout = self._checkouts.active_for(session, obj.id)
        view = self._checkouts.describe(obj, checkout, user)
        workspace_name = obj.filename
        try:
            workspace_name = self._workspaces.locate_content(project, obj).name
        except PathValidationError:
            pass
        modified = self._workspaces.is_modified(project, obj)
        pending = self._workspaces.pending_workspace_save(project, obj)
        force_checkin = (
            checkout is None
            and pending is not None
            and obj.lifecycle_state == LifecycleState.IN_WORK.value
        )
        current = f"{obj.revision}.{obj.iteration}"
        nxt = f"{obj.revision}.{obj.iteration + 1}"
        siblings = self._objects.list_objects(session, project.id)
        new_files = self._new_files_for(project, obj, siblings)
        warning = ""
        if force_checkin:
            warning = (
                f"{workspace_name} is not checked out. Checking in will record this "
                "vault save without a checkout lock."
            )
        return {
            "filename": workspace_name,
            "current_display": current,
            "next_display": nxt,
            "file_modified": modified,
            "parameters_changed": False,
            "dependencies_unchanged": True,
            "can_checkin": view.can_checkin or force_checkin,
            "force_checkin": force_checkin,
            "warning": warning,
            "new_files": new_files,
        }

    def checkin(
        self,
        session: Session,
        object_uuid: str,
        comment: str,
        add_relative_paths: list[str] | None = None,
    ) -> EngineeringObject:
        message = (comment or "").strip()
        if not message:
            raise ValidationAppError("A check-in comment is required.")
        obj = self._objects.get_object(session, object_uuid)
        project = obj.project
        user = self._users.get_current_user()
        self._workspaces.ensure_vault(project)
        repo = self._workspaces.vault_for(project)
        to_add = [item.replace("\\", "/").strip() for item in (add_relative_paths or []) if item.strip()]

        with self._locks.acquire(project.uuid):
            existing = self._checkouts.active_for(session, obj.id)
            record = None
            if existing is not None:
                record = self._checkouts.require_owned(session, obj, user)
            else:
                pending = self._workspaces.pending_workspace_save(project, obj)
                if pending is None:
                    raise CheckoutOwnershipError(f"{obj.filename} is not checked out.")
                if obj.lifecycle_state != LifecycleState.IN_WORK.value:
                    raise ReleasedObjectError(
                        f"{obj.filename} is {obj.lifecycle_state.replace('_', ' ').title()} and cannot be checked in."
                    )
            if to_add:
                self._add_workspace_files(session, project, to_add, message, obj.filename)
            workspace_file = self._workspaces.locate_content(project, obj)
            content_hash = calculate_sha256(workspace_file)
            file_size = workspace_file.stat().st_size
            creo_release = creo_release_for(workspace_file, workspace_file.name)
            old_relative = obj.relative_path.replace("\\", "/")
            new_relative = self._workspaces.sibling_relative(obj, workspace_file)
            clash = self._objects.existing_logical(session, project.id, new_relative, exclude_id=obj.id)
            if clash is not None:
                raise ValidationAppError(
                    f"{workspace_file.name} is already in this project as {clash.filename}.",
                    details={"relative_path": new_relative},
                )
            repo_file = self._workspaces.repository_file(project, new_relative)
            captured_head = self._store.capture_checkpoint(repo)
            previous_git = obj.current_version.git_commit_hash if obj.current_version else None
            copy_file(workspace_file, repo_file)
            same_bytes = (
                obj.current_version is not None
                and content_hash == obj.current_version.content_hash
            )
            path_changed = (
                old_relative != new_relative
                or workspace_file.name != (obj.filename or "")
            )
            # Same content with a Creo save-number rename (e.g. revert .prt.3 → .prt.1)
            # is still a real check-in.
            if same_bytes and not to_add and not path_changed:
                raise ValidationAppError(
                    "No changes to check in. Use Undo Checkout to release the lock without a new version.",
                    details={"filename": obj.filename},
                )
            remove_paths = [old_relative] if old_relative != new_relative else []
            try:
                git_hash = self._store.store_version(
                    repo,
                    [new_relative],
                    message,
                    user,
                    allow_empty=same_bytes,
                    remove_relative_paths=remove_paths,
                )
            except Exception:
                logger.exception("Git store failed during check-in of %s", obj.filename)
                raise

            now = datetime.now(timezone.utc)
            new_iteration = obj.iteration + 1
            obj.filename = workspace_file.name
            obj.relative_path = new_relative
            version = ObjectVersion(
                uuid=str(uuid.uuid4()),
                object_id=obj.id,
                revision=obj.revision or DEFAULT_REVISION,
                iteration=new_iteration,
                git_commit_hash=git_hash or previous_git,
                content_hash=content_hash,
                file_size=file_size,
                filename=obj.filename,
                relative_path=new_relative,
                creo_release=creo_release,
                created_by=user.user_name,
                created_at=now,
                comment=message,
            )
            session.add(version)
            try:
                session.flush()
                obj.iteration = new_iteration
                obj.current_version_id = version.id
                obj.updated_at = now
                if record is not None:
                    record.status = CheckoutStatus.RETURNED.value
                session.flush()
            except Exception as exc:
                logger.exception("Metadata failed after storing check-in of %s", obj.filename)
                if captured_head:
                    self._store.restore_checkpoint(repo, captured_head)
                raise RepositoryError(
                    "The file was stored but project metadata could not be updated. "
                    "The checkout was not released.",
                    details={"file": obj.filename},
                ) from exc

            self._capture_parameters(session, obj, version, workspace_file)
            try:
                set_file_readonly(workspace_file)
            except Exception:
                logger.warning("Could not mark workspace file read-only after check-in: %s", workspace_file)
            try:
                set_file_readonly(repo_file)
            except Exception:
                pass
            try:
                self._workspaces.materialize(project, obj, writable=False, overwrite_modified=True)
            except Exception:
                logger.warning("Could not refresh the canonical workspace copy after check-in: %s", obj.filename)

            self._activities.record(
                session,
                ActivityAction.CHECKED_IN,
                user,
                project_id=project.id,
                object_id=obj.id,
                details={"iteration": new_iteration, "comment": message, "added": to_add},
            )
            logger.info("Checked in %s as %s.%s", obj.filename, obj.revision, new_iteration)
            session.refresh(obj)
            return obj

    def revert_to_version(
        self,
        session: Session,
        object_uuid: str,
        version_uuid: str,
    ) -> EngineeringObject:
        """Restore an older version onto vault (and rematerialize), as a new check-in."""
        obj = self._objects.get_object(session, object_uuid)
        project = obj.project
        user = self._users.get_current_user()
        target = session.scalar(
            select(ObjectVersion).where(ObjectVersion.uuid == version_uuid)
        )
        if target is None or target.object_id != obj.id:
            raise ValidationAppError("Choose a version from this file’s history.")
        if obj.current_version_id is not None and target.id == obj.current_version_id:
            raise ValidationAppError(
                "That is already the current version. Choose an older version to revert."
            )
        if not (target.git_commit_hash or "").strip():
            raise ValidationAppError("This version has no stored vault content to restore.")

        display = f"{target.revision}.{target.iteration}"
        comment = f"Reverted to {display}"
        self._workspaces.ensure_vault(project)
        repo = self._workspaces.vault_for(project)
        rel_candidates = []
        for raw in (target.relative_path, obj.relative_path, target.filename, obj.filename):
            text = str(raw or "").replace("\\", "/").strip().lstrip("/")
            if text and text not in rel_candidates:
                rel_candidates.append(text)
        data: bytes | None = None
        source_rel = ""
        last_error: Exception | None = None
        for rel in rel_candidates:
            try:
                data = self._store.get_version(repo, rel, target.git_commit_hash)
                source_rel = rel
                break
            except Exception as exc:
                last_error = exc
                continue
        if data is None:
            raise ValidationAppError(
                f"Could not read version {display} from vault history.",
                details={"version": version_uuid},
            ) from last_error

        # Always restore to the version's recorded path/name (e.g. …/start_part.prt.1),
        # not whichever path git show happened to accept for reading bytes.
        dest_rel = ""
        for raw in (target.relative_path, target.filename):
            text = str(raw or "").replace("\\", "/").strip().lstrip("/")
            if not text:
                continue
            if "/" not in text:
                parent = Path(str(obj.relative_path or "").replace("\\", "/")).parent.as_posix()
                if parent and parent != ".":
                    text = f"{parent}/{Path(text).name}"
                else:
                    text = Path(text).name
            dest_rel = text
            break
        if not dest_rel:
            dest_rel = source_rel.replace("\\", "/").lstrip("/")

        tip_rel = str(obj.relative_path or "").replace("\\", "/").strip().lstrip("/")
        with self._locks.acquire(project.uuid):
            existing = self._checkouts.active_for(session, obj.id)
            if existing is not None:
                self._checkouts.require_owned(session, obj, user)
            else:
                # Need a writable checkout so check-in can record the restored bytes.
                self._checkouts.checkout(session, object_uuid)

            # Restore the Git path/name from that commit (e.g. start_part.prt.1), not
            # overwrite the current tip filename (e.g. start_part.prt.3).
            try:
                self._store.restore_version(repo, dest_rel, target.git_commit_hash)
            except Exception:
                logger.warning(
                    "git checkout of %s@%s failed; writing blob directly",
                    dest_rel,
                    (target.git_commit_hash or "")[:8],
                    exc_info=True,
                )
            dest = self._workspaces.file_path(project, dest_rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.is_file() or dest.read_bytes() != data:
                if dest.exists():
                    set_file_writable(dest)
                dest.write_bytes(data)
            try:
                set_file_writable(dest)
            except Exception:
                pass

            # Drop higher .N siblings so locate_content prefers the restored save
            # (e.g. .prt.1) instead of the tip (.prt.3). Leave obj.filename as the tip
            # so check-in still git-rms the old tip path when the basename changes.
            self._workspaces.purge_newer_creo_saves(project, dest)
            if tip_rel and tip_rel != dest_rel:
                tip_path = self._workspaces.file_path(project, tip_rel)
                try:
                    tip_resolved = tip_path.resolve()
                    dest_resolved = dest.resolve()
                except OSError:
                    tip_resolved = tip_path
                    dest_resolved = dest
                if tip_path.is_file() and tip_resolved != dest_resolved:
                    try:
                        set_file_writable(tip_path)
                        tip_path.unlink()
                        logger.info("Removed tip path after revert: %s", tip_path)
                    except OSError as exc:
                        logger.warning("Could not remove tip path %s: %s", tip_path, exc)
            logger.info(
                "Restored %s bytes from %s@%s → %s for revert to %s",
                len(data),
                source_rel,
                (target.git_commit_hash or "")[:8],
                dest,
                display,
            )

        # Revert always records the restored tip as a new version — never leave the
        # user checked out with a "please check in" prompt.
        try:
            restored = self.checkin(session, object_uuid, comment)
        except Exception:
            try:
                self._checkouts.undo_checkout(session, object_uuid)
            except Exception:
                logger.warning(
                    "Could not release checkout after failed revert check-in of %s",
                    object_uuid,
                    exc_info=True,
                )
            raise
        self._activities.record(
            session,
            ActivityAction.VERSION_RESTORED,
            user,
            project_id=project.id,
            object_id=obj.id,
            details={
                "from_version": version_uuid,
                "from_display": display,
                "to_iteration": restored.iteration,
                "restored_path": dest_rel,
            },
        )
        return restored

    def preview_queue(self, session: Session, project) -> dict[str, str | bool | list]:
        siblings = self._objects.list_objects(session, project.id)
        queue = self._workspaces.project_checkin_queue(project, siblings)
        new_files = []
        for item in queue["new_files"]:
            new_files.append(
                {
                    "filename": item["filename"],
                    "relative_path": item["relative_path"],
                    "path": item["path"],
                    "object_type": item["object_type"],
                    "same_folder": True,
                }
            )
        pending = queue["saves"]
        names = [str(item["filename"]) for item in pending] + [str(item["filename"]) for item in new_files]
        label = names[0] if len(names) == 1 else f"{len(names)} vault files"
        return {
            "filename": label,
            "current_display": "—",
            "next_display": "—",
            "file_modified": bool(names),
            "parameters_changed": False,
            "dependencies_unchanged": True,
            "can_checkin": bool(names),
            "force_checkin": False,
            "warning": "",
            "queue_mode": True,
            "new_files": new_files,
            "object_ids": [str(item["uuid"]) for item in pending],
            "pending_files": [str(item["filename"]) for item in pending],
        }

    def checkin_queue(
        self,
        session: Session,
        project,
        comment: str,
        object_ids: list[str] | None = None,
        add_relative_paths: list[str] | None = None,
    ) -> dict[str, list]:
        message = (comment or "").strip()
        if not message:
            raise ValidationAppError("A check-in comment is required.")
        ok: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        for object_uuid in object_ids or []:
            filename = object_uuid
            try:
                obj = self.checkin(session, object_uuid, message, None)
                ok.append({"uuid": obj.uuid, "filename": obj.filename, "status": "checked_in"})
            except CreoPDMError as exc:
                try:
                    filename = self._objects.get_object(session, object_uuid).filename
                except CreoPDMError:
                    pass
                failed.append(
                    {
                        "uuid": object_uuid,
                        "filename": filename,
                        "code": exc.code,
                        "message": exc.message,
                    }
                )
        to_add = [item.replace("\\", "/").strip() for item in (add_relative_paths or []) if item.strip()]
        if to_add:
            try:
                self._add_workspace_files(session, project, to_add, message, "workspace")
                for relative in to_add:
                    ok.append({"uuid": "", "filename": Path(relative).name, "status": "added", "path": relative})
            except CreoPDMError as exc:
                failed.append(
                    {
                        "uuid": "",
                        "filename": Path(to_add[0]).name if to_add else "",
                        "code": exc.code,
                        "message": exc.message,
                    }
                )
        if not ok and not failed:
            raise ValidationAppError("There are no vault files to check in.")
        return {"ok": ok, "failed": failed}

    def _new_files_for(
        self,
        project,
        obj: EngineeringObject,
        siblings: list[EngineeringObject],
    ) -> list[dict[str, str | bool]]:
        folder = Path(self._workspaces.workspace_relative(obj)).parent.as_posix()
        if folder == ".":
            folder = ""
        found = []
        for item in self._workspaces.list_untracked(project, siblings):
            parent = Path(str(item["relative_path"]).replace("\\", "/")).parent.as_posix()
            if parent == ".":
                parent = ""
            found.append(
                {
                    "filename": item["filename"],
                    "relative_path": item["relative_path"],
                    "path": item["path"],
                    "object_type": item["object_type"],
                    "same_folder": parent.lower() == folder.lower(),
                }
            )
        found.sort(key=lambda row: (not row["same_folder"], str(row["filename"]).lower()))
        return found

    def _add_workspace_files(
        self,
        session: Session,
        project,
        relative_paths: list[str],
        comment: str,
        source_label: str = "workspace",
    ) -> None:
        siblings = self._objects.list_objects(session, project.id)
        available = {
            str(item["relative_path"]).replace("\\", "/").lower(): item
            for item in self._workspaces.list_untracked(project, siblings)
        }
        jobs: list[tuple[Path, str | None, str | None]] = []
        for relative in relative_paths:
            key = relative.replace("\\", "/").lower()
            item = available.get(key)
            if item is None:
                raise ValidationAppError(
                    f"{Path(relative).name} is not a new file in the vault.",
                    details={"relative_path": relative},
                )
            source = Path(str(item["path"]))
            if not source.is_file():
                raise ValidationAppError(
                    f"{item['filename']} is no longer in the vault.",
                    details={"path": str(source)},
                )
            jobs.append((source, source.name, relative))
        if not jobs:
            return
        for outcome in self._objects.import_files(session, project, jobs, comment):
            if outcome.error is not None:
                raise outcome.error
            logger.info("Added %s during check-in of %s", outcome.filename, source_label)

    def _capture_parameters(
        self,
        session: Session,
        obj: EngineeringObject,
        version: ObjectVersion,
        path: Path,
    ) -> None:
        if not self._creo.is_available() or not obj.object_type.startswith("CREO_"):
            return
        try:
            model = CreoModelRef(name=obj.filename, path=path, object_type=obj.object_type)
            for param in self._creo.get_parameters(model):
                session.add(
                    Parameter(
                        object_id=obj.id,
                        version_id=version.id,
                        name=param.name,
                        value=param.value,
                        data_type=param.data_type,
                        units=param.units,
                    )
                )
        except Exception:
            logger.warning("Creo parameter capture skipped for %s", obj.filename)
