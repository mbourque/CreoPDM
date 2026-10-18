"""Pessimistic checkout locks. The database is authoritative, not the filesystem."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from creopdm.constants import CheckoutStatus, LifecycleState, ActivityAction
from creopdm.exceptions import (
    CheckoutOwnershipError,
    CreoPDMError,
    ObjectAlreadyCheckedOutError,
    ObjectNotFoundError,
    ReleasedObjectError,
    ValidationAppError,
    batch_failure,
)
from creopdm.logging_setup import get_logger
from creopdm.models.checkout import Checkout
from creopdm.models.object import EngineeringObject
from creopdm.product_state import (
    ensure_product_allows,
    product_allows_mutation,
    product_state_label,
    product_state_value,
)
from creopdm.services.activity_service import ActivityService
from creopdm.services.lock_manager import ProductLockManager
from creopdm.services.object_service import ObjectService
from creopdm.services.workspace_service import WorkspaceService
from creopdm.utils.identity import CurrentUserProvider, UserIdentity
from creopdm.utils.timefmt import format_local

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
        locks: ProductLockManager,
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

    def list_for_product(self, session: Session, product_id: int) -> list[EngineeringObject]:
        """Active checkouts in this product, including files other people hold."""
        rows = session.scalars(
            select(EngineeringObject)
            .options(
                joinedload(EngineeringObject.current_version),
                joinedload(EngineeringObject.product),
            )
            .join(Checkout, Checkout.object_id == EngineeringObject.id)
            .where(
                EngineeringObject.product_id == product_id,
                Checkout.status == CheckoutStatus.ACTIVE.value,
            )
            .order_by(EngineeringObject.filename.asc())
        )
        return list(rows.unique())

    def count_for_product(
        self, session: Session, product_id: int, user_name: str | None = None
    ) -> int:
        """How many files currently have an active checkout in this product.

        With ``user_name`` only that user's checkouts count (what "Check in product…" can act on).
        """
        stmt = (
            select(func.count())
            .select_from(Checkout)
            .join(EngineeringObject, Checkout.object_id == EngineeringObject.id)
            .where(
                EngineeringObject.product_id == product_id,
                Checkout.status == CheckoutStatus.ACTIVE.value,
            )
        )
        if user_name:
            stmt = stmt.where(Checkout.user_name == user_name)
        return int(session.scalar(stmt) or 0)

    def count_checkoutable_for_product(self, session: Session, product_id: int) -> int:
        """IN_WORK files with no active checkout — available for Checkout product."""
        from creopdm.models.product import Product

        product = session.get(Product, product_id)
        if product is not None and not product_allows_mutation(product):
            return 0
        active = select(Checkout.object_id).where(Checkout.status == CheckoutStatus.ACTIVE.value)
        value = session.scalar(
            select(func.count())
            .select_from(EngineeringObject)
            .where(
                EngineeringObject.product_id == product_id,
                EngineeringObject.lifecycle_state == LifecycleState.IN_WORK.value,
                EngineeringObject.id.not_in(active),
            )
        )
        return int(value or 0)

    def checkoutable_ids_for_product(self, session: Session, product_id: int) -> list[str]:
        """UUIDs Checkout product would take: IN_WORK, no active checkout, product allows it."""
        from creopdm.models.product import Product

        product = session.get(Product, product_id)
        if product is not None and not product_allows_mutation(product):
            return []
        active = select(Checkout.object_id).where(Checkout.status == CheckoutStatus.ACTIVE.value)
        rows = session.scalars(
            select(EngineeringObject.uuid)
            .where(
                EngineeringObject.product_id == product_id,
                EngineeringObject.lifecycle_state == LifecycleState.IN_WORK.value,
                EngineeringObject.id.not_in(active),
            )
            .order_by(EngineeringObject.id)
        )
        return [str(item) for item in rows]

    def describe(
        self,
        obj: EngineeringObject,
        checkout: Checkout | None,
        user: UserIdentity | None = None,
    ) -> CheckoutView:
        current = user or self._users.get_current_user()
        product = obj.product
        mutable = product_allows_mutation(product) if product is not None else True
        released = obj.lifecycle_state != LifecycleState.IN_WORK.value
        if released:
            label = "Released" if obj.lifecycle_state == LifecycleState.RELEASED.value else "Obsolete"
            return CheckoutView(checkout, label, False, False, False)
        if checkout is None:
            if not mutable:
                # Do not say Available when checkout is blocked by product lock.
                label = product_state_label(product_state_value(product))
                return CheckoutView(None, label, False, False, False)
            return CheckoutView(None, "Available", False, True, False)
        owned = checkout.user_name == current.user_name
        label = "Checked out by me" if owned else f"Checked out by {checkout.user_name}"
        # Check-in blocked when lifecycle matrix blocks mutations; undo follows checkout op.
        return CheckoutView(checkout, label, owned, False, owned and mutable)

    def checkout(self, session: Session, object_uuid: str) -> Checkout:
        obj = self._objects.get_object(session, object_uuid)
        product = obj.product
        if product is not None:
            session.refresh(product)
        ensure_product_allows(product, "checkout", action="check out files")
        user = self._users.get_current_user()
        with self._locks.acquire(product.uuid):
            if obj.lifecycle_state != LifecycleState.IN_WORK.value:
                raise ReleasedObjectError(
                    f"{obj.filename} is {obj.lifecycle_state.replace('_', ' ').title()} and cannot be checked out."
                )
            existing = self.active_for(session, obj.id)
            if existing is not None:
                since = existing.checkout_time
                since_text = format_local(since) or "unknown"
                raise ObjectAlreadyCheckedOutError(
                    f"{obj.filename} is checked out by {existing.user_name}.",
                    details={
                        "user": existing.user_name,
                        "machine": existing.machine_name,
                        "since": since_text,
                    },
                )
            workspace_file = self._workspaces.materialize(
                product, obj, writable=True, keep_local=True
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
                product_id=product.id,
                object_id=obj.id,
                details={
                    "filename": obj.filename,
                    "object_uuid": obj.uuid,
                    "workspace": str(workspace_file),
                },
            )
            logger.info("Checked out %s by %s", obj.filename, user.user_name)
            return record

    def checkout_many(self, session: Session, object_uuids: list[str]) -> dict[str, list]:
        """Bulk checkout: one gate, one lock, one git status, one insert per product.

        Per-item results match the single-file path (``checked_out``,
        ``already_checked_out``, or a ``failed`` row with the same error text). A
        working copy is never overwritten: clean tips are only made writable, and
        locally modified tips are kept.
        """
        started = time.perf_counter()
        ok: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        user = self._users.get_current_user()
        ordered: list[str] = []
        seen: set[str] = set()
        for object_uuid in object_uuids:
            if not object_uuid or object_uuid in seen:
                continue
            seen.add(object_uuid)
            ordered.append(object_uuid)
        by_uuid = {obj.uuid: obj for obj in self._objects.get_objects(session, ordered)}
        groups: dict[int, list[EngineeringObject]] = {}
        for object_uuid in ordered:
            obj = by_uuid.get(object_uuid)
            if obj is None:
                missing = ObjectNotFoundError("Object not found.", details={"uuid": object_uuid})
                failed.append(batch_failure(object_uuid, object_uuid, missing))
                continue
            groups.setdefault(obj.product_id, []).append(obj)
        for group in groups.values():
            self._checkout_group(session, group, user, ok, failed)
        rank = {object_uuid: index for index, object_uuid in enumerate(ordered)}
        ok.sort(key=lambda row: rank.get(row["uuid"], 0))
        failed.sort(key=lambda row: rank.get(row["uuid"], 0))
        logger.info(
            "checkout_many: %s ok, %s failed in %.2fs (%s requested)",
            len(ok),
            len(failed),
            time.perf_counter() - started,
            len(ordered),
        )
        return {"ok": ok, "failed": failed}

    def _checkout_group(
        self,
        session: Session,
        group: list[EngineeringObject],
        user: UserIdentity,
        ok: list[dict[str, str]],
        failed: list[dict[str, str]],
    ) -> None:
        product = group[0].product
        if product is not None:
            session.refresh(product)
        try:
            ensure_product_allows(product, "checkout", action="check out files")
        except CreoPDMError as exc:
            for obj in group:
                failed.append(batch_failure(obj.uuid, obj.filename, exc))
            return
        with self._locks.acquire(product.uuid):
            active = self.active_map(session, [obj.id for obj in group])
            candidates: list[EngineeringObject] = []
            for obj in group:
                existing = active.get(obj.id)
                if existing is not None and existing.user_name == user.user_name:
                    ok.append({"uuid": obj.uuid, "filename": obj.filename, "status": "already_checked_out"})
                    continue
                if obj.lifecycle_state != LifecycleState.IN_WORK.value:
                    released = ReleasedObjectError(
                        f"{obj.filename} is {obj.lifecycle_state.replace('_', ' ').title()} and cannot be checked out."
                    )
                    failed.append(batch_failure(obj.uuid, obj.filename, released))
                    continue
                if existing is not None:
                    taken = ObjectAlreadyCheckedOutError(
                        f"{obj.filename} is checked out by {existing.user_name}.",
                        details={
                            "user": existing.user_name,
                            "machine": existing.machine_name,
                            "since": format_local(existing.checkout_time) or "unknown",
                        },
                    )
                    failed.append(batch_failure(obj.uuid, obj.filename, taken))
                    continue
                candidates.append(obj)
            if not candidates:
                return
            prepared: list[tuple[EngineeringObject, Path]] = []
            context = self._workspaces.checkout_workspace_context(product)
            for obj in candidates:
                try:
                    path = self._workspaces.checkout_workspace_path(product, obj, context)
                except Exception as exc:
                    if not isinstance(exc, CreoPDMError):
                        logger.exception("Checkout failed for %s", obj.uuid)
                    failed.append(batch_failure(obj.uuid, obj.filename, exc))
                    continue
                prepared.append((obj, path))
            self._insert_checkouts(session, product, user, prepared, ok, failed)

    def _new_checkout_row(
        self,
        obj: EngineeringObject,
        path: Path,
        user: UserIdentity,
        now: datetime,
    ) -> Checkout:
        return Checkout(
            object_id=obj.id,
            user_name=user.user_name,
            machine_name=user.machine_name,
            workspace_path=str(path),
            checkout_time=now,
            heartbeat_time=now,
            status=CheckoutStatus.ACTIVE.value,
        )

    def _record_checked_out(
        self,
        session: Session,
        product,
        user: UserIdentity,
        obj: EngineeringObject,
        path: Path,
    ) -> None:
        self._activities.record(
            session,
            ActivityAction.CHECKED_OUT,
            user,
            product_id=product.id,
            object_id=obj.id,
            details={
                "filename": obj.filename,
                "object_uuid": obj.uuid,
                "workspace": str(path),
            },
            product_uuid=product.uuid,
            product_name=product.name,
            object_uuid=obj.uuid,
            object_filename=obj.filename,
            flush=False,
        )

    def _insert_checkouts(
        self,
        session: Session,
        product,
        user: UserIdentity,
        prepared: list[tuple[EngineeringObject, Path]],
        ok: list[dict[str, str]],
        failed: list[dict[str, str]],
    ) -> None:
        """Insert every row in one flush; on any error retry per item with savepoints."""
        if not prepared:
            return
        now = datetime.now(timezone.utc)
        try:
            with session.begin_nested():
                for obj, path in prepared:
                    session.add(self._new_checkout_row(obj, path, user, now))
                    self._record_checked_out(session, product, user, obj, path)
                session.flush()
        except Exception:
            logger.warning(
                "Bulk checkout insert failed for %s; retrying one file at a time",
                product.uuid,
                exc_info=True,
            )
        else:
            for obj, _path in prepared:
                ok.append({"uuid": obj.uuid, "filename": obj.filename, "status": "checked_out"})
            return
        for obj, path in prepared:
            try:
                with session.begin_nested():
                    session.add(self._new_checkout_row(obj, path, user, now))
                    self._record_checked_out(session, product, user, obj, path)
                    session.flush()
            except Exception as exc:
                if isinstance(exc, IntegrityError):
                    exc = ObjectAlreadyCheckedOutError(
                        f"{obj.filename} was checked out by someone else."
                    )
                elif not isinstance(exc, CreoPDMError):
                    logger.exception("Checkout failed for %s", obj.uuid)
                failed.append(batch_failure(obj.uuid, obj.filename, exc))
                continue
            ok.append({"uuid": obj.uuid, "filename": obj.filename, "status": "checked_out"})

    def undo_checkout(self, session: Session, object_uuid: str) -> None:
        obj = self._objects.get_object(session, object_uuid)
        product = obj.product
        if product is not None:
            session.refresh(product)
        ensure_product_allows(product, "checkout", action="undo checkout")
        user = self._users.get_current_user()
        with self._locks.acquire(product.uuid):
            record = self.require_owned(session, obj, user)
            workspace_file = self._workspaces.materialize(
                product,
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
                product_id=product.id,
                object_id=obj.id,
                details={
                    "filename": obj.filename,
                    "object_uuid": obj.uuid,
                    "workspace": str(workspace_file),
                },
            )
            logger.info("Cancelled checkout of %s", obj.filename)

    def discard_changes(self, session: Session, object_uuid: str) -> EngineeringObject:
        """Throw away unsaved vault changes of a file nobody has checked out.

        Undo Checkout keeps a save on purpose (it can still be checked in); this is the explicit
        way to drop it, back to the checked-in version. A held checkout must be undone first.
        """
        obj = self._objects.get_object(session, object_uuid)
        product = obj.product
        if product is not None:
            session.refresh(product)
        ensure_product_allows(product, "checkout", action="discard changes")
        user = self._users.get_current_user()
        with self._locks.acquire(product.uuid):
            existing = self.active_for(session, obj.id)
            if existing is not None:
                raise ObjectAlreadyCheckedOutError(
                    f"{obj.filename} is checked out by {existing.user_name}. "
                    "Undo the checkout first, then discard the changes.",
                    details={"user": existing.user_name},
                )
            if not self._workspaces.discard_vault_saves(product, obj):
                raise ValidationAppError(
                    f"{obj.filename} has no unsaved changes in the vault to discard. "
                    "If it still reads Modified, the changed copy is in your local workspace on this PC.",
                    details={"filename": obj.filename},
                )
            self._activities.record(
                session,
                ActivityAction.CHANGES_DISCARDED,
                user,
                product_id=product.id,
                object_id=obj.id,
                details={"filename": obj.filename, "object_uuid": obj.uuid},
            )
            logger.info("Discarded vault changes of %s", obj.filename)
        return obj

    def force_undo_checkout(self, session: Session, object_uuid: str) -> str:
        """Release any user's checkout without committing a new version.

        Returns the previous checkout ``user_name`` (login username).
        """
        obj = self._objects.get_object(session, object_uuid)
        product = obj.product
        if product is not None:
            session.refresh(product)
        ensure_product_allows(product, "checkout", action="force undo checkout")
        user = self._users.get_current_user()
        with self._locks.acquire(product.uuid):
            record = self.active_for(session, obj.id)
            if record is None:
                raise CheckoutOwnershipError(f"{obj.filename} is not checked out.")
            previous_user = record.user_name
            previous_machine = record.machine_name
            workspace_file = self._workspaces.materialize(
                product,
                obj,
                writable=False,
                overwrite_modified=True,
            )
            record.status = CheckoutStatus.CANCELLED.value
            session.flush()
            self._activities.record(
                session,
                ActivityAction.CHECKOUT_OVERRIDE,
                user,
                product_id=product.id,
                object_id=obj.id,
                details={
                    "filename": obj.filename,
                    "object_uuid": obj.uuid,
                    "workspace": str(workspace_file),
                    "previous_user": previous_user,
                    "previous_machine": previous_machine,
                },
            )
            logger.info(
                "Force-cancelled checkout of %s (was %s)",
                obj.filename,
                previous_user,
            )
            return previous_user

    def undo_checkout_many(self, session: Session, object_uuids: list[str]) -> dict[str, list]:
        """Bulk Undo Checkout: one gate, one lock, one flush per product."""
        return self._release_many(session, object_uuids, force=False)

    def force_undo_checkout_many(self, session: Session, object_uuids: list[str]) -> dict[str, list]:
        """Bulk Force Undo Checkout (any user's lock); same bulk path as Undo."""
        return self._release_many(session, object_uuids, force=True)

    def _release_many(
        self,
        session: Session,
        object_uuids: list[str],
        *,
        force: bool,
    ) -> dict[str, list]:
        """Release checkouts in bulk. Results match the single-file Undo / Force Undo.

        Undo never restores bytes (a newer Creo save stays for check-in), so a tip that is
        the vault file is only made read-only: no hashing, no copy, no directory scan.
        """
        started = time.perf_counter()
        ok: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        user = self._users.get_current_user()
        ordered: list[str] = []
        seen: set[str] = set()
        for object_uuid in object_uuids:
            if not object_uuid or object_uuid in seen:
                continue
            seen.add(object_uuid)
            ordered.append(object_uuid)
        by_uuid = {obj.uuid: obj for obj in self._objects.get_objects(session, ordered)}
        groups: dict[int, list[EngineeringObject]] = {}
        for object_uuid in ordered:
            obj = by_uuid.get(object_uuid)
            if obj is None:
                missing = ObjectNotFoundError("Object not found.", details={"uuid": object_uuid})
                failed.append(batch_failure(object_uuid, object_uuid, missing))
                continue
            groups.setdefault(obj.product_id, []).append(obj)
        for group in groups.values():
            self._release_group(session, group, user, ok, failed, force=force)
        rank = {object_uuid: index for index, object_uuid in enumerate(ordered)}
        ok.sort(key=lambda row: rank.get(row["uuid"], 0))
        failed.sort(key=lambda row: rank.get(row["uuid"], 0))
        logger.info(
            "%s: %s ok, %s failed in %.2fs (%s requested)",
            "force_undo_checkout_many" if force else "undo_checkout_many",
            len(ok),
            len(failed),
            time.perf_counter() - started,
            len(ordered),
        )
        return {"ok": ok, "failed": failed}

    def _release_group(
        self,
        session: Session,
        group: list[EngineeringObject],
        user: UserIdentity,
        ok: list[dict[str, str]],
        failed: list[dict[str, str]],
        *,
        force: bool,
    ) -> None:
        product = group[0].product
        if product is not None:
            session.refresh(product)
        gate_error: CreoPDMError | None = None
        try:
            ensure_product_allows(
                product,
                "checkout",
                action="force undo checkout" if force else "undo checkout",
            )
        except CreoPDMError as exc:
            # Only files that need releasing fail on the gate; "already available" and
            # "not yours" keep the same answer they had before.
            gate_error = exc
        with self._locks.acquire(product.uuid):
            active = self.active_map(session, [obj.id for obj in group])
            releasing: list[tuple[EngineeringObject, Checkout]] = []
            for obj in group:
                existing = active.get(obj.id)
                if existing is None:
                    ok.append({"uuid": obj.uuid, "filename": obj.filename, "status": "already_available"})
                    continue
                if not force and existing.user_name != user.user_name:
                    other = CheckoutOwnershipError(
                        f"{obj.filename} is checked out by {existing.user_name}.",
                        details={"user": existing.user_name, "machine": existing.machine_name},
                    )
                    failed.append(batch_failure(obj.uuid, obj.filename, other))
                    continue
                if gate_error is not None:
                    failed.append(batch_failure(obj.uuid, obj.filename, gate_error))
                    continue
                releasing.append((obj, existing))
            if not releasing:
                return
            prepared: list[tuple[EngineeringObject, Checkout, Path]] = []
            for obj, record in releasing:
                try:
                    path = self._workspaces.release_workspace_path(product, obj)
                except Exception as exc:
                    if not isinstance(exc, CreoPDMError):
                        logger.exception("Undo checkout failed for %s", obj.uuid)
                    failed.append(batch_failure(obj.uuid, obj.filename, exc))
                    continue
                prepared.append((obj, record, path))
            self._apply_release(session, product, user, prepared, ok, failed, force=force)

    def _release_one(
        self,
        session: Session,
        product,
        user: UserIdentity,
        obj: EngineeringObject,
        record: Checkout,
        path: Path,
        *,
        force: bool,
    ) -> dict[str, str]:
        previous_user = record.user_name
        previous_machine = record.machine_name
        record.status = CheckoutStatus.CANCELLED.value
        details: dict[str, object] = {
            "filename": obj.filename,
            "object_uuid": obj.uuid,
            "workspace": str(path),
        }
        if force:
            details["previous_user"] = previous_user
            details["previous_machine"] = previous_machine
        self._activities.record(
            session,
            ActivityAction.CHECKOUT_OVERRIDE if force else ActivityAction.CHECKOUT_CANCELLED,
            user,
            product_id=product.id,
            object_id=obj.id,
            details=details,
            product_uuid=product.uuid,
            product_name=product.name,
            object_uuid=obj.uuid,
            object_filename=obj.filename,
            flush=False,
        )
        if force:
            return {
                "uuid": obj.uuid,
                "filename": obj.filename,
                "status": "force_cancelled",
                "previous_user": previous_user,
            }
        return {"uuid": obj.uuid, "filename": obj.filename, "status": "cancelled"}

    def _apply_release(
        self,
        session: Session,
        product,
        user: UserIdentity,
        prepared: list[tuple[EngineeringObject, Checkout, Path]],
        ok: list[dict[str, str]],
        failed: list[dict[str, str]],
        *,
        force: bool,
    ) -> None:
        """Flip every row in one flush; on any error retry per item with savepoints."""
        if not prepared:
            return
        rows: list[dict[str, str]] = []
        try:
            with session.begin_nested():
                for obj, record, path in prepared:
                    rows.append(
                        self._release_one(session, product, user, obj, record, path, force=force)
                    )
                session.flush()
        except Exception:
            logger.warning(
                "Bulk release failed for %s; retrying one file at a time",
                product.uuid,
                exc_info=True,
            )
        else:
            ok.extend(rows)
            return
        for obj, record, path in prepared:
            try:
                with session.begin_nested():
                    row = self._release_one(session, product, user, obj, record, path, force=force)
                    session.flush()
            except Exception as exc:
                if not isinstance(exc, CreoPDMError):
                    logger.exception("Undo checkout failed for %s", obj.uuid)
                failed.append(batch_failure(obj.uuid, obj.filename, exc))
                continue
            ok.append(row)

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

    def heartbeat_mine(self, session: Session) -> None:
        """Touch every active checkout owned by the current user in one write."""
        user = self._users.get_current_user()
        session.execute(
            update(Checkout)
            .where(
                Checkout.status == CheckoutStatus.ACTIVE.value,
                Checkout.user_name == user.user_name,
            )
            .values(heartbeat_time=datetime.now(timezone.utc))
        )
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
