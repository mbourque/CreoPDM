"""Revise eligibility: may this file get a new revision (A.3 RELEASED → B.1)?

One rule set for the UI flags and the server check, so the Files list, the Details page and
the API can never disagree. Creating the revision itself is a later step.
"""

from __future__ import annotations

import uuid as uuidlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from creopdm.constants import INITIAL_ITERATION, ActivityAction, LifecycleState
from creopdm.exceptions import (
    RepositoryError,
    ReviseActiveCheckoutError,
    ReviseInvalidLifecycleError,
    ReviseNextRevisionExistsError,
    ReviseNotAllowedError,
    ReviseOperationAlreadyCompletedError,
    ReviseRevisionSchemeError,
    ReviseSourceNotFoundError,
    ValidationAppError,
)
from creopdm.logging_setup import get_logger
from creopdm.models.ai_snapshot import ObjectVersionSnapshot
from creopdm.models.checkout import Checkout
from creopdm.models.object import EngineeringObject
from creopdm.models.parameter import Parameter
from creopdm.models.revise_operation import ReviseOperation
from creopdm.models.version import ObjectVersion
from creopdm.product_state import (
    product_allows_op,
    product_is_archived,
    product_state_label,
    product_state_value,
)
from creopdm.services.activity_service import ActivityService
from creopdm.services.checkout_service import CheckoutService
from creopdm.services.lock_manager import ProductLockManager
from creopdm.services.object_service import ObjectService
from creopdm.services.workspace_service import WorkspaceService
from creopdm.storage.base import VersionStore
from creopdm.utils.identity import CurrentUserProvider

logger = get_logger("revise")

# Server policy: a revision always carries a reason (a later setting can relax this).
REVISE_REASON_REQUIRED = True
REVISE_REASON_MAX_LENGTH = 500


@dataclass(frozen=True)
class ReviseEligibility:
    allowed: bool
    code: str = ""
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def evaluate_revise(
    obj: EngineeringObject,
    checkout: Checkout | None,
    *,
    check_product: bool = True,
) -> ReviseEligibility:
    """Object-level rules, in the order a user would hit them.

    ``check_product`` is False for list flags, where the product matrix is applied separately
    (``product_ui.show_revise``); the API always checks it.
    """
    # Only touch obj.product when asked: list flags run per row and must not lazy-load it.
    product = obj.product if check_product else None
    if product is not None:
        if product_is_archived(product):
            return ReviseEligibility(
                False,
                ReviseNotAllowedError.code,
                f"{product.name} is archived and cannot create a new revision.",
                {"product": product.uuid, "state": product_state_value(product)},
            )
        if not product_allows_op(product, "revise"):
            state = product_state_label(product_state_value(product))
            return ReviseEligibility(
                False,
                ReviseNotAllowedError.code,
                f"Product is {state} and cannot create a new revision.",
                {"product": product.uuid, "state": product_state_value(product), "op": "revise"},
            )
    if checkout is not None:
        return ReviseEligibility(
            False,
            ReviseActiveCheckoutError.code,
            f"Cannot revise {obj.filename}: it is checked out by {checkout.user_name}. "
            "Resolve the checkout before creating a new revision.",
            {"checked_out_by": checkout.user_name},
        )
    if obj.lifecycle_state != LifecycleState.RELEASED.value:
        state = (obj.lifecycle_state or "").replace("_", " ").title()
        return ReviseEligibility(
            False,
            ReviseInvalidLifecycleError.code,
            f"{obj.filename} is {state} — only a Released file can be revised.",
            {"lifecycle_state": obj.lifecycle_state},
        )
    return ReviseEligibility(True)


@dataclass(frozen=True)
class RevisePreview:
    """Eligibility plus the new version the server would create (nothing is created)."""

    eligibility: ReviseEligibility
    source_version_id: str
    source_revision: str
    source_iteration: int
    new_revision: str = ""
    new_iteration: int = INITIAL_ITERATION
    new_lifecycle_state: str = LifecycleState.IN_WORK.value


