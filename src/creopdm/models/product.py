"""SQLAlchemy models for products."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from creopdm.database.base import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    number: Mapped[str | None] = mapped_column(String(25), nullable=True)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Single path segment under vaults/ (UUID by default, or a custom name).
    vault_folder: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    repository_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(128), default="main")
    remote_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Product lifecycle (project state) — separate from object lifecycle_state.
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="IN_WORK")
    read_only: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    objects: Mapped[list["EngineeringObject"]] = relationship(back_populates="product")  # noqa: F821
    activities: Mapped[list["Activity"]] = relationship(back_populates="product")  # noqa: F821
    remotes: Mapped[list["Remote"]] = relationship(back_populates="product")  # noqa: F821
