"""Store Creo.JS feature tree JSON for parts/solids.

Revision ID: 007_creo_features
Revises: 006_creo_mass_units_family
Create Date: 2026-09-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_creo_features"
down_revision: Union[str, None] = "006_creo_mass_units_family"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("object_versions") as batch_op:
        batch_op.add_column(sa.Column("features_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("object_versions") as batch_op:
        batch_op.drop_column("features_json")
