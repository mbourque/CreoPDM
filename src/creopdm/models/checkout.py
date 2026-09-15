"""SQLAlchemy model for pessimistic checkout locks."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import Index

from creopdm.constants import CheckoutStatus
from creopdm.database.base import Base


class Checkout(Base):
    __tablename__ = "checkouts"
    __table_args__ = (
        Index(
            "uq_checkouts_object_active",
            "object_id",
            unique=True,
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    object_id: Mapped[int] = mapped_column(ForeignKey("objects.id"), index=True)
    user_name: Mapped[str] = mapped_column(String(128), nullable=False)
    machine_name: Mapped[str] = mapped_column(String(128), nullable=False)
    workspace_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    checkout_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    heartbeat_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    status: Mapped[str] = mapped_column(String(32), default=CheckoutStatus.ACTIVE.value, index=True)

    object: Mapped["EngineeringObject"] = relationship(back_populates="checkouts")  # noqa: F821
