"""SQLAlchemy model for a PDM object version (not a Git commit)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from creopdm.database.base import Base


class ObjectVersion(Base):
    __tablename__ = "object_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"), index=True)
    revision: Mapped[str] = mapped_column(String(16), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    relative_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    creo_release: Mapped[str | None] = mapped_column(String(64), nullable=True)
    identity_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    materials_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    bom_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    units_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    mass_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    family_table_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    features_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    git_commit_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    comment: Mapped[str] = mapped_column(Text, nullable=False)

    object: Mapped["EngineeringObject"] = relationship(  # noqa: F821
        back_populates="versions",
        foreign_keys=[object_id],
        overlaps="current_version",
    )
    parameters: Mapped[list["Parameter"]] = relationship(back_populates="version")  # noqa: F821
