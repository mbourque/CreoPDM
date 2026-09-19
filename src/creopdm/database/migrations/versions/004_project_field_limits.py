"""Limit project number to 25 and description to 256 characters.

Revision ID: 004_project_field_limits
Revises: 003_creo_release
Create Date: 2026-09-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_project_field_limits"
down_revision: Union[str, None] = "003_creo_release"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE projects SET number = substr(number, 1, 25) "
        "WHERE number IS NOT NULL AND length(number) > 25"
    )
    op.execute(
        "UPDATE projects SET description = substr(description, 1, 256) "
        "WHERE description IS NOT NULL AND length(description) > 256"
    )
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column(
            "number",
            existing_type=sa.String(length=64),
            type_=sa.String(length=25),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "description",
            existing_type=sa.Text(),
            type_=sa.String(length=256),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column(
            "description",
            existing_type=sa.String(length=256),
            type_=sa.Text(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "number",
            existing_type=sa.String(length=25),
            type_=sa.String(length=64),
            existing_nullable=True,
        )
