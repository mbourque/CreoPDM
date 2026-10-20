"""Alembic migration: an object's number can be as long as its file name (255).

Revision ID: 052_object_number_len
Revises: 051_comments_perms
Create Date: 2026-10-20

The number defaults to the file name without its extension, uppercased; long names (for example
SolidWorks part names) overflowed the old 64 characters and the whole Add failed.

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "052_object_number_len"
down_revision: Union[str, None] = "051_comments_perms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("objects") as batch:
        batch.alter_column(
            "number", existing_type=sa.String(64), type_=sa.String(255), existing_nullable=True
        )


def downgrade() -> None:
    with op.batch_alter_table("objects") as batch:
        batch.alter_column(
            "number", existing_type=sa.String(255), type_=sa.String(64), existing_nullable=True
        )
