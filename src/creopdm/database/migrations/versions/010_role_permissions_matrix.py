"""Alembic migration: seed core role permission matrix.

Revision ID: 010_role_permissions_matrix
Revises: 009_auth_users
Create Date: 2026-09-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_role_permissions_matrix"
down_revision: Union[str, None] = "009_auth_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PERMISSIONS = (
    ("users.manage", "Create, edit, and disable users"),
    ("settings.manage", "Change global CreoPDM settings"),
    ("projects.create", "Create projects"),
    ("projects.edit", "Edit project properties"),
    ("projects.delete", "Delete or forget projects"),
    ("objects.add", "Add files and folders to projects"),
    ("objects.checkout", "Check out objects and undo own checkout"),
    ("objects.checkin", "Check in objects"),
    ("objects.remove", "Remove objects from projects"),
    ("objects.revert", "Restore an older version as the working version"),
    ("objects.metadata", "Update Creo metadata on objects"),
)

_ROLE_KEYS = {
    "Administrator": tuple(key for key, _ in _PERMISSIONS),
    "PDM Manager": (
        "projects.create",
        "projects.edit",
        "objects.add",
        "objects.checkout",
        "objects.checkin",
        "objects.remove",
        "objects.revert",
        "objects.metadata",
    ),
    "Engineer": (
        "objects.add",
        "objects.checkout",
        "objects.checkin",
        "objects.remove",
        "objects.revert",
        "objects.metadata",
    ),
    "Viewer": (),
}


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
    for key, description in _PERMISSIONS:
        existing = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
        if existing is None:
            conn.execute(sa.insert(permissions).values(key=key, description=description))

    for role_name, keys in _ROLE_KEYS.items():
        role_id = conn.execute(sa.select(roles.c.id).where(roles.c.name == role_name)).scalar()
        if role_id is None:
            continue
        for key in keys:
            perm_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
            if perm_id is None:
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
    # Keep permission rows; only remove matrix links beyond the original admin pair.
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Integer),
        sa.column("key", sa.String),
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
    keep_admin = {"users.manage", "settings.manage"}
    for role_name, keys in _ROLE_KEYS.items():
        role_id = conn.execute(sa.select(roles.c.id).where(roles.c.name == role_name)).scalar()
        if role_id is None:
            continue
        for key in keys:
            if role_name == "Administrator" and key in keep_admin:
                continue
            perm_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
            if perm_id is None:
                continue
            conn.execute(
                sa.delete(role_permissions).where(
                    role_permissions.c.role_id == role_id,
                    role_permissions.c.permission_id == perm_id,
                )
            )
    for key, _desc in _PERMISSIONS:
        if key in keep_admin:
            continue
        conn.execute(sa.delete(permissions).where(permissions.c.key == key))
