"""PDM check-in: vault the workspace file, increment iteration, release the lock."""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session
from sqlalchemy import select

from creopdm.constants import ActivityAction, CheckoutStatus, DEFAULT_REVISION, LifecycleState
from creopdm.creo.base import CreoConnector, CreoModelRef
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import (
    CheckoutOwnershipError,
    CreoPDMError,
    PathValidationError,
    ReleasedObjectError,
    RepositoryError,
    ValidationAppError,
    batch_failure,
)
from creopdm.logging_setup import get_logger
from creopdm.models.object import EngineeringObject
from creopdm.models.parameter import Parameter
from creopdm.models.version import ObjectVersion
from creopdm.product_state import ensure_product_allows
from creopdm.services.activity_service import ActivityService
from creopdm.services.checkout_service import CheckoutService
from creopdm.services.lock_manager import ProductLockManager
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
        locks: ProductLockManager,
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

    @staticmethod
    def _carry_metadata(session: Session, source: ObjectVersion, new: ObjectVersion | None) -> None:
        """A revert restores the very bytes of an older version, so its Creo metadata still holds:
        carry it over instead of leaving the new version without any."""
        if new is None or new.id == source.id or new.content_hash != source.content_hash:
            return
        for column in (
            "identity_json",
            "materials_json",
            "units_json",
            "mass_json",
            "family_table_json",
            "features_json",
            "bom_json",
        ):
            if not getattr(new, column) and getattr(source, column):
                setattr(new, column, getattr(source, column))
        has_params = session.scalar(select(Parameter.id).where(Parameter.version_id == new.id).limit(1))
        if has_params is None:
            for row in session.scalars(select(Parameter).where(Parameter.version_id == source.id)):
                session.add(
                    Parameter(
                        object_id=row.object_id,
                        version_id=new.id,
                        name=row.name,
                        value=row.value,
                        data_type=row.data_type,
                        units=row.units,
                        description=row.description,
                        is_designated=row.is_designated,
                    )
                )
        session.flush()

    def set_metadata(self, metadata) -> None:
        """Where Used is kept current by re-reading just the checked-in assembly / drawing."""
        self._metadata = metadata

    def _refresh_where_used(self, session: Session, product, obj: EngineeringObject) -> None:
        metadata = getattr(self, "_metadata", None)
        if metadata is None:
            return
        try:
            metadata.refresh_where_used_for_parents(session, product, [obj])
        except Exception:
            # Never fail a check-in over the index: the full rebuild still repairs it.
            logger.warning("Where Used refresh skipped for %s", obj.filename, exc_info=True)

    def preview(self, session: Session, object_uuid: str) -> dict[str, str | bool | list]:
        obj = self._objects.get_object(session, object_uuid)
        product = obj.product
        user = self._users.get_current_user()
        checkout = self._checkouts.active_for(session, obj.id)
        view = self._checkouts.describe(obj, checkout, user)
        workspace_name = obj.filename
        try:
            workspace_name = self._workspaces.locate_content(product, obj).name
        except PathValidationError:
            pass
        modified = self._workspaces.is_modified(product, obj)
        pending = self._workspaces.pending_workspace_save(product, obj)
        force_checkin = (
            checkout is None
            and pending is not None
            and obj.lifecycle_state == LifecycleState.IN_WORK.value
        )
        current = f"{obj.revision}.{obj.iteration}"
        nxt = f"{obj.revision}.{obj.iteration + 1}"
        siblings = self._objects.list_objects(session, product.id)
        new_files = self._new_files_for(product, obj, siblings)
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
        *,
        allow_unchanged: bool = False,
        source_path: Path | None = None,
        added_out: list[EngineeringObject] | None = None,
    ) -> EngineeringObject:
        """``added_out`` (optional) receives the new objects created from ``add_relative_paths``."""
        message = (comment or "").strip()
        if not message:
            raise ValidationAppError("A check-in comment is required.")
        obj = self._objects.get_object(session, object_uuid)
        product = obj.product
        if product is not None:
            session.refresh(product)
        ensure_product_allows(product, "checkin", action="check in files")
        user = self._users.get_current_user()
        self._workspaces.ensure_vault(product)
        repo = self._workspaces.vault_for(product)
        to_add = [item.replace("\\", "/").strip() for item in (add_relative_paths or []) if item.strip()]

        with self._locks.acquire(product.uuid):
            existing = self._checkouts.active_for(session, obj.id)
            record = None
            if existing is not None:
                record = self._checkouts.require_owned(session, obj, user)
            else:
                pending = self._workspaces.pending_workspace_save(product, obj)
                if pending is None:
                    raise CheckoutOwnershipError(f"{obj.filename} is not checked out.")
                if obj.lifecycle_state != LifecycleState.IN_WORK.value:
                    raise ReleasedObjectError(
                        f"{obj.filename} is {obj.lifecycle_state.replace('_', ' ').title()} and cannot be checked in."
                    )
            if to_add:
                created = self._add_workspace_files(session, product, to_add, message, obj.filename)
                if added_out is not None:
                    added_out.extend(obj_added for _relative, obj_added in created)
            # Revert passes the restored logical tip so a leftover higher .N cannot
            # win locate_content and re-commit the wrong bytes as the "revert".
            if source_path is not None:
                workspace_file = Path(source_path)
                if not workspace_file.is_file():
                    raise ValidationAppError(
                        f"Restored vault tip missing for {obj.filename}.",
                        details={"path": str(workspace_file)},
                    )
            else:
                workspace_file = self._workspaces.locate_content(product, obj)
            content_hash = calculate_sha256(workspace_file)
            file_size = workspace_file.stat().st_size
            creo_release = creo_release_for(workspace_file, workspace_file.name)
            old_relative = obj.relative_path.replace("\\", "/")
            new_relative = self._workspaces.sibling_relative(obj, workspace_file)
            clash = self._objects.existing_logical(session, product.id, new_relative, exclude_id=obj.id)
            if clash is not None:
                raise ValidationAppError(
                    f"{workspace_file.name} is already in this product as {clash.filename}.",
                    details={"relative_path": new_relative},
                )
            repo_file = self._workspaces.repository_file(product, new_relative)
            captured_head = self._store.capture_checkpoint(repo)
            previous_git = obj.current_version.git_commit_hash if obj.current_version else None
            same_bytes = (
                obj.current_version is not None
                and content_hash == obj.current_version.content_hash
            )
            path_changed = old_relative != new_relative
            # Reject unchanged check-ins before touching the vault. A later
            # "No changes" error used to run after copy + purge.
            if same_bytes and not to_add and not path_changed and not allow_unchanged:
                raise ValidationAppError(
                    "No changes to check in. Use Undo Checkout to release the lock without a new version.",
                    details={"filename": obj.filename},
                )
            remove_paths = [old_relative] if old_relative != new_relative else []
            touched = list(dict.fromkeys([new_relative, *remove_paths]))
            # Workspace and vault are usually the same file: nothing is overwritten,
            # so there is nothing to snapshot. Otherwise copy to disk, not into memory.
            try:
                same_file = workspace_file.resolve() == repo_file.resolve()
            except OSError:
                same_file = False
            snapshot_dir = Path(tempfile.mkdtemp(prefix="creopdm-checkin-snap-"))
            snapshots: list[tuple[Path, bool, Path | None]] = []
            try:
                if not same_file:
                    snapshots = self._snapshot_repo_files(repo, [new_relative], snapshot_dir)
                copy_file(workspace_file, repo_file)
                try:
                    os.utime(repo_file, None)
                except OSError:
                    pass
                git_hash = self._store.store_version(
                    repo,
                    [new_relative],
                    message,
                    user,
                    allow_empty=same_bytes or allow_unchanged,
                    remove_relative_paths=remove_paths,
                )
            except Exception:
                logger.exception("Git store failed during check-in of %s", obj.filename)
                self._restore_repo_snapshots(repo, snapshots, touched)
                raise
            finally:
                shutil.rmtree(snapshot_dir, ignore_errors=True)
            # Drop numbered Creo siblings only after Git has the new tip.
            self._workspaces.purge_newer_creo_saves(product, repo_file)

            previous_iteration = int(obj.iteration or 0)
            now = datetime.now(timezone.utc)
            new_iteration = previous_iteration + 1
            tip_name = Path(new_relative).name
            obj.filename = tip_name
            obj.relative_path = new_relative
            version = ObjectVersion(
                uuid=str(uuid.uuid4()),
                object_id=obj.id,
                revision=obj.revision or DEFAULT_REVISION,
                iteration=new_iteration,
                git_commit_hash=git_hash or previous_git,
                content_hash=content_hash,
                file_size=file_size,
                filename=tip_name,
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
                    "The file was stored but product metadata could not be updated. "
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
                self._workspaces.materialize(product, obj, writable=False, overwrite_modified=True)
            except Exception:
                logger.warning("Could not refresh the canonical workspace copy after check-in: %s", obj.filename)

            self._activities.record(
                session,
                ActivityAction.CHECKED_IN,
                user,
                product_id=product.id,
                object_id=obj.id,
                details={
                    "filename": tip_name,
                    "relative_path": new_relative,
                    "iteration": new_iteration,
                    "previous_iteration": previous_iteration,
                    "git_commit": (git_hash or previous_git or "")[:40] or None,
                    "comment": message,
                    "added": to_add,
                },
                comment=message,
            )
            logger.info("Checked in %s as %s.%s", obj.filename, obj.revision, new_iteration)
            session.refresh(obj)
            self._refresh_where_used(session, product, obj)
            return obj

    def revert_to_version(
        self,
        session: Session,
        object_uuid: str,
        version_uuid: str,
    ) -> EngineeringObject:
        """Restore an older version onto vault (and rematerialize), as a new check-in."""
        obj = self._objects.get_object(session, object_uuid)
        product = obj.product
        if product is not None:
            session.refresh(product)
        ensure_product_allows(product, "checkin", action="revert files")
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
        self._workspaces.ensure_vault(product)
        repo = self._workspaces.vault_for(product)
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

        # Always restore onto the logical vault tip (strip Creo .N). Older history
        # rows may still name shaft.prt.1 — Git reads that path; the working tip
        # becomes shaft.prt so Git owns subsequent history.
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
        extras = self._workspaces._cad_extensions()
        dest_name = CreoFileManager.canonical_repository_name(Path(dest_rel).name, extras)
        dest_parent = Path(dest_rel).parent
        if dest_parent.as_posix() == ".":
            dest_rel = dest_name
        else:
            dest_rel = (dest_parent / dest_name).as_posix()

        tip_rel = str(obj.relative_path or "").replace("\\", "/").strip().lstrip("/")
        # Hold the product lock across restore and check-in (RLock: check-in re-enters).
        with self._locks.acquire(product.uuid):
            existing = self._checkouts.active_for(session, obj.id)
            created_checkout = existing is None
            if existing is not None:
                self._checkouts.require_owned(session, obj, user)
            else:
                # Need a writable checkout so check-in can record the restored bytes.
                self._checkouts.checkout(session, object_uuid)

            dest = self._workspaces.file_path(product, dest_rel)
            source_for_checkin = dest
            temp_dir: Path | None = None
            if created_checkout:
                # Restore bytes onto the logical tip path.
                try:
                    self._store.restore_version(repo, source_rel, target.git_commit_hash)
                except Exception:
                    logger.warning(
                        "git checkout of %s@%s failed; writing blob directly",
                        source_rel,
                        (target.git_commit_hash or "")[:8],
                        exc_info=True,
                    )
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.is_file() or dest.read_bytes() != data:
                    if dest.exists():
                        set_file_writable(dest)
                    dest.write_bytes(data)
                try:
                    set_file_writable(dest)
                except Exception:
                    pass

                # Drop numbered siblings so locate_content prefers the logical tip.
                self._workspaces.purge_newer_creo_saves(product, dest)
                if tip_rel and tip_rel != dest_rel:
                    tip_path = self._workspaces.file_path(product, tip_rel)
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
            else:
                # Their checkout already has local edits. Do not overwrite the vault
                # file unless check-in of the restored bytes succeeds. The temp
                # file keeps the vault tip name so check-in stores that path.
                temp_dir = Path(tempfile.mkdtemp(prefix="creopdm-revert-"))
                source_for_checkin = temp_dir / dest.name
                source_for_checkin.write_bytes(data)
            logger.info(
                "Restored %s bytes from %s@%s → %s for revert to %s",
                len(data),
                source_rel,
                (target.git_commit_hash or "")[:8],
                dest,
                display,
            )

            # Revert always records the restored tip as a new version — never leave the
            # user checked out with a "please check in" prompt. Pass the source explicitly
            # so a leftover higher Creo .N cannot win locate_content after a failed purge.
            try:
                restored = self.checkin(
                    session,
                    object_uuid,
                    comment,
                    allow_unchanged=True,
                    source_path=source_for_checkin,
                )
            except Exception:
                if created_checkout:
                    try:
                        self._checkouts.undo_checkout(session, object_uuid)
                    except Exception:
                        logger.warning(
                            "Could not release checkout after failed revert check-in of %s",
                            object_uuid,
                            exc_info=True,
                        )
                raise
            finally:
                if temp_dir is not None:
                    shutil.rmtree(temp_dir, ignore_errors=True)
        self._activities.record(
            session,
            ActivityAction.VERSION_RESTORED,
            user,
            product_id=product.id,
            object_id=obj.id,
            details={
                "from_version": version_uuid,
                "from_display": display,
                "to_display": f"{restored.revision}.{restored.iteration}",
                "to_iteration": restored.iteration,
                "restored_path": dest_rel,
            },
        )
        self._refresh_where_used(session, product, restored)
        self._carry_metadata(session, target, restored.current_version)
        return restored

    def preview_queue(self, session: Session, product) -> dict[str, str | bool | list]:
        siblings = self._objects.list_objects(session, product.id)
        # A check-in decision: read the vault as it is now, not a status shared a moment ago.
        queue = self._workspaces.product_checkin_queue(product, siblings, fresh=True)
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
        product,
        comment: str,
        object_ids: list[str] | None = None,
        add_relative_paths: list[str] | None = None,
    ) -> dict[str, list]:
        message = (comment or "").strip()
        if not message:
            raise ValidationAppError("A check-in comment is required.")
        if product is not None:
            session.refresh(product)
        ensure_product_allows(product, "checkin", action="check in files")
        ok: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        for object_uuid in object_ids or []:
            filename = object_uuid
            try:
                # Savepoint: a failure after check-in mutates the row must not
                # stay in this session for the request-end commit.
                with session.begin_nested():
                    obj = self.checkin(session, object_uuid, message, None)
                    ok.append({"uuid": obj.uuid, "filename": obj.filename, "status": "checked_in"})
            except Exception as exc:
                if not isinstance(exc, CreoPDMError):
                    logger.exception("Check-in queue failed for %s", object_uuid)
                try:
                    filename = self._objects.get_object(session, object_uuid).filename
                except Exception:
                    pass
                failed.append(batch_failure(object_uuid, filename, exc))
        to_add = [item.replace("\\", "/").strip() for item in (add_relative_paths or []) if item.strip()]
        if to_add:
            try:
                with session.begin_nested():
                    created = self._add_workspace_files(session, product, to_add, message, "workspace")
                    by_path = {relative.replace("\\", "/").lower(): o for relative, o in created}
                    for relative in to_add:
                        # The uuid lets the page collect Creo metadata for what was just added.
                        obj = by_path.get(relative.replace("\\", "/").lower())
                        ok.append(
                            {
                                "uuid": obj.uuid if obj is not None else "",
                                "filename": obj.filename if obj is not None else Path(relative).name,
                                "status": "added",
                                "path": relative,
                                "relative_path": str(obj.relative_path or "") if obj is not None else relative,
                            }
                        )
            except Exception as exc:
                if not isinstance(exc, CreoPDMError):
                    logger.exception("Check-in queue failed while adding workspace files")
                failed.append(
                    batch_failure("", Path(to_add[0]).name if to_add else "", exc)
                )
        if not ok and not failed:
            raise ValidationAppError("There are no vault files to check in.")
        return {"ok": ok, "failed": failed}

    def _snapshot_repo_files(
        self, repo: Path, relative_paths: list[str], snapshot_dir: Path
    ) -> list[tuple[Path, bool, Path | None]]:
        """Copy vault paths check-in is about to overwrite into ``snapshot_dir``.

        Missing files are noted. Copies live on disk so a huge assembly is never held
        in memory.
        """
        snaps: list[tuple[Path, bool, Path | None]] = []
        root = repo.resolve()
        for index, rel in enumerate(relative_paths):
            path = (repo / rel.replace("\\", "/").lstrip("/")).resolve()
            if root != path and root not in path.parents:
                continue
            if path.is_file():
                saved = snapshot_dir / f"{index}.bin"
                shutil.copy2(path, saved)
                snaps.append((path, True, saved))
            else:
                snaps.append((path, False, None))
        return snaps

    def _restore_repo_snapshots(
        self,
        repo: Path,
        snaps: list[tuple[Path, bool, Path | None]],
        relative_paths: list[str],
    ) -> None:
        """Put only the paths this check-in touched back. Not a whole-repo reset."""
        try:
            self._store.abandon_staged_paths(repo, relative_paths)
        except Exception:
            logger.warning("Could not unstage check-in paths in %s", repo, exc_info=True)
        for path, existed, saved in snaps:
            try:
                if existed and saved is not None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if path.exists():
                        set_file_writable(path)
                    shutil.copyfile(saved, path)
                elif path.is_file():
                    set_file_writable(path)
                    path.unlink()
            except OSError:
                logger.warning("Could not restore vault file %s", path, exc_info=True)

    def _new_files_for(
        self,
        product,
        obj: EngineeringObject,
        siblings: list[EngineeringObject],
    ) -> list[dict[str, str | bool]]:
        folder = Path(self._workspaces.workspace_relative(obj)).parent.as_posix()
        if folder == ".":
            folder = ""
        found = []
        for item in self._workspaces.list_untracked(product, siblings):
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
        product,
        relative_paths: list[str],
        comment: str,
        source_label: str = "workspace",
    ) -> list[tuple[str, EngineeringObject]]:
        """Add new vault files as objects; returns (requested path, created object) pairs.

        The pairing matters: a Creo numbered save (``part.prt.2``) is stored under its logical name
        (``part.prt``), so the new object's own path cannot be matched back to what was asked for.
        """
        siblings = self._objects.list_objects(session, product.id)
        available = {
            str(item["relative_path"]).replace("\\", "/").lower(): item
            for item in self._workspaces.list_untracked(product, siblings)
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
            return []
        requested = {str(source): relative for source, _name, relative in jobs}
        created: list[tuple[str, EngineeringObject]] = []
        for outcome in self._objects.import_files(session, product, jobs, comment):
            if outcome.error is not None:
                raise outcome.error
            if outcome.obj is not None:
                created.append((requested.get(str(outcome.source)) or "", outcome.obj))
            logger.info("Added %s during check-in of %s", outcome.filename, source_label)
        return created

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
