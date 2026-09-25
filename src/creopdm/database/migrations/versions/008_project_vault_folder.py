"""Add projects.vault_folder for custom vault directory names.

Revision ID: 008_project_vault_folder
Revises: 007_creo_features
Create Date: 2026-09-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_project_vault_folder"
down_revision: Union[str, None] = "007_creo_features"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.add_column(sa.Column("vault_folder", sa.String(length=200), nullable=True))
    op.execute("UPDATE projects SET vault_folder = uuid WHERE vault_folder IS NULL OR vault_folder = ''")
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column("vault_folder", existing_type=sa.String(length=200), nullable=False)
        batch_op.create_index("ix_projects_vault_folder", ["vault_folder"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch_op:
        batch_op.drop_index("ix_projects_vault_folder")
        batch_op.drop_column("vault_folder")
