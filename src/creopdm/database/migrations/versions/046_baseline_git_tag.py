"""Alembic migration: optional Git tag on baselines.

Revision ID: 046_baseline_git_tag
Revises: 045_baseline_git_commit
Create Date: 2026-10-18

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "046_baseline_git_tag"
down_revision: Union[str, None] = "045_baseline_git_commit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("baselines", sa.Column("git_tag_name", sa.String(length=255), nullable=True))
    op.add_column(
        "baselines",
        sa.Column("git_tag_status", sa.String(length=16), nullable=False, server_default="NONE"),
    )
    op.add_column("baselines", sa.Column("git_tag_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("baselines", "git_tag_error")
    op.drop_column("baselines", "git_tag_status")
    op.drop_column("baselines", "git_tag_name")
