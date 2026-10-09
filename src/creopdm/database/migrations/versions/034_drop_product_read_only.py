"""Alembic migration: drop products.read_only.

Revision ID: 034_drop_product_read_only
Revises: 033_product_lifecycle
Create Date: 2026-10-09

Lifecycle matrix (Administration → Lifecycle states) owns mutation lock;
the separate read_only checkbox is removed.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "034_drop_product_read_only"
down_revision: Union[str, None] = "033_product_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("products", "read_only")


def downgrade() -> None:
    op.add_column(
        "products",
        sa.Column("read_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("products", "read_only", server_default=None)
