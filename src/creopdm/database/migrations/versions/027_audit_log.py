"""Alembic migration: enrich activities for Utilities Audit log.

Revision ID: 027_audit_log
Revises: 026_utilities_access
Create Date: 2026-10-05

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "027_audit_log"
down_revision: Union[str, None] = "026_utilities_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("activities") as batch:
        batch.add_column(sa.Column("uuid", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("user_uuid", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("comment", sa.Text(), nullable=True))
    # Backfill uuids for existing rows so unique index can apply.
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM activities WHERE uuid IS NULL")).fetchall()
    import uuid as uuid_mod

    for (row_id,) in rows:
        conn.execute(
            sa.text("UPDATE activities SET uuid = :u WHERE id = :id"),
            {"u": str(uuid_mod.uuid4()), "id": row_id},
        )
    with op.batch_alter_table("activities") as batch:
        batch.alter_column("uuid", existing_type=sa.String(length=36), nullable=False)
        batch.create_index("ix_activities_uuid", ["uuid"], unique=True)
        batch.create_index("ix_activities_timestamp", ["timestamp"])
        batch.create_index("ix_activities_user_uuid", ["user_uuid"])


def downgrade() -> None:
    with op.batch_alter_table("activities") as batch:
        batch.drop_index("ix_activities_user_uuid")
        batch.drop_index("ix_activities_timestamp")
        batch.drop_index("ix_activities_uuid")
        batch.drop_column("comment")
        batch.drop_column("user_uuid")
        batch.drop_column("uuid")
