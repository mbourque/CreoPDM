"""Alembic migration: add users.password and products.assign for existing installs.

Revision ID: 016_pw_prod_assign
Revises: 015_roles_assign
Create Date: 2026-09-27

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016_pw_prod_assign"
down_revision: Union[str, None] = "015_roles_assign"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW = (
    ("users.password", "Set or reset user passwords"),
    ("products.assign", "Assign product membership to users"),
)
# Prior full-admin set (before this migration) — grant new keys to those roles.
_PRIOR_ADMIN_KEYS = (
    "users.manage",
    "roles.assign",
    "roles.manage",
    "settings.manage",
)


def _grant_to_full_admins(conn, permissions, roles, role_permissions, perm_id: int) -> None:
    admin_key_ids = {
        key: conn.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
        for key in _PRIOR_ADMIN_KEYS
    }
    role_ids: set[int] = set()
    if all(v is not None for v in admin_key_ids.values()):
        for (role_id,) in conn.execute(sa.select(roles.c.id)).all():
            linked = {
                row[0]
                for row in conn.execute(
                    sa.select(role_permissions.c.permission_id).where(
                        role_permissions.c.role_id == role_id
                    )
                ).all()
            }
            if all(admin_key_ids[key] in linked for key in _PRIOR_ADMIN_KEYS):
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
    for key, desc in _NEW:
        perm_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
        if perm_id is None:
            conn.execute(sa.insert(permissions).values(key=key, description=desc))
            perm_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
        if perm_id is not None:
            _grant_to_full_admins(conn, permissions, roles, role_permissions, perm_id)


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
    for key, _desc in _NEW:
        perm_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
        if perm_id is None:
            continue
        conn.execute(sa.delete(role_permissions).where(role_permissions.c.permission_id == perm_id))
        conn.execute(sa.delete(permissions).where(permissions.c.id == perm_id))
