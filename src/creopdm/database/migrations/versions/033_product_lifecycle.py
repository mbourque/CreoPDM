"""Alembic migration: remap legacy product lifecycle states.

Revision ID: 033_product_lifecycle
Revises: 032_settings_ai
Create Date: 2026-10-09

ON_HOLD → IN_REVIEW, CLOSED → OBSOLETE. New states (IN_REVIEW, APPROVED,
UNDER_CHANGE, OBSOLETE, LOCKED) are string values — no schema change.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "033_product_lifecycle"
down_revision: Union[str, None] = "032_settings_ai"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE products SET state = 'IN_REVIEW' WHERE state = 'ON_HOLD'")
    op.execute("UPDATE products SET state = 'OBSOLETE' WHERE state = 'CLOSED'")


def downgrade() -> None:
    # Lossy if new IN_REVIEW / OBSOLETE rows exist — leave values as-is.
    pass
