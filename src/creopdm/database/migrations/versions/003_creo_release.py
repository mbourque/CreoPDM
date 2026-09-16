"""Store Creo release from native model UGC headers.

Revision ID: 003_creo_release
Revises: 002_version_filenames
Create Date: 2026-09-16
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_creo_release"
down_revision: Union[str, None] = "002_version_filenames"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("object_versions") as batch_op:
        batch_op.add_column(sa.Column("creo_release", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("object_versions") as batch_op:
        batch_op.drop_column("creo_release")