def next_revision_for(db: Session, obj: EngineeringObject) -> str:
    """Next revision after the object's current one, refusing to reuse an existing revision.

    History stays linear (A → B → C): the next revision must not already exist on any
    version of this object. Raises a REVISE_* error the preview turns into a message.
    """
    from creopdm.utils.revision_scheme import get_next_revision

    current = obj.revision
    nxt = get_next_revision(current)
    used = set(
        db.scalars(select(ObjectVersion.revision).where(ObjectVersion.object_id == obj.id))
    )
    if nxt in used:
        raise ReviseNextRevisionExistsError(
            f"{obj.filename} already has a revision {nxt}.",
            details={"revision": nxt},
        )
    return nxt


def preview_revise(
    db: Session, obj: EngineeringObject, checkout: Checkout | None
) -> RevisePreview:
    """Server-calculated preview. The source is always the object's exact current version."""
    source = obj.current_version
    source_id = source.uuid if source is not None else ""
    base = {
        "source_version_id": source_id,
        "source_revision": obj.revision,
        "source_iteration": obj.iteration,
    }
    eligibility = evaluate_revise(obj, checkout)
    if not eligibility.allowed:
        return RevisePreview(eligibility=eligibility, **base)
    if source is None:
        error = ReviseSourceNotFoundError(f"{obj.filename} has no version to revise from.")
        return RevisePreview(
            eligibility=ReviseEligibility(False, error.code, error.message), **base
        )
    try:
        new_revision = next_revision_for(db, obj)
    except (ReviseNextRevisionExistsError, ReviseRevisionSchemeError) as exc:
        return RevisePreview(
            eligibility=ReviseEligibility(False, exc.code, exc.message, exc.details), **base
        )
    return RevisePreview(eligibility=eligibility, new_revision=new_revision, **base)


def object_can_revise(obj: EngineeringObject, checkout: Checkout | None) -> bool:
    """Flag for ObjectResponse.can_revise (permission and product matrix are separate)."""
    return evaluate_revise(obj, checkout, check_product=False).allowed


def raise_for(result: ReviseEligibility) -> None:
    """Raise the REVISE_* error that matches a refused eligibility result."""
    if result.allowed:
        return
    error = {
        ReviseActiveCheckoutError.code: ReviseActiveCheckoutError,
        ReviseInvalidLifecycleError.code: ReviseInvalidLifecycleError,
        ReviseNextRevisionExistsError.code: ReviseNextRevisionExistsError,
        ReviseRevisionSchemeError.code: ReviseRevisionSchemeError,
        ReviseSourceNotFoundError.code: ReviseSourceNotFoundError,
    }.get(result.code, ReviseNotAllowedError)
    raise error(result.message, result.details)


def ensure_can_revise(obj: EngineeringObject, checkout: Checkout | None) -> None:
    """Raise the matching REVISE_* error when Revise is not allowed."""
    raise_for(evaluate_revise(obj, checkout))


def clean_reason(reason: str | None) -> str:
    """Validate the revision reason against the server policy."""
    text = " ".join((reason or "").split())
    if REVISE_REASON_REQUIRED and not text:
        raise ValidationAppError("A revision reason is required.")
    if len(text) > REVISE_REASON_MAX_LENGTH:
        raise ValidationAppError(
            f"The revision reason is too long (max {REVISE_REASON_MAX_LENGTH} characters)."
        )
    return text


@dataclass(frozen=True)
class RevisedVersion:
    obj: EngineeringObject
    source: ObjectVersion
    version: ObjectVersion
    # True when this is the stored result of an earlier request with the same operation id.
    replayed: bool = False


