"""SQLAlchemy model for per-version Creo/engineering parameters."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from creopdm.database.base import Base


class Parameter(Base):
    __tablename__ = "parameters"

    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"), index=True)
    version_id: Mapped[int | None] = mapped_column(ForeignKey("object_versions.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_type: Mapped[str] = mapped_column(String(32), default="STRING")
    units: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_designated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    object: Mapped["EngineeringObject"] = relationship(back_populates="parameters")  # noqa: F821
    version: Mapped["ObjectVersion | None"] = relationship(back_populates="parameters")  # noqa: F821
