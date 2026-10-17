"""Alembic migration: revise_operations (retry-safe Revise).

Revision ID: 040_revise_operations
Revises: 039_version_revise_fields
Create Date: 2026-10-17

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "040_revise_operations"
down_revision: Union[str, None] = "039_version_revise_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "revise_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operation_id", sa.String(length=64), nullable=False),
        sa.Column("object_id", sa.Integer(), sa.ForeignKey("objects.id"), nullable=False),
        sa.Column(
            "source_version_id",
            sa.Integer(),
            sa.ForeignKey("object_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "new_version_id",
            sa.Integer(),
            sa.ForeignKey("object_versions.id"),
            nullable=False,
        ),
        sa.Column("user_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="COMPLETED"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )
    op.create_index("ix_revise_operations_operation_id", "revise_operations", ["operation_id"], unique=True)
    op.create_index("ix_revise_operations_object_id", "revise_operations", ["object_id"])


def downgrade() -> None:
    op.drop_index("ix_revise_operations_object_id", table_name="revise_operations")
    op.drop_index("ix_revise_operations_operation_id", table_name="revise_operations")
    op.drop_table("revise_operations")
