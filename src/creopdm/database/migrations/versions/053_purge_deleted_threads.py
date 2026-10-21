"""Alembic migration: remove threads whose first comment was deleted.

Revision ID: 053_purge_deleted_threads
Revises: 052_object_number_len
Create Date: 2026-10-21

Deleting the first comment of a thread used to leave its replies behind under a "This comment was
deleted" placeholder. Deleting a thread now deletes its replies too; this clears the ones already left.

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "053_purge_deleted_threads"
down_revision: Union[str, None] = "052_object_number_len"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ROOTS = "SELECT id FROM comments WHERE deleted_at IS NOT NULL AND parent_id IS NULL"
_THREAD = f"{_ROOTS} UNION SELECT id FROM comments WHERE parent_id IN ({_ROOTS})"


def upgrade() -> None:
    conn = op.get_bind()
    for table, column in (
        ("user_notifications", "comment_id"),
        ("comment_attachments", "comment_id"),
        ("comment_mentions", "comment_id"),
    ):
        conn.execute(sa.text(f"DELETE FROM {table} WHERE {column} IN ({_THREAD})"))
    # replies first (they point at the first comment), then the first comments themselves
    conn.execute(sa.text(f"DELETE FROM comments WHERE parent_id IN ({_ROOTS})"))
    conn.execute(sa.text("DELETE FROM comments WHERE deleted_at IS NOT NULL AND parent_id IS NULL"))


def downgrade() -> None:
    pass
