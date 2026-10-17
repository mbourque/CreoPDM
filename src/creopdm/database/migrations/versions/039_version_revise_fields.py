"""Alembic migration: per-version lifecycle + Revise provenance on object_versions.

Revision ID: 039_version_revise_fields
Revises: 038_release_released_objects
Create Date: 2026-10-17

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "039_version_revise_fields"
down_revision: Union[str, None] = "038_release_released_objects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UNIQUE = "uq_object_versions_revision_iteration"


def upgrade() -> None:
    with op.batch_alter_table("object_versions") as batch:
        batch.add_column(sa.Column("lifecycle_state", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("created_from_version_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("revision_reason", sa.Text(), nullable=True))

    conn = op.get_bind()
    # The current version of a Released file is the Released one.
    conn.execute(
        sa.text(
            "UPDATE object_versions SET lifecycle_state = 'RELEASED' "
            "WHERE id IN (SELECT current_version_id FROM objects "
            "WHERE lifecycle_state = 'RELEASED' AND current_version_id IS NOT NULL)"
        )
    )
    # One (object, revision, iteration) per version. Only enforced when history is clean:
    # an old database with a duplicate keeps working and logs nothing here.
    duplicates = conn.execute(
        sa.text(
            "SELECT 1 FROM object_versions GROUP BY object_id, revision, iteration "
            "HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicates is None:
        op.create_index(
            _UNIQUE,
            "object_versions",
            ["object_id", "revision", "iteration"],
            unique=True,
        )


def downgrade() -> None:
    try:
        op.drop_index(_UNIQUE, table_name="object_versions")
    except Exception:
        pass
    with op.batch_alter_table("object_versions") as batch:
        batch.drop_column("revision_reason")
        batch.drop_column("created_from_version_id")
        batch.drop_column("lifecycle_state")
