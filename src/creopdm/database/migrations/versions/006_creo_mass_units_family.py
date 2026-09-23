"""Store Creo.JS units, mass properties, and family table JSON.

Revision ID: 006_creo_mass_units_family
Revises: 005_creo_metadata
Create Date: 2026-09-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_creo_mass_units_family"
down_revision: Union[str, None] = "005_creo_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("object_versions") as batch_op:
        batch_op.add_column(sa.Column("units_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("mass_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("family_table_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("object_versions") as batch_op:
        batch_op.drop_column("family_table_json")
        batch_op.drop_column("mass_json")
        batch_op.drop_column("units_json")
