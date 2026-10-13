"""Alembic migration: thumbnails table (Creo embedded JPEG by content_hash).

Revision ID: 036_thumbnails
Revises: 035_lifecycle_states_manage
Create Date: 2026-10-13

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "036_thumbnails"
down_revision: Union[str, None] = "035_lifecycle_states_manage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "thumbnails",
        sa.Column("content_hash", sa.String(length=64), primary_key=True),
        sa.Column("mime", sa.String(length=64), nullable=False, server_default="image/jpeg"),
        sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bytes", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("thumbnails")
