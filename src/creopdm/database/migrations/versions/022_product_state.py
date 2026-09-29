"""Alembic migration: product state + read_only.

Revision ID: 022_product_state
Revises: 021_password_reset
Create Date: 2026-09-29

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "022_product_state"
down_revision: Union[str, None] = "021_password_reset"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "state",
            sa.String(length=32),
            nullable=False,
            server_default="IN_WORK",
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "read_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("products", "read_only")
    op.drop_column("products", "state")
