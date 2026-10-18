"""Alembic migration: baselines.structure_indexed.

Revision ID: 044_baseline_structure_flag
Revises: 043_baseline_dependencies
Create Date: 2026-10-18

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "044_baseline_structure_flag"
down_revision: Union[str, None] = "043_baseline_dependencies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing baselines predate the check: assume the structure was captured as far as it could be.
    op.add_column(
        "baselines",
        sa.Column("structure_indexed", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("baselines", "structure_indexed")
