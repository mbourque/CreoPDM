"""Alembic migration: add roles.assign permission for existing installs.

Revision ID: 015_roles_assign
Revises: 014_user_project_access
Create Date: 2026-09-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_roles_assign"
down_revision: Union[str, None] = "014_user_project_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "roles.assign"
_DESC = "Assign roles to users"
_ADMIN_KEYS = ("users.manage", "roles.manage", "settings.manage")


def upgrade() -> None:
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Integer),
        sa.column("key", sa.String),
        sa.column("description", sa.Text),
    )
    roles = sa.table(
        "roles",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Integer),
        sa.column("permission_id", sa.Integer),
    )
    conn = op.get_bind()
    perm_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == _KEY)).scalar()
    if perm_id is None:
        conn.execute(sa.insert(permissions).values(key=_KEY, description=_DESC))
        perm_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == _KEY)).scalar()
    if perm_id is None:
        return

    # Grant to roles that already have the previous full-admin trio (or Administrator by name).
    admin_key_ids = {
        key: conn.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
        for key in _ADMIN_KEYS
    }
    if any(v is None for v in admin_key_ids.values()):
        role_ids: set[int] = set()
    else:
        role_ids = set()
        for role_id, in conn.execute(sa.select(roles.c.id)).all():
            linked = {
                row[0]
                for row in conn.execute(
                    sa.select(role_permissions.c.permission_id).where(
                        role_permissions.c.role_id == role_id
                    )
                ).all()
            }
            if all(admin_key_ids[key] in linked for key in _ADMIN_KEYS):
                role_ids.add(role_id)

    admin_named = conn.execute(sa.select(roles.c.id).where(roles.c.name == "Administrator")).scalar()
    if admin_named is not None:
        role_ids.add(admin_named)

    for role_id in role_ids:
        already = conn.execute(
            sa.select(role_permissions.c.role_id).where(
                role_permissions.c.role_id == role_id,
                role_permissions.c.permission_id == perm_id,
            )
        ).scalar()
        if already is None:
            conn.execute(
                sa.insert(role_permissions).values(role_id=role_id, permission_id=perm_id)
            )


def downgrade() -> None:
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Integer),
        sa.column("key", sa.String),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Integer),
        sa.column("permission_id", sa.Integer),
    )
    conn = op.get_bind()
    perm_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == _KEY)).scalar()
    if perm_id is None:
        return
    conn.execute(sa.delete(role_permissions).where(role_permissions.c.permission_id == perm_id))
    conn.execute(sa.delete(permissions).where(permissions.c.id == perm_id))
