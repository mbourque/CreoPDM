"""Alembic migration: require users.email (non-null).

Revision ID: 019_user_email_req
Revises: 018_email_manage
Create Date: 2026-09-28

Note: revision id must fit alembic_version.version_num VARCHAR(32).
SQLite needs batch_alter_table to change nullability (no ALTER COLUMN SET NOT NULL).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019_user_email_req"
down_revision: Union[str, None] = "018_email_manage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    users = sa.table(
        "users",
        sa.column("id", sa.Integer),
        sa.column("username", sa.String),
        sa.column("email", sa.String),
    )
    rows = conn.execute(sa.select(users.c.id, users.c.username, users.c.email)).all()
    for user_id, username, email in rows:
        if (email or "").strip():
            continue
        uname = (username or "user").strip() or "user"
        # Placeholder so existing accounts remain loadable; admins should update real addresses.
        conn.execute(
            sa.update(users)
            .where(users.c.id == user_id)
            .values(email=f"{uname}@creopdm.local")
        )
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "email",
            existing_type=sa.String(length=255),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "email",
            existing_type=sa.String(length=255),
            nullable=True,
        )
