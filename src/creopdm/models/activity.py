"""SQLAlchemy model for the activity / PDM audit trail."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from creopdm.database.base import Base


class Activity(Base):
    """Append-only audit row. Survives product/object delete via snapshot columns."""

    __tablename__ = "activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        unique=True,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    # Live FKs — app nulls these when the product/object is purged (audit row kept).
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True, index=True)
    object_id: Mapped[int | None] = mapped_column(ForeignKey("objects.id"), nullable=True, index=True)
    # Denormalized so Utilities → Audit still labels events after purge.
    product_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    object_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    object_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    user: Mapped[str] = mapped_column(String(128), nullable=False)
    user_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    machine: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    product: Mapped["Product | None"] = relationship(back_populates="activities")  # noqa: F821
