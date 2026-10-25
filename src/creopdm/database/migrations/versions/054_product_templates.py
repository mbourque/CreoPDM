"""Alembic migration: product templates (products.is_template) and templates.* permissions.

Revision ID: 054_product_templates
Revises: 053_purge_deleted_threads
Create Date: 2026-10-25

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "054_product_templates"
down_revision: Union[str, None] = "053_purge_deleted_threads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (key, description, starter roles that get it)
_PERMISSIONS = (
    ("templates.view", "See product templates in the product list", ("Administrator", "PDM Manager")),
    ("templates.create", "Create product templates", ("Administrator",)),
    (
        "templates.edit",
        "Change the files, folders and properties of a product template",
        ("Administrator", "PDM Manager"),
    ),
    ("templates.delete", "Delete product templates", ("Administrator",)),
)


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("is_template", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Integer),
        sa.column("key", sa.String),
        sa.column("description", sa.Text),
    )
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("name", sa.String))
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Integer),
        sa.column("permission_id", sa.Integer),
    )
    conn = op.get_bind()
    for key, description, grant_roles in _PERMISSIONS:
        perm_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
        if perm_id is None:
            conn.execute(sa.insert(permissions).values(key=key, description=description))
            perm_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
        if perm_id is None:
            continue
        for role_name in grant_roles:
            role_id = conn.execute(sa.select(roles.c.id).where(roles.c.name == role_name)).scalar()
            if role_id is None:
                continue
            linked = conn.execute(
                sa.select(role_permissions.c.role_id).where(
                    role_permissions.c.role_id == role_id,
                    role_permissions.c.permission_id == perm_id,
                )
            ).scalar()
            if linked is None:
                conn.execute(sa.insert(role_permissions).values(role_id=role_id, permission_id=perm_id))


def downgrade() -> None:
    op.drop_column("products", "is_template")
