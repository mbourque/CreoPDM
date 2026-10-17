"""Alembic migration: files in already-Released products become RELEASED.

Releasing a product now releases its in-work files (Revise needs a RELEASED file).
Products released before this change get the same treatment once, here.

Revision ID: 038_release_released_objects
Revises: 037_objects_revise
Create Date: 2026-10-17

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "038_release_released_objects"
down_revision: Union[str, None] = "037_objects_revise"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    products = sa.table(
        "products",
        sa.column("id", sa.Integer),
        sa.column("state", sa.String),
    )
    objects = sa.table(
        "objects",
        sa.column("product_id", sa.Integer),
        sa.column("lifecycle_state", sa.String),
    )
    released_ids = sa.select(products.c.id).where(products.c.state == "RELEASED")
    op.get_bind().execute(
        sa.update(objects)
        .where(
            objects.c.product_id.in_(released_ids),
            objects.c.lifecycle_state == "IN_WORK",
        )
        .values(lifecycle_state="RELEASED")
    )


def downgrade() -> None:
    # Cannot tell which files were released by this migration versus later; leave as is.
    pass
