"""Alembic migration: add roles.manage permission for existing installs.

Revision ID: 011_roles_manage
Revises: 010_role_permissions_matrix
Create Date: 2026-09-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011_roles_manage"
down_revision: Union[str, None] = "010_role_permissions_matrix"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "roles.manage"
_DESC = "Create, edit, and delete roles"


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

    # Grant to Administrator starter if present (existing installs).
    admin_id = conn.execute(sa.select(roles.c.id).where(roles.c.name == "Administrator")).scalar()
    if admin_id is not None and perm_id is not None:
        linked = conn.execute(
            sa.select(role_permissions.c.role_id).where(
                role_permissions.c.role_id == admin_id,
                role_permissions.c.permission_id == perm_id,
            )
        ).scalar()
        if linked is None:
            conn.execute(
                sa.insert(role_permissions).values(role_id=admin_id, permission_id=perm_id)
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
