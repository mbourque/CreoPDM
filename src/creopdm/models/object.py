"""SQLAlchemy model for a logical engineering object."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from creopdm.constants import DEFAULT_REVISION, INITIAL_ITERATION, LifecycleState, ObjectType
from creopdm.database.base import Base


class EngineeringObject(Base):
    __tablename__ = "objects"
    __table_args__ = (
        UniqueConstraint("project_id", "relative_path", name="uq_objects_project_path"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str] = mapped_column(String(32), nullable=False)
    object_type: Mapped[str] = mapped_column(String(32), default=ObjectType.OTHER.value)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    revision: Mapped[str] = mapped_column(String(16), default=DEFAULT_REVISION)
    iteration: Mapped[int] = mapped_column(default=INITIAL_ITERATION)
    lifecycle_state: Mapped[str] = mapped_column(
        String(32),
        default=LifecycleState.IN_WORK.value,
    )
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("object_versions.id", use_alter=True, name="fk_objects_current_version"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    project: Mapped["Project"] = relationship(back_populates="objects")  # noqa: F821
    versions: Mapped[list["ObjectVersion"]] = relationship(  # noqa: F821
        back_populates="object",
        foreign_keys="ObjectVersion.object_id",
        overlaps="current_version",
    )
    current_version: Mapped["ObjectVersion | None"] = relationship(  # noqa: F821
        foreign_keys=[current_version_id],
        post_update=True,
        overlaps="versions,object",
    )
    checkouts: Mapped[list["Checkout"]] = relationship(back_populates="object")  # noqa: F821
    parameters: Mapped[list["Parameter"]] = relationship(back_populates="object")  # noqa: F821
