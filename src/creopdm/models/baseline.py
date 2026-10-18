"""Baselines: immutable, exact configuration snapshots of a product."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    inspect,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from creopdm.database.base import Base


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
