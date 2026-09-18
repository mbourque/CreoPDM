"""Pessimistic checkout locks. The database is authoritative, not the filesystem."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from creopdm.constants import CheckoutStatus, LifecycleState, ActivityAction
from creopdm.exceptions import (
    CheckoutOwnershipError,
    CreoPDMError,
    ObjectAlreadyCheckedOutError,
    ReleasedObjectError,
)
from creopdm.logging_setup import get_logger
from creopdm.models.checkout import Checkout
from creopdm.models.object import EngineeringObject
from creopdm.services.activity_service import ActivityService
from creopdm.services.lock_manager import ProjectLockManager
from creopdm.services.object_service import ObjectService
from creopdm.services.workspace_service import WorkspaceService
from creopdm.utils.identity import CurrentUserProvider, UserIdentity

logger = get_logger("checkout")


@dataclass(frozen=True, slots=True)
class CheckoutView:
    checkout: Checkout | None
    label: str
    owned_by_me: bool
    can_checkout: bool
    can_checkin: bool


class CheckoutService:
    def __init__(
        self,
        objects: ObjectService,
        workspaces: WorkspaceService,
        locks: ProjectLockManager,
        activities: ActivityService,
        users: CurrentUserProvider,
    ) -> None:
        self._objects = objects
        self._workspaces = workspaces
        self._locks = locks
        self._activities = activities
        self._users = users

    def active_for(self, session: Session, object_id: int) -> Checkout | None:
        return session.scalar(
            select(Checkout).where(
                Checkout.object_id == object_id,
                Checkout.status == CheckoutStatus.ACTIVE.value,
            )
        )

    def active_map(self, session: Session, object_ids: list[int]) -> dict[int, Checkout]:
        if not object_ids:
            return {}
        rows = session.scalars(
            select(Checkout).where(
                Checkout.object_id.in_(object_ids),
                Checkout.status == CheckoutStatus.ACTIVE.value,
            )
        )
        return {row.object_id: row for row in rows}

    def list_for_project(self, session: Session, project_id: int) -> list[EngineeringObject]:
        """Active checkouts in this project, including files other people hold."""
        rows = session.scalars(
            select(EngineeringObject)
            .options(
                joinedload(EngineeringObject.current_version),
                joinedload(EngineeringObject.project),
            )
            .join(Checkout, Checkout.object_id == EngineeringObject.id)
            .where(
                EngineeringObject.project_id == project_id,
                Checkout.status == CheckoutStatus.ACTIVE.value,
            )
            .order_by(EngineeringObject.filename.asc())
        )
        return list(rows.unique())

    def count_for_project(self, session: Session, project_id: int) -> int:
        """How many files currently have an active checkout in this project."""
        value = session.scalar(
            select(func.count())
            .select_from(Checkout)
            .join(EngineeringObject, Checkout.object_id == EngineeringObject.id)
            .where(
                EngineeringObject.project_id == project_id,
                Checkout.status == CheckoutStatus.ACTIVE.value,
            )
        )
        return int(value or 0)

    def describe(
        self,
        obj: EngineeringObject,
        checkout: Checkout | None,
        user: UserIdentity | None = None,
    ) -> CheckoutView:
        current = user or self._users.get_current_user()
        released = obj.lifecycle_state != LifecycleState.IN_WORK.value
        if released:
            label = "Released" if obj.lifecycle_state == LifecycleState.RELEASED.value else "Obsolete"
            return CheckoutView(checkout, label, False, False, False)
        if checkout is None:
            return CheckoutView(None, "Available", False, True, False)
        owned = checkout.user_name == current.user_name
        label = "Checked out by me" if owned else f"Checked out by {checkout.user_name}"
        return CheckoutView(checkout, label, owned, False, owned)

    def checkout(self, session: Session, object_uuid: str) -> Checkout:
        obj = self._objects.get_object(session, object_uuid)
        project = obj.project
        user = self._users.get_current_user()
        with self._locks.acquire(project.uuid):
            if obj.lifecycle_state != LifecycleState.IN_WORK.value:
                raise ReleasedObjectError(
                    f"{obj.filename} is {obj.lifecycle_state.replace('_', ' ').title()} and cannot be checked out."
                )
            existing = self.active_for(session, obj.id)
            if existing is not None:
                since = existing.checkout_time
                since_text = since.strftime("%Y-%m-%d %H:%M") if since else "unknown"
                raise ObjectAlreadyCheckedOutError(
                    f"{obj.filename} is checked out by {existing.user_name}.",
                    details={
                        "user": existing.user_name,
                        "machine": existing.machine_name,
                        "since": since_text,
                    },
                )
            workspace_file = self._workspaces.materialize(
                project, obj, writable=True, keep_local=True
            )
            now = datetime.now(timezone.utc)
            record = Checkout(
                object_id=obj.id,
                user_name=user.user_name,
                machine_name=user.machine_name,
                workspace_path=str(workspace_file),
                checkout_time=now,
                heartbeat_time=now,
                status=CheckoutStatus.ACTIVE.value,
            )
            session.add(record)
            session.flush()
            self._activities.record(
                session,
                ActivityAction.CHECKED_OUT,
                user,
                project_id=project.id,
                object_id=obj.id,
                details={"workspace": str(workspace_file)},
            )
            logger.info("Checked out %s by %s", obj.filename, user.user_name)
            return record

    def checkout_many(self, session: Session, object_uuids: list[str]) -> dict[str, list]:
        ok: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        user = self._users.get_current_user()
        seen: set[str] = set()
        for object_uuid in object_uuids:
            if not object_uuid or object_uuid in seen:
                continue
            seen.add(object_uuid)
            filename = object_uuid
            try:
                obj = self._objects.get_object(session, object_uuid)
                filename = obj.filename
                existing = self.active_for(session, obj.id)
                if existing is not None and existing.user_name == user.user_name:
                    ok.append({"uuid": object_uuid, "filename": filename, "status": "already_checked_out"})
                    continue
                self.checkout(session, object_uuid)
                ok.append({"uuid": object_uuid, "filename": filename, "status": "checked_out"})
            except CreoPDMError as exc:
                failed.append(
                    {
                        "uuid": object_uuid,
                        "filename": filename,
                        "code": exc.code,
                        "message": exc.message,
                    }
                )
        return {"ok": ok, "failed": failed}

    def undo_checkout(self, session: Session, object_uuid: str) -> None:
        obj = self._objects.get_object(session, object_uuid)
        project = obj.project
        user = self._users.get_current_user()
        with self._locks.acquire(project.uuid):
            record = self.require_owned(session, obj, user)
            workspace_file = self._workspaces.materialize(
                project,
                obj,
                writable=False,
                overwrite_modified=True,
            )
            record.status = CheckoutStatus.CANCELLED.value
            session.flush()
            self._activities.record(
                session,
                ActivityAction.CHECKOUT_CANCELLED,
                user,
                project_id=project.id,
                object_id=obj.id,
                details={"workspace": str(workspace_file)},
            )
            logger.info("Cancelled checkout of %s", obj.filename)

    def undo_checkout_many(self, session: Session, object_uuids: list[str]) -> dict[str, list]:
        ok: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        user = self._users.get_current_user()
        seen: set[str] = set()
        for object_uuid in object_uuids:
            if not object_uuid or object_uuid in seen:
                continue
            seen.add(object_uuid)
            filename = object_uuid
            try:
                obj = self._objects.get_object(session, object_uuid)
                filename = obj.filename
                existing = self.active_for(session, obj.id)
                if existing is None:
                    ok.append({"uuid": object_uuid, "filename": filename, "status": "already_available"})
                    continue
                if existing.user_name != user.user_name:
                    raise CheckoutOwnershipError(
                        f"{obj.filename} is checked out by {existing.user_name}.",
                        details={"user": existing.user_name, "machine": existing.machine_name},
                    )
                self.undo_checkout(session, object_uuid)
                ok.append({"uuid": object_uuid, "filename": filename, "status": "cancelled"})
            except CreoPDMError as exc:
                failed.append(
                    {
                        "uuid": object_uuid,
                        "filename": filename,
                        "code": exc.code,
                        "message": exc.message,
                    }
                )
            except Exception as exc:
                failed.append(
                    {
                        "uuid": object_uuid,
                        "filename": filename,
                        "code": "APPLICATION_ERROR",
                        "message": str(exc),
                    }
                )
        return {"ok": ok, "failed": failed}

    def release_mine(self, session: Session, obj: EngineeringObject) -> None:
        """Drop my active checkout without restoring workspace files."""
        user = self._users.get_current_user()
        record = self.active_for(session, obj.id)
        if record is None:
            return
        if record.user_name != user.user_name:
            raise CheckoutOwnershipError(
                f"{obj.filename} is checked out by {record.user_name}.",
                details={"user": record.user_name, "machine": record.machine_name},
            )
        record.status = CheckoutStatus.CANCELLED.value
        session.flush()

    def release_mine_many(self, session: Session, objects: list[EngineeringObject]) -> None:
        """Drop my active checkouts on these objects without restoring files."""
        ids = [obj.id for obj in objects]
        if not ids:
            return
        user = self._users.get_current_user()
        for start in range(0, len(ids), 400):
            chunk = ids[start : start + 400]
            session.execute(
                update(Checkout)
                .where(
                    Checkout.object_id.in_(chunk),
                    Checkout.status == CheckoutStatus.ACTIVE.value,
                    Checkout.user_name == user.user_name,
                )
                .values(status=CheckoutStatus.CANCELLED.value)
            )
        session.flush()

    def heartbeat(self, session: Session, object_uuid: str) -> None:
        obj = self._objects.get_object(session, object_uuid)
        user = self._users.get_current_user()
        record = self.require_owned(session, obj, user)
        record.heartbeat_time = datetime.now(timezone.utc)
        session.flush()

    def require_owned(
        self,
        session: Session,
        obj: EngineeringObject,
        user: UserIdentity,
    ) -> Checkout:
        record = self.active_for(session, obj.id)
        if record is None:
            raise CheckoutOwnershipError(f"{obj.filename} is not checked out.")
        if record.user_name != user.user_name:
            raise CheckoutOwnershipError(
                f"{obj.filename} is checked out by {record.user_name}.",
                details={"user": record.user_name, "machine": record.machine_name},
            )
        return record
