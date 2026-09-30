"""Alembic migration: add products.view; grant to all roles; restore starter caps.

Revision ID: 024_products_view
Revises: 023_objects_force_undo
Create Date: 2026-09-30

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024_products_view"
down_revision: Union[str, None] = "023_objects_force_undo"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VIEW_KEY = "products.view"
_VIEW_DESC = "View products"

# Additive restore for starter roles (never removes custom grants).
_STARTER_GRANTS: dict[str, tuple[str, ...]] = {
    "Administrator": (),  # filled from catalog in upgrade
    "PDM Manager": (
        "products.view",
        "products.create",
        "products.edit",
        "objects.view",
        "objects.add",
        "objects.checkout",
        "objects.checkin",
        "objects.force_undo_checkout",
        "objects.remove",
        "objects.revert",
        "objects.metadata",
        "objects.copy_to_vault",
    ),
    "Engineer": (
        "products.view",
        "objects.view",
        "objects.add",
        "objects.checkout",
        "objects.checkin",
        "objects.remove",
        "objects.revert",
        "objects.metadata",
    ),
    "Viewer": ("products.view", "objects.view"),
}


def upgrade() -> None:
    from creopdm.auth_constants import BUILTIN_PERMISSIONS

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

    # Ensure full catalog (idempotent) so Roles UI shows every known key.
    for key, description in BUILTIN_PERMISSIONS:
        perm_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
        if perm_id is None:
            conn.execute(sa.insert(permissions).values(key=key, description=description))
        else:
            conn.execute(
                sa.update(permissions).where(permissions.c.id == perm_id).values(description=description)
            )

    view_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == _VIEW_KEY)).scalar()
    if view_id is None:
        return

    # Everyone gets products.view by default (all roles, including custom).
    for (role_id,) in conn.execute(sa.select(roles.c.id)).all():
        linked = conn.execute(
            sa.select(role_permissions.c.role_id).where(
                role_permissions.c.role_id == role_id,
                role_permissions.c.permission_id == view_id,
            )
        ).scalar()
        if linked is None:
            conn.execute(
                sa.insert(role_permissions).values(role_id=role_id, permission_id=view_id)
            )

    starter = dict(_STARTER_GRANTS)
    starter["Administrator"] = tuple(key for key, _ in BUILTIN_PERMISSIONS)

    def _ensure_role_keys(role_name: str, keys: tuple[str, ...]) -> None:
        role_id = conn.execute(sa.select(roles.c.id).where(roles.c.name == role_name)).scalar()
        if role_id is None:
            return
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

    for role_name, keys in starter.items():
        _ensure_role_keys(role_name, keys)


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
    perm_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == _VIEW_KEY)).scalar()
    if perm_id is None:
        return
    conn.execute(sa.delete(role_permissions).where(role_permissions.c.permission_id == perm_id))
    conn.execute(sa.delete(permissions).where(permissions.c.id == perm_id))
