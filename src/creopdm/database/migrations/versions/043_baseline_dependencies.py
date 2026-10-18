"""Alembic migration: baseline_dependencies (the exact structure a baseline captured).

Revision ID: 043_baseline_dependencies
Revises: 042_baselines_perms
Create Date: 2026-10-18

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "043_baseline_dependencies"
down_revision: Union[str, None] = "042_baselines_perms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "baselines",
        sa.Column("dependency_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "baselines",
        sa.Column("unresolved_dependency_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "baseline_dependencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("baseline_id", sa.Integer(), sa.ForeignKey("baselines.id"), nullable=False),
        sa.Column("parent_object_id", sa.Integer(), sa.ForeignKey("objects.id"), nullable=False),
        sa.Column(
            "parent_object_version_id",
            sa.Integer(),
            sa.ForeignKey("object_versions.id"),
            nullable=False,
        ),
        sa.Column("child_object_id", sa.Integer(), sa.ForeignKey("objects.id"), nullable=False),
        sa.Column(
            "child_object_version_id",
            sa.Integer(),
            sa.ForeignKey("object_versions.id"),
            nullable=True,
        ),
        sa.Column("child_filename", sa.String(length=255), nullable=False),
        sa.Column("dependency_type", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="1"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint(
            "baseline_id",
            "parent_object_id",
            "child_object_id",
            "dependency_type",
            name="uq_baseline_dependencies_edge",
        ),
    )
    op.create_index("ix_baseline_dependencies_baseline_id", "baseline_dependencies", ["baseline_id"])
    op.create_index(
        "ix_baseline_dependencies_parent_object_id", "baseline_dependencies", ["parent_object_id"]
    )
    op.create_index(
        "ix_baseline_dependencies_child_object_id", "baseline_dependencies", ["child_object_id"]
    )


def downgrade() -> None:
    op.drop_table("baseline_dependencies")
    op.drop_column("baselines", "unresolved_dependency_count")
    op.drop_column("baselines", "dependency_count")
