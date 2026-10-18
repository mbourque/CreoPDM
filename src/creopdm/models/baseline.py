"""Baselines: immutable, exact configuration snapshots of a product."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    inspect,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from creopdm.database.base import Base
from creopdm.exceptions import BaselineImmutableError

STATUS_DRAFT = "DRAFT"  # only inside the one transaction that captures a baseline
STATUS_FINALIZED = "FINALIZED"
STATUS_ARCHIVED = "ARCHIVED"

IMMUTABLE_MESSAGE = (
    "A finalized baseline can never be changed. Create a new baseline for a different "
    "configuration."
)
# Once finalized these never change (the name and description are labels and may).
_FROZEN_BASELINE_FIELDS = (
    "product_id",
    "baseline_type",
    "member_count",
    "dependency_count",
    "unresolved_dependency_count",
    "created_by",
    "finalized_by",
    "finalized_at",
)


class Baseline(Base):
    """One finalized snapshot. Identity is ``uuid`` — never the name."""

    __tablename__ = "baselines"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_type: Mapped[str] = mapped_column(String(16), nullable=False, default="MANUAL")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="FINALIZED")
    member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dependency_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unresolved_dependency_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalized_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Client-made id for one logical create: a retry returns the stored baseline.
    operation_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    members: Mapped[list["BaselineMember"]] = relationship(
        back_populates="baseline", order_by="BaselineMember.id"
    )


@event.listens_for(Baseline, "before_update")
def _baseline_uuid_never_changes(_mapper, _connection, target: Baseline) -> None:
    """Identity is the uuid: whatever else may change, this value never does."""
    if inspect(target).attrs.uuid.history.has_changes():
        raise ValueError("A baseline's uuid is its identity and can never be changed.")


@event.listens_for(Baseline, "before_update")
def _finalized_baseline_is_frozen(_mapper, _connection, target: Baseline) -> None:
    """After finalization: no change to what it captured, who made it, or its type, and it can
    only ever move on to ARCHIVED (never back to a draft)."""
    state = inspect(target)
    status = state.attrs.status.history
    was = status.deleted[0] if status.deleted else target.status
    if was not in (STATUS_FINALIZED, STATUS_ARCHIVED):
        return
    for field in _FROZEN_BASELINE_FIELDS:
        if state.attrs[field].history.has_changes():
            raise BaselineImmutableError(IMMUTABLE_MESSAGE, details={"field": field})
    if status.has_changes() and target.status not in (STATUS_FINALIZED, STATUS_ARCHIVED):
        raise BaselineImmutableError(IMMUTABLE_MESSAGE, details={"field": "status"})


class BaselineMember(Base):
    """One exact object version in a baseline. The ids are authoritative.

    The filename, path, revision and the rest are display copies frozen at capture so the page
    stays readable if the object is later renamed.
    """

    __tablename__ = "baseline_members"
    __table_args__ = (
        UniqueConstraint("baseline_id", "object_id", name="uq_baseline_members_object"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    baseline_id: Mapped[int] = mapped_column(ForeignKey("baselines.id"), index=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"), index=True)
    object_version_id: Mapped[int] = mapped_column(ForeignKey("object_versions.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    object_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revision: Mapped[str] = mapped_column(String(16), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    lifecycle_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    baseline: Mapped[Baseline] = relationship(back_populates="members")


class BaselineDependency(Base):
    """One structure edge as it was when the baseline was made (parent uses child).

    Stored, never recomputed: the parent and child versions are the exact ones the baseline
    captured, so later check-ins, revisions or a re-scan cannot change the structure. A child
    with no captured version is kept as an UNRESOLVED edge (``child_object_version_id`` empty)
    rather than being silently dropped.
    """

    __tablename__ = "baseline_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "baseline_id",
            "parent_object_id",
            "child_object_id",
            "dependency_type",
            name="uq_baseline_dependencies_edge",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    baseline_id: Mapped[int] = mapped_column(ForeignKey("baselines.id"), index=True)
    parent_object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"), index=True)
    parent_object_version_id: Mapped[int] = mapped_column(ForeignKey("object_versions.id"))
    child_object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"), index=True)
    child_object_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("object_versions.id"), nullable=True
    )
    child_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    dependency_type: Mapped[str] = mapped_column(String(32), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # Required edges (assembly members, drawing models, skeletons, merges) must be resolved for a
    # strict (release) baseline; plain references need not be.
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


def _parent_is_finalized(connection, baseline_id: int) -> bool:
    status = connection.execute(
        select(Baseline.__table__.c.status).where(Baseline.__table__.c.id == baseline_id)
    ).scalar()
    return status in (STATUS_FINALIZED, STATUS_ARCHIVED)


def _guard_member(_mapper, connection, target: "BaselineMember | BaselineDependency") -> None:
    """Members may be written only while the baseline is being captured (DRAFT, inside the one
    transaction that finalizes it). After that: no add, no remove, no replaced version."""
    if _parent_is_finalized(connection, target.baseline_id):
        raise BaselineImmutableError(IMMUTABLE_MESSAGE, details={"baseline_id": target.baseline_id})


event.listen(BaselineMember, "before_insert", _guard_member)
event.listen(BaselineMember, "before_update", _guard_member)
event.listen(BaselineMember, "before_delete", _guard_member)
for _hook in ("before_insert", "before_update", "before_delete"):
    event.listen(BaselineDependency, _hook, _guard_member)
