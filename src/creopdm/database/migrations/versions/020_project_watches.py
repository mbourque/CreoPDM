"""Alembic migration: project_watches (user email subscribe per project).

Revision ID: 020_project_watches
Revises: 019_user_email_req
Create Date: 2026-09-28

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020_project_watches"
down_revision: Union[str, None] = "019_user_email_req"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_watches",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "project_id", name="uq_project_watches"),
    )


def downgrade() -> None:
    op.drop_table("project_watches")
