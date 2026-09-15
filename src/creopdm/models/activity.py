"""SQLAlchemy model for the activity / audit trail."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from creopdm.database.base import Base


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    object_id: Mapped[int | None] = mapped_column(ForeignKey("objects.id"), nullable=True, index=True)
    user: Mapped[str] = mapped_column(String(128), nullable=False)
    machine: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped["Project | None"] = relationship(back_populates="activities")  # noqa: F821
