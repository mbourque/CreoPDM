"""Baselines: capture an exact, immutable snapshot of a product's current configuration."""

from __future__ import annotations

import uuid as uuidlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, joinedload, selectinload

from creopdm.constants import ActivityAction, LifecycleState
from creopdm.exceptions import (
    BaselineEmptyError,
    BaselineNameConflictError,
    BaselineNotFoundError,
    ValidationAppError,
)
from creopdm.logging_setup import get_logger
from creopdm.models.baseline import Baseline, BaselineMember
from creopdm.models.object import EngineeringObject
from creopdm.models.version import ObjectVersion
from creopdm.models.product import Product
from creopdm.services.activity_service import ActivityService
from creopdm.services.lock_manager import ProductLockManager
from creopdm.utils.identity import CurrentUserProvider

logger = get_logger("baselines")

NAME_MAX_LENGTH = 255
DESCRIPTION_MAX_LENGTH = 2000
BASELINE_TYPE_MANUAL = "MANUAL"
STATUS_FINALIZED = "FINALIZED"


def clean_name(name: str | None) -> str:
    text = " ".join((name or "").split())
    if not text:
        raise ValidationAppError("A baseline name is required.")
    if len(text) > NAME_MAX_LENGTH:
        raise ValidationAppError(f"The baseline name is too long (max {NAME_MAX_LENGTH} characters).")
    return text


def clean_description(description: str | None) -> str | None:
    text = (description or "").strip()
    if len(text) > DESCRIPTION_MAX_LENGTH:
        raise ValidationAppError(
            f"The description is too long (max {DESCRIPTION_MAX_LENGTH} characters)."
        )
    return text or None


