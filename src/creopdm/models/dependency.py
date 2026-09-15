"""SQLAlchemy model for assembly/reference dependency graph."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from creopdm.constants import DependencyType
from creopdm.database.base import Base


class Dependency(Base):
    __tablename__ = "dependencies"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "parent_object_id",
            "child_object_id",
            "dependency_type",
            name="uq_dependencies_edge",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    parent_object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"), index=True)
    child_object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"), index=True)
    dependency_type: Mapped[str] = mapped_column(
        String(32),
        default=DependencyType.ASSEMBLY_MEMBER.value,
    )
    quantity: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
