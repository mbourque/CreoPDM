"""Store Creo.JS identity, materials, BOM JSON; parameter description.

Revision ID: 005_creo_metadata
Revises: 004_project_field_limits
Create Date: 2026-09-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_creo_metadata"
down_revision: Union[str, None] = "004_project_field_limits"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("object_versions") as batch_op:
        batch_op.add_column(sa.Column("identity_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("materials_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("bom_json", sa.Text(), nullable=True))
    with op.batch_alter_table("parameters") as batch_op:
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("is_designated", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("parameters") as batch_op:
        batch_op.drop_column("is_designated")
        batch_op.drop_column("description")
    with op.batch_alter_table("object_versions") as batch_op:
        batch_op.drop_column("bom_json")
        batch_op.drop_column("materials_json")
        batch_op.drop_column("identity_json")
