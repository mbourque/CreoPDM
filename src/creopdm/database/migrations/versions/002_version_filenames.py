"""Store the real filename on each object version.

Revision ID: 002_version_filenames
Revises: 001_initial
Create Date: 2026-09-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_version_filenames"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("object_versions") as batch_op:
        batch_op.add_column(sa.Column("filename", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("relative_path", sa.String(length=1024), nullable=True))
    op.execute(
        """
        UPDATE object_versions
        SET filename = (SELECT filename FROM objects WHERE objects.id = object_versions.object_id),
            relative_path = (SELECT relative_path FROM objects WHERE objects.id = object_versions.object_id)
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("object_versions") as batch_op:
        batch_op.drop_column("relative_path")
        batch_op.drop_column("filename")
