"""Completed Revise operations, keyed by the client's operation id (retry safety)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from creopdm.database.base import Base


class ReviseOperation(Base):
    """One row per completed Revise that carried an operation id.

    Written in the same transaction as the new version, so a row exists exactly when B.1 does.
    The unique operation_id is what stops a retry (or two concurrent identical requests) from
    allocating another revision: the retry returns the version stored here.
    """

    __tablename__ = "revise_operations"

    id: Mapped[int] = mapped_column(primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"), index=True)
    source_version_id: Mapped[int] = mapped_column(ForeignKey("object_versions.id"))
    new_version_id: Mapped[int] = mapped_column(ForeignKey("object_versions.id"))
    user_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="COMPLETED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
