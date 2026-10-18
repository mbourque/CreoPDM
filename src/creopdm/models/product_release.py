"""A product release: promoting a product to Released, tied to its exact baseline."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from creopdm.database.base import Base


class ProductRelease(Base):
    """R1, R2, ... of one product. It points at the Release baseline by id, so a release never
    depends on "latest": the baseline holds the exact versions that were released."""

    __tablename__ = "product_releases"
    __table_args__ = (UniqueConstraint("product_id", "number", name="uq_product_releases_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    # NULL only for a product with no checked-in files (nothing to capture).
    baseline_id: Mapped[int | None] = mapped_column(
        ForeignKey("baselines.id"), nullable=True, index=True
    )
    released_by: Mapped[str] = mapped_column(String(128), nullable=False)
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
