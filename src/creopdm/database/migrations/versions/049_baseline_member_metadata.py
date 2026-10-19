"""Alembic migration: the Creo metadata of each baseline member, copied when the baseline is made.

Revision ID: 049_baseline_member_metadata
Revises: 048_baselines_admin_perm
Create Date: 2026-10-19

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "049_baseline_member_metadata"
down_revision: Union[str, None] = "048_baselines_admin_perm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("baseline_members", sa.Column("metadata_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("baseline_members", "metadata_json")