class ReviseService:
    """Create the next revision (A.3 RELEASED -> B.1 IN_WORK) of the same object."""

    def __init__(
        self,
        objects: ObjectService,
        checkouts: CheckoutService,
        workspaces: WorkspaceService,
        store: VersionStore,
        locks: ProductLockManager,
        activities: ActivityService,
        users: CurrentUserProvider,
    ) -> None:
        self._objects = objects
        self._checkouts = checkouts
        self._workspaces = workspaces
        self._store = store
        self._locks = locks
        self._activities = activities
        self._users = users

    def revise(
        self,
        session: Session,
        object_uuid: str,
        reason: str | None,
        operation_id: str | None = None,
    ) -> RevisedVersion:
        """All-or-nothing: either B.1 exists and is current, or A.x is untouched.

        The server picks the revision. The client sends only the reason and, for retry safety,
        an operation id: the same id always returns the same B.1 and never allocates C.1.
        """
        op_id = (operation_id or "").strip() or None
        obj = self._objects.get_object(session, object_uuid)
        product = obj.product
        if product is not None:
            session.refresh(product)
        # A retry after a lost response: answer from the stored result before anything else
        # (B.1 is In Work now, so the normal Released-only check would refuse it).
        if op_id is not None:
            replay = self._replay(session, obj, op_id)
            if replay is not None:
                return replay
        note = clean_reason(reason)
        # Cheap refusal before taking the lock; the real check repeats inside it.
        early = preview_revise(session, obj, self._checkouts.active_for(session, obj.id))
        raise_for(early.eligibility)
        user = self._users.get_current_user()
        self._workspaces.ensure_vault(product)
        repo = self._workspaces.vault_for(product)

        with self._locks.acquire(product.uuid):
            # Lock the object row (Postgres) and re-read: state may have changed while waiting.
            session.execute(
                select(EngineeringObject.id)
                .where(EngineeringObject.id == obj.id)
                .with_for_update()
            )
            session.refresh(obj)
            session.refresh(product)
            # Same operation id from a concurrent request that finished while we waited.
            if op_id is not None:
                replay = self._replay(session, obj, op_id)
                if replay is not None:
                    return replay
            preview = preview_revise(session, obj, self._checkouts.active_for(session, obj.id))
            raise_for(preview.eligibility)
            source = obj.current_version
            if source is None:
                raise ReviseSourceNotFoundError(f"{obj.filename} has no version to revise from.")
            new_revision = preview.new_revision
            old_display = f"{source.revision}.{source.iteration}"
            new_display = f"{new_revision}.{INITIAL_ITERATION}"

            checkpoint = self._store.capture_checkpoint(repo)
            message = (
                "CreoPDM Revise\n\n"
                f"Object: {obj.filename}\n"
                f"Object UUID: {obj.uuid}\n"
                f"From: {old_display}\n"
                f"To: {new_display}\n"
                "Operation: REVISE\n"
                f"Reason: {note}"
            )
            # Content is unchanged: an empty commit gives B.1 its own repository state while
            # A.x's commit and blob stay exactly as they were. Informational message only.
            try:
                git_hash = self._store.store_version(repo, [], message, user, allow_empty=True)
            except Exception as exc:
                logger.exception("Git store failed during revise of %s", obj.filename)
                self._rollback_git(repo, checkpoint)
                raise RepositoryError(
                    "The new revision could not be stored in the vault, so nothing was changed.",
                    details={"file": obj.filename},
                ) from exc
            now = datetime.now(timezone.utc)
            try:
                if source.lifecycle_state != LifecycleState.RELEASED.value:
                    # Make the source's own state explicit before the object row moves on.
                    source.lifecycle_state = LifecycleState.RELEASED.value
                version = ObjectVersion(
                    uuid=str(uuidlib.uuid4()),
                    object_id=obj.id,
                    revision=new_revision,
                    iteration=INITIAL_ITERATION,
                    filename=source.filename,
                    relative_path=source.relative_path,
                    creo_release=source.creo_release,
                    identity_json=source.identity_json,
                    materials_json=source.materials_json,
                    bom_json=source.bom_json,
                    units_json=source.units_json,
                    mass_json=source.mass_json,
                    family_table_json=source.family_table_json,
                    features_json=source.features_json,
                    git_commit_hash=git_hash or source.git_commit_hash,
                    content_hash=source.content_hash,
                    file_size=source.file_size,
                    created_by=user.user_name,
                    created_at=now,
                    comment=f"Revision {new_revision} created from {old_display}: {note}",
                    lifecycle_state=LifecycleState.IN_WORK.value,
                    created_from_version_id=source.id,
                    revision_reason=note,
                )
                session.add(version)
                session.flush()
                self._copy_metadata(session, obj, source, version)
                obj.revision = new_revision
                obj.iteration = INITIAL_ITERATION
                obj.lifecycle_state = LifecycleState.IN_WORK.value
                obj.current_version_id = version.id
                obj.updated_at = now
                session.flush()
                if op_id is not None:
                    session.add(
                        ReviseOperation(
                            operation_id=op_id,
                            object_id=obj.id,
                            source_version_id=source.id,
                            new_version_id=version.id,
                            user_name=user.user_name,
                            status="COMPLETED",
                        )
                    )
                    session.flush()
                self._activities.record(
                    session,
                    ActivityAction.REVISION_CREATED,
                    user,
                    product_id=product.id,
                    object_id=obj.id,
                    details={
                        "filename": obj.filename,
                        "object_uuid": obj.uuid,
                        "source_version": old_display,
                        "source_version_id": source.uuid,
                        "new_version": new_display,
                        "new_version_id": version.uuid,
                        "from_revision": source.revision,
                        "from_iteration": source.iteration,
                        "to_revision": new_revision,
                        "to_iteration": INITIAL_ITERATION,
                        "reason": note,
                        "git_commit": (git_hash or "")[:40] or None,
                    },
                    comment=note,
                )
            except IntegrityError as exc:
                self._rollback_git(repo, checkpoint)
                session.rollback()
                if op_id is not None:
                    # The same operation id won a race: hand back its result, not an error.
                    replay = self._replay(session, obj, op_id)
                    if replay is not None:
                        return replay
                raise ReviseNextRevisionExistsError(
                    f"{obj.filename} already has a revision {new_revision}.",
                    details={"revision": new_revision},
                ) from exc
            except Exception as exc:
                logger.exception("Revise failed after storing the Git state for %s", obj.filename)
                self._rollback_git(repo, checkpoint)
                raise RepositoryError(
                    "The revision could not be saved, so nothing was changed.",
                    details={"file": obj.filename},
                ) from exc
            # Commit while still holding the product lock: the next waiter (a retry, or another
            # user) must see B.1 and the operation row, not the pre-revise state.
            try:
                session.commit()
            except Exception as exc:
                session.rollback()
                self._rollback_git(repo, checkpoint)
                logger.exception("Revise commit failed for %s", obj.filename)
                raise RepositoryError(
                    "The revision could not be saved, so nothing was changed.",
                    details={"file": obj.filename},
                ) from exc
            logger.info("Revised %s %s -> %s", obj.filename, old_display, new_display)
            session.refresh(obj)
            return RevisedVersion(obj=obj, source=source, version=version)

    def _replay(
        self, session: Session, obj: EngineeringObject, op_id: str
    ) -> RevisedVersion | None:
        """The stored result of an earlier, completed request with this operation id."""
        done = session.scalar(
            select(ReviseOperation).where(ReviseOperation.operation_id == op_id)
        )
        if done is None:
            return None
        if done.object_id != obj.id:
            raise ReviseOperationAlreadyCompletedError(
                "That operation id was already used for a different file.",
                details={"operation_id": op_id},
            )
        version = session.get(ObjectVersion, done.new_version_id)
        source = session.get(ObjectVersion, done.source_version_id)
        if version is None or source is None:
            return None
        logger.info("Revise replay for %s (operation %s)", obj.filename, op_id)
        return RevisedVersion(obj=obj, source=source, version=version, replayed=True)

    def _rollback_git(self, repo, checkpoint: str | None) -> None:
        if not checkpoint:
            return
        try:
            self._store.restore_checkpoint(repo, checkpoint)
        except Exception:
            logger.exception("Could not restore the vault after a failed revise")

    @staticmethod
    def _copy_metadata(
        session: Session,
        obj: EngineeringObject,
        source: ObjectVersion,
        version: ObjectVersion,
    ) -> None:
        """B.1 gets its own metadata rows, never a pointer to the source's.

        Version JSON columns (identity, materials, BOM/structure, units, mass, features) are copied
        by value on the row; parameters and the AI snapshot are separate rows copied here. System
        fields (lifecycle, created_*, revision, iteration, ids) are fresh, not inherited.
        """
        for param in session.scalars(select(Parameter).where(Parameter.version_id == source.id)):
            session.add(
                Parameter(
                    object_id=obj.id,
                    version_id=version.id,
                    name=param.name,
                    value=param.value,
                    data_type=param.data_type,
                    units=param.units,
                    description=param.description,
                    is_designated=param.is_designated,
                )
            )
        snap = session.scalar(
            select(ObjectVersionSnapshot).where(ObjectVersionSnapshot.version_id == source.id)
        )
        if snap is not None:
            session.add(
                ObjectVersionSnapshot(
                    uuid=str(uuidlib.uuid4()),
                    object_id=obj.id,
                    version_id=version.id,
                    schema_version=snap.schema_version,
                    content_hash=snap.content_hash,
                    capture_status=snap.capture_status,
                    capture_errors=snap.capture_errors,
                    snapshot_json=snap.snapshot_json,
                )
            )
        session.flush()
