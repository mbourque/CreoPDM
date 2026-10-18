"""Alembic migration: add baselines.view and baselines.create; grant to starter roles.

Revision ID: 042_baselines_perms
Revises: 041_baselines
Create Date: 2026-10-18

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "042_baselines_perms"
down_revision: Union[str, None] = "041_baselines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (key, description, starter roles that get it)
_PERMISSIONS = (
    (
        "baselines.view",
        "View baselines (exact configuration snapshots) of a product",
        ("Administrator", "PDM Manager", "Engineer", "Viewer"),
    ),
    (
        "baselines.create",
        "Create a baseline of a product's current configuration",
        ("Administrator", "PDM Manager", "Engineer"),
    ),
)


def upgrade() -> None:
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
        perm_id = conn.execute(
            sa.select(permissions.c.id).where(permissions.c.key == key)
        ).scalar()
        if perm_id is None:
            conn.execute(sa.insert(permissions).values(key=key, description=description))
            perm_id = conn.execute(
                sa.select(permissions.c.id).where(permissions.c.key == key)
            ).scalar()
        if perm_id is None:
            continue
        for role_name in grant_roles:
            role_id = conn.execute(
                sa.select(roles.c.id).where(roles.c.name == role_name)
            ).scalar()
            if role_id is None:
                continue
            linked = conn.execute(
                sa.select(role_permissions.c.role_id).where(
                    role_permissions.c.role_id == role_id,
                    role_permissions.c.permission_id == perm_id,
                )
            ).scalar()
            if linked is None:
                conn.execute(
                    sa.insert(role_permissions).values(role_id=role_id, permission_id=perm_id)
                )


def downgrade() -> None:
    permissions = sa.table(
        "permissions", sa.column("id", sa.Integer), sa.column("key", sa.String)
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Integer),
        sa.column("permission_id", sa.Integer),
    )
    conn = op.get_bind()
    for key, _description, _roles in _PERMISSIONS:
        perm_id = conn.execute(
            sa.select(permissions.c.id).where(permissions.c.key == key)
        ).scalar()
        if perm_id is None:
            continue
        conn.execute(
            sa.delete(role_permissions).where(role_permissions.c.permission_id == perm_id)
        )
        conn.execute(sa.delete(permissions).where(permissions.c.id == perm_id))
