"""Alembic migration: add objects.revise; grant to authoring starter roles.

Revision ID: 037_objects_revise
Revises: 036_thumbnails
Create Date: 2026-10-17
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "037_objects_revise"
down_revision: Union[str, None] = "036_thumbnails"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KEY = "objects.revise"
_DESC = "Create the next revision of a released file (Revise)"
_GRANT_ROLES = ("Administrator", "PDM Manager", "Engineer")


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
    for role_name in _GRANT_ROLES:
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