class BaselineService:
    def __init__(
        self,
        locks: ProductLockManager,
        activities: ActivityService,
        users: CurrentUserProvider,
    ) -> None:
        self._locks = locks
        self._activities = activities
        self._users = users

    # ---- reads -------------------------------------------------------------------------

    def list_for_product(self, session: Session, product: Product) -> list[Baseline]:
        """Newest first."""
        return list(
            session.scalars(
                select(Baseline)
                .where(Baseline.product_id == product.id)
                .order_by(Baseline.id.desc())
            )
        )

    def count_for_product(self, session: Session, product_id: int) -> int:
        return len(
            list(session.scalars(select(Baseline.id).where(Baseline.product_id == product_id)))
        )

    def get(self, session: Session, baseline_uuid: str) -> Baseline:
        row = session.scalar(
            select(Baseline)
            .options(selectinload(Baseline.members))
            .where(Baseline.uuid == (baseline_uuid or "").strip())
        )
        if row is None:
            raise BaselineNotFoundError("Baseline not found.", details={"uuid": baseline_uuid})
        return row

    def members(self, session: Session, baseline: Baseline) -> list[dict]:
        """The baseline's exact members, resolved through the STORED version ids.

        Never through the object's current version: after later check-ins, revisions or a rename
        this still answers with what was captured. ``status`` compares to the current version only
        for information.
        """
        current = aliased(ObjectVersion)
        rows = session.execute(
            select(BaselineMember, ObjectVersion, EngineeringObject, current)
            .join(ObjectVersion, ObjectVersion.id == BaselineMember.object_version_id)
            .join(EngineeringObject, EngineeringObject.id == BaselineMember.object_id)
            .outerjoin(current, current.id == EngineeringObject.current_version_id)
            .where(BaselineMember.baseline_id == baseline.id)
            .order_by(BaselineMember.relative_path.asc(), BaselineMember.id.asc())
        ).all()
        out: list[dict] = []
        for member, version, obj, cur in rows:
            same = obj.current_version_id == member.object_version_id
            out.append(
                {
                    "object_uuid": obj.uuid,
                    "version_uuid": version.uuid,
                    # Name and path as they were when the baseline was made.
                    "filename": member.filename,
                    "relative_path": member.relative_path,
                    "object_type": member.object_type,
                    # Everything else from the exact captured version row.
                    "revision": version.revision,
                    "iteration": version.iteration,
                    "display_version": f"{version.revision}.{version.iteration}",
                    "lifecycle_state": version.lifecycle_state or member.lifecycle_state or "",
                    "content_hash": version.content_hash,
                    "current_version_uuid": cur.uuid if cur is not None else None,
                    "current_display_version": (
                        f"{cur.revision}.{cur.iteration}" if cur is not None else None
                    ),
                    "status": "SAME" if same else "OUT_OF_DATE",
                }
            )
        return out

    # ---- create ------------------------------------------------------------------------

    def create(
        self,
        session: Session,
        product: Product,
        name: str | None,
        description: str | None = None,
        operation_id: str | None = None,
    ) -> Baseline:
        """Capture every file's current version as an immutable, FINALIZED baseline.

        All-or-nothing, serialized per product, and committed while the product lock is still
        held. The same ``operation_id`` always returns the same baseline (retry safety).
        """
        op_id = (operation_id or "").strip() or None
        replay = self._replay(session, product, op_id)
        if replay is not None:
            return replay
        clean = clean_name(name)
        note = clean_description(description)
        user = self._users.get_current_user()

        with self._locks.acquire(product.uuid):
            replay = self._replay(session, product, op_id)
            if replay is not None:
                return replay
            self._require_unique_name(session, product, clean)
            objects = list(
                session.scalars(
                    select(EngineeringObject)
                    .options(joinedload(EngineeringObject.current_version))
                    .where(EngineeringObject.product_id == product.id)
                    .order_by(EngineeringObject.relative_path.asc())
                )
            )
            captured = [obj for obj in objects if obj.current_version is not None]
            if not captured:
                raise BaselineEmptyError(
                    f"{product.name} has no files with a checked-in version to baseline.",
                    details={"product": product.uuid},
                )
            now = datetime.now(timezone.utc)
            baseline = Baseline(
                uuid=str(uuidlib.uuid4()),
                product_id=product.id,
                name=clean,
                description=note,
                baseline_type=BASELINE_TYPE_MANUAL,
                status=STATUS_FINALIZED,
                member_count=len(captured),
                created_by=user.user_name,
                finalized_by=user.user_name,
                finalized_at=now,
                operation_id=op_id,
            )
            try:
                session.add(baseline)
                session.flush()
                session.add_all(self._members(baseline, captured))
                session.flush()
                self._activities.record(
                    session,
                    ActivityAction.BASELINE_CREATED,
                    user,
                    product_id=product.id,
                    details={
                        "baseline_uuid": baseline.uuid,
                        "baseline_name": baseline.name,
                        "baseline_type": baseline.baseline_type,
                        "member_count": baseline.member_count,
                    },
                    comment=note,
                )
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                # Same operation id, or the same name, won a race: answer from what is stored.
                replay = self._replay(session, product, op_id)
                if replay is not None:
                    return replay
                raise BaselineNameConflictError(
                    f'A baseline named "{clean}" already exists in {product.name}.',
                    details={"name": clean},
                ) from exc
            except Exception:
                session.rollback()
                logger.exception("Baseline create failed for %s", product.uuid)
                raise
            logger.info(
                "Created baseline %s (%s members) for product %s",
                baseline.uuid,
                baseline.member_count,
                product.uuid,
            )
            session.refresh(baseline)
            return baseline

    # ---- helpers -----------------------------------------------------------------------

    def _replay(self, session: Session, product: Product, op_id: str | None) -> Baseline | None:
        if op_id is None:
            return None
        found = session.scalar(select(Baseline).where(Baseline.operation_id == op_id))
        if found is None:
            return None
        if found.product_id != product.id:
            raise ValidationAppError(
                "That operation id was already used for a different product.",
                details={"operation_id": op_id},
            )
        return found

    def _require_unique_name(self, session: Session, product: Product, name: str) -> None:
        wanted = name.casefold()
        for existing in session.scalars(
            select(Baseline.name).where(Baseline.product_id == product.id)
        ):
            if str(existing).casefold() == wanted:
                raise BaselineNameConflictError(
                    f'A baseline named "{existing}" already exists in {product.name}.',
                    details={"name": existing},
                )

    @staticmethod
    def _members(baseline: Baseline, objects: list[EngineeringObject]) -> list[BaselineMember]:
        members: list[BaselineMember] = []
        for obj in objects:
            version = obj.current_version
            assert version is not None
            members.append(
                BaselineMember(
                    baseline_id=baseline.id,
                    object_id=obj.id,
                    object_version_id=version.id,
                    filename=version.filename or obj.filename,
                    relative_path=version.relative_path or obj.relative_path,
                    object_type=obj.object_type,
                    revision=version.revision,
                    iteration=version.iteration,
                    # The state of THIS version (a Released A.3 stays Released after B.1).
                    lifecycle_state=version.lifecycle_state
                    or obj.lifecycle_state
                    or LifecycleState.IN_WORK.value,
                    content_hash=version.content_hash,
                )
            )
        return members
