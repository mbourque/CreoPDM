"""Alembic migration: baselines.git_commit_sha.

Revision ID: 045_baseline_git_commit
Revises: 044_baseline_structure_flag
Create Date: 2026-10-18

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "045_baseline_git_commit"
down_revision: Union[str, None] = "044_baseline_structure_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Baselines made before this change have no recorded repository commit (NULL).
    op.add_column("baselines", sa.Column("git_commit_sha", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("baselines", "git_commit_sha")
