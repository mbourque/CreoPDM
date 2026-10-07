"""Per-version experimental AI model snapshot (features / dimensions / parameters)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from creopdm.database.base import Base


class ObjectVersionSnapshot(Base):
    """JSON snapshot attached to one object_versions row (experimental AI compare)."""

    __tablename__ = "object_version_snapshots"
    __table_args__ = (
        UniqueConstraint("version_id", name="uq_object_version_snapshots_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[int] = mapped_column(
        ForeignKey("object_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    capture_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    capture_errors: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
