"""Alembic migration: users, roles, permissions for session auth.

Revision ID: 009_auth_users
Revises: 008_project_vault_folder
Create Date: 2026-09-27
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_auth_users"
down_revision: Union[str, None] = "008_project_vault_folder"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BUILTIN_ROLES = (
    ("Administrator", "Full system administration access."),
    ("PDM Manager", "Manage engineering data without full server administration."),
    ("Engineer", "Normal CAD/PDM authoring user."),
    ("Viewer", "Read-only access to assigned projects."),
)

_PERMISSIONS = (
    ("users.manage", "Create, edit, and disable users"),
    ("settings.manage", "Change global CreoPDM settings"),
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("uuid"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_uuid", "users", ["uuid"])
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_status", "users", ["status"])

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("uuid"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_roles_uuid", "roles", ["uuid"])

    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint("key"),
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), primary_key=True),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_roles"),
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), primary_key=True),
        sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id"), primary_key=True),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permissions"),
    )

    roles = sa.table(
        "roles",
        sa.column("id", sa.Integer),
        sa.column("uuid", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("is_builtin", sa.Boolean),
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", sa.Integer),
        sa.column("key", sa.String),
        sa.column("description", sa.Text),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_id", sa.Integer),
        sa.column("permission_id", sa.Integer),
    )

    conn = op.get_bind()
    for name, description in _BUILTIN_ROLES:
        conn.execute(
            sa.insert(roles).values(
                uuid=str(uuid.uuid4()),
                name=name,
                description=description,
                is_builtin=True,
            )
        )
    for key, description in _PERMISSIONS:
        conn.execute(
            sa.insert(permissions).values(key=key, description=description)
        )

    admin_id = conn.execute(sa.select(roles.c.id).where(roles.c.name == "Administrator")).scalar_one()
    for key, _desc in _PERMISSIONS:
        perm_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar_one()
        conn.execute(sa.insert(role_permissions).values(role_id=admin_id, permission_id=perm_id))


def downgrade() -> None:
    op.drop_table("role_permissions")
    op.drop_table("user_roles")
    op.drop_table("permissions")
    op.drop_index("ix_roles_uuid", table_name="roles")
    op.drop_table("roles")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_uuid", table_name="users")
    op.drop_table("users")
