"""Alembic migration: comments.view / add / resolve / admin and the starter roles that get them.

Revision ID: 051_comments_perms
Revises: 050_comments
Create Date: 2026-10-20

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "051_comments_perms"
down_revision: Union[str, None] = "050_comments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (key, description, starter roles that get it)
_PERMISSIONS = (
    (
        "comments.view",
        "View comments and discussions on products, files and baselines",
        ("Administrator", "PDM Manager", "Engineer", "Viewer"),
    ),
    (
        "comments.add",
        "Write comments, reply and mention people",
        ("Administrator", "PDM Manager", "Engineer", "Viewer"),
    ),
    (
        "comments.resolve",
        "Resolve and reopen any comment thread",
        ("Administrator", "PDM Manager", "Engineer"),
    ),
    (
        "comments.admin",
        "Delete anyone's comment",
        ("Administrator",),
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
    pass
