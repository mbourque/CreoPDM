"""Alembic migration: durable audit snapshots; clear existing activity history.

Revision ID: 029_audit_durable
Revises: 028_utilities_perms
Create Date: 2026-10-06

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "029_audit_durable"
down_revision: Union[str, None] = "028_utilities_perms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fresh durable trail — prior rows were wiped on product delete anyway.
    op.execute(sa.text("DELETE FROM activities"))

    with op.batch_alter_table("activities") as batch:
        batch.add_column(sa.Column("product_uuid", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("product_name", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("object_uuid", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("object_filename", sa.String(length=512), nullable=True))
        batch.create_index("ix_activities_product_uuid", ["product_uuid"])
        batch.create_index("ix_activities_object_uuid", ["object_uuid"])


def downgrade() -> None:
    with op.batch_alter_table("activities") as batch:
        batch.drop_index("ix_activities_object_uuid")
        batch.drop_index("ix_activities_product_uuid")
        batch.drop_column("object_filename")
        batch.drop_column("object_uuid")
        batch.drop_column("product_name")
        batch.drop_column("product_uuid")
