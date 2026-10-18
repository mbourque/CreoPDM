"""Alembic migration: baselines and baseline_members.

Revision ID: 041_baselines
Revises: 040_revise_operations
Create Date: 2026-10-18

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "041_baselines"
down_revision: Union[str, None] = "040_revise_operations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "baselines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("baseline_type", sa.String(length=16), nullable=False, server_default="MANUAL"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="FINALIZED"),
        sa.Column("member_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finalized_by", sa.String(length=128), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operation_id", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_baselines_uuid", "baselines", ["uuid"], unique=True)
    op.create_index("ix_baselines_product_id", "baselines", ["product_id"])
    op.create_index("ix_baselines_operation_id", "baselines", ["operation_id"], unique=True)

    op.create_table(
        "baseline_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("baseline_id", sa.Integer(), sa.ForeignKey("baselines.id"), nullable=False),
        sa.Column("object_id", sa.Integer(), sa.ForeignKey("objects.id"), nullable=False),
        sa.Column(
            "object_version_id",
            sa.Integer(),
            sa.ForeignKey("object_versions.id"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("relative_path", sa.String(length=1024), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=True),
        sa.Column("revision", sa.String(length=16), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=32), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.UniqueConstraint("baseline_id", "object_id", name="uq_baseline_members_object"),
    )
    op.create_index("ix_baseline_members_baseline_id", "baseline_members", ["baseline_id"])
    op.create_index("ix_baseline_members_object_id", "baseline_members", ["object_id"])
    op.create_index(
        "ix_baseline_members_object_version_id", "baseline_members", ["object_version_id"]
    )


def downgrade() -> None:
    op.drop_table("baseline_members")
    op.drop_table("baselines")
