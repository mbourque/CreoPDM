"""Alembic migration: replace utilities.access with granular Utilities keys.

Revision ID: 028_utilities_perms
Revises: 027_audit_log
Create Date: 2026-10-05

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "028_utilities_perms"
down_revision: Union[str, None] = "027_audit_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_KEY = "utilities.access"

_NEW_KEYS: tuple[tuple[str, str], ...] = (
    ("utilities.availability", "Utilities → Availability (site maintenance message)"),
    ("utilities.email_users", "Utilities → Email all users"),
    ("utilities.compact_product", "Utilities → Compact product vault history"),
    ("utilities.rebuild_product", "Utilities → Rebuild product database"),
    ("utilities.delete_product", "Utilities → Delete products"),
    ("utilities.audit", "Utilities → Audit log"),
    ("utilities.health", "Utilities → Health and server Logs"),
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

    new_ids: dict[str, int] = {}
    for key, desc in _NEW_KEYS:
        perm_id = conn.execute(sa.select(permissions.c.id).where(permissions.c.key == key)).scalar()
        if perm_id is None:
            conn.execute(sa.insert(permissions).values(key=key, description=desc))
            perm_id = conn.execute(
                sa.select(permissions.c.id).where(permissions.c.key == key)
            ).scalar()
        if perm_id is not None:
            new_ids[key] = int(perm_id)

    old_id = conn.execute(
        sa.select(permissions.c.id).where(permissions.c.key == _OLD_KEY)
    ).scalar()

    role_ids: set[int] = set()
    if old_id is not None:
        for (role_id,) in conn.execute(
            sa.select(role_permissions.c.role_id).where(
                role_permissions.c.permission_id == old_id
            )
        ).all():
            role_ids.add(int(role_id))
    admin_named = conn.execute(
        sa.select(roles.c.id).where(roles.c.name == "Administrator")
    ).scalar()
    if admin_named is not None:
        role_ids.add(int(admin_named))

    for role_id in role_ids:
        for perm_id in new_ids.values():
            already = conn.execute(
                sa.select(role_permissions.c.role_id).where(
                    role_permissions.c.role_id == role_id,
                    role_permissions.c.permission_id == perm_id,
                )
            ).scalar()
            if already is None:
                conn.execute(
                    sa.insert(role_permissions).values(
                        role_id=role_id, permission_id=perm_id
                    )
                )

    if old_id is not None:
        conn.execute(
            sa.delete(role_permissions).where(role_permissions.c.permission_id == old_id)
        )
        conn.execute(sa.delete(permissions).where(permissions.c.id == old_id))


def downgrade() -> None:
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

    old_id = conn.execute(
        sa.select(permissions.c.id).where(permissions.c.key == _OLD_KEY)
    ).scalar()
    if old_id is None:
        conn.execute(
            sa.insert(permissions).values(
                key=_OLD_KEY,
                description="Open Administration → Utilities (health, disk, diagnostics)",
            )
        )
        old_id = conn.execute(
            sa.select(permissions.c.id).where(permissions.c.key == _OLD_KEY)
        ).scalar()
    if old_id is None:
        return

    new_ids = []
    for key, _desc in _NEW_KEYS:
        perm_id = conn.execute(
            sa.select(permissions.c.id).where(permissions.c.key == key)
        ).scalar()
        if perm_id is not None:
            new_ids.append(int(perm_id))

    role_ids: set[int] = set()
    for perm_id in new_ids:
        for (role_id,) in conn.execute(
            sa.select(role_permissions.c.role_id).where(
                role_permissions.c.permission_id == perm_id
            )
        ).all():
            role_ids.add(int(role_id))
    admin_named = conn.execute(
        sa.select(roles.c.id).where(roles.c.name == "Administrator")
    ).scalar()
    if admin_named is not None:
        role_ids.add(int(admin_named))

    for role_id in role_ids:
        already = conn.execute(
            sa.select(role_permissions.c.role_id).where(
                role_permissions.c.role_id == role_id,
                role_permissions.c.permission_id == old_id,
            )
        ).scalar()
        if already is None:
            conn.execute(
                sa.insert(role_permissions).values(
                    role_id=role_id, permission_id=old_id
                )
            )

    for perm_id in new_ids:
        conn.execute(
            sa.delete(role_permissions).where(role_permissions.c.permission_id == perm_id)
        )
        conn.execute(sa.delete(permissions).where(permissions.c.id == perm_id))
