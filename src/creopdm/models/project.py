"""SQLAlchemy models for projects."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from creopdm.database.base import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    number: Mapped[str | None] = mapped_column(String(25), nullable=True)
    description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    repository_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(128), default="main")
    remote_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    objects: Mapped[list["EngineeringObject"]] = relationship(back_populates="project")  # noqa: F821
    activities: Mapped[list["Activity"]] = relationship(back_populates="project")  # noqa: F821
    remotes: Mapped[list["Remote"]] = relationship(back_populates="project")  # noqa: F821
