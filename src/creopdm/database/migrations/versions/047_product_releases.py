"""Alembic migration: product_releases.

Revision ID: 047_product_releases
Revises: 046_baseline_git_tag
Create Date: 2026-10-18

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "047_product_releases"
down_revision: Union[str, None] = "046_baseline_git_tag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_releases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=32), nullable=False),
        sa.Column("baseline_id", sa.Integer(), sa.ForeignKey("baselines.id"), nullable=True),
        sa.Column("released_by", sa.String(length=128), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("product_id", "number", name="uq_product_releases_number"),
    )
    op.create_index("ix_product_releases_uuid", "product_releases", ["uuid"], unique=True)
    op.create_index("ix_product_releases_product_id", "product_releases", ["product_id"])
    op.create_index("ix_product_releases_baseline_id", "product_releases", ["baseline_id"])


def downgrade() -> None:
    op.drop_table("product_releases")
