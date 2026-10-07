"""Alembic migration: object_version_snapshots for experimental AI model JSON.

Revision ID: 031_ai_snapshots
Revises: 030_utilities_logs
Create Date: 2026-10-07

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "031_ai_snapshots"
down_revision: Union[str, None] = "030_utilities_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "object_version_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("capture_status", sa.String(length=32), nullable=False, server_default="ok"),
        sa.Column("capture_errors", sa.Text(), nullable=True),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["object_id"], ["objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["object_versions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("uuid"),
        sa.UniqueConstraint("version_id", name="uq_object_version_snapshots_version"),
    )
    op.create_index(
        "ix_object_version_snapshots_object_id",
        "object_version_snapshots",
        ["object_id"],
    )
    op.create_index(
        "ix_object_version_snapshots_version_id",
        "object_version_snapshots",
        ["version_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_object_version_snapshots_version_id", table_name="object_version_snapshots")
    op.drop_index("ix_object_version_snapshots_object_id", table_name="object_version_snapshots")
    op.drop_table("object_version_snapshots")
