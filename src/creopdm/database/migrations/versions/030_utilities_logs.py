"""Alembic migration: add utilities.logs; grant Administrator (and health roles).

Revision ID: 030_utilities_logs
Revises: 029_audit_durable
Create Date: 2026-10-06

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "030_utilities_logs"
down_revision: Union[str, None] = "029_audit_durable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LOGS_KEY = "utilities.logs"
_LOGS_DESC = "Utilities → Logs"
_HEALTH_KEY = "utilities.health"
_HEALTH_DESC = "Utilities → Health"


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

    health_id = conn.execute(
        sa.select(permissions.c.id).where(permissions.c.key == _HEALTH_KEY)
    ).scalar()
    if health_id is not None:
        conn.execute(
            sa.update(permissions)
            .where(permissions.c.id == health_id)
            .values(description=_HEALTH_DESC)
        )

    logs_id = conn.execute(
        sa.select(permissions.c.id).where(permissions.c.key == _LOGS_KEY)
    ).scalar()
    if logs_id is None:
        conn.execute(sa.insert(permissions).values(key=_LOGS_KEY, description=_LOGS_DESC))
        logs_id = conn.execute(
            sa.select(permissions.c.id).where(permissions.c.key == _LOGS_KEY)
        ).scalar()
    else:
        conn.execute(
            sa.update(permissions)
            .where(permissions.c.id == logs_id)
            .values(description=_LOGS_DESC)
        )
    if logs_id is None:
        return
    logs_id = int(logs_id)

    role_ids: set[int] = set()
    admin_id = conn.execute(
        sa.select(roles.c.id).where(roles.c.name == "Administrator")
    ).scalar()
    if admin_id is not None:
        role_ids.add(int(admin_id))
    # Preserve prior Logs access for roles that already had Health.
    if health_id is not None:
        for (role_id,) in conn.execute(
            sa.select(role_permissions.c.role_id).where(
                role_permissions.c.permission_id == int(health_id)
            )
        ).all():
            role_ids.add(int(role_id))

    for role_id in role_ids:
        already = conn.execute(
            sa.select(role_permissions.c.role_id).where(
                role_permissions.c.role_id == role_id,
                role_permissions.c.permission_id == logs_id,
            )
        ).scalar()
        if already is None:
            conn.execute(
                sa.insert(role_permissions).values(
                    role_id=role_id, permission_id=logs_id
                )
            )


def downgrade() -> None:
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

    health_id = conn.execute(
        sa.select(permissions.c.id).where(permissions.c.key == _HEALTH_KEY)
    ).scalar()
    if health_id is not None:
        conn.execute(
            sa.update(permissions)
            .where(permissions.c.id == health_id)
            .values(description="Utilities → Health and server Logs")
        )

    logs_id = conn.execute(
        sa.select(permissions.c.id).where(permissions.c.key == _LOGS_KEY)
    ).scalar()
    if logs_id is None:
        return
    conn.execute(
        sa.delete(role_permissions).where(role_permissions.c.permission_id == logs_id)
    )
    conn.execute(sa.delete(permissions).where(permissions.c.id == logs_id))
