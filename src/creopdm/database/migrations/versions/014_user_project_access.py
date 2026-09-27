"""Alembic migration: user project access (all projects or selected).

Revision ID: 014_user_project_access
Revises: 013_objects_view
Create Date: 2026-09-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_user_project_access"
down_revision: Union[str, None] = "013_objects_view"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "access_all_projects",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_table(
        "user_projects",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.UniqueConstraint("user_id", "project_id", name="uq_user_projects"),
    )


def downgrade() -> None:
    op.drop_table("user_projects")
    op.drop_column("users", "access_all_projects")
