"""Alembic migration: comments, mentions, comment images and user notifications.

Revision ID: 050_comments
Revises: 049_baseline_member_metadata
Create Date: 2026-10-20

Note: revision id must fit alembic_version.version_num VARCHAR(32).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "050_comments"
down_revision: Union[str, None] = "049_baseline_member_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(36), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("target_type", sa.String(24), nullable=False),
        sa.Column("target_uuid", sa.String(80), nullable=False),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("object_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("anchor_json", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("comments.id"), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author", sa.String(64), nullable=False),
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(64), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.String(500), nullable=True),
        sa.Column(
            "resolved_in_version_id",
            sa.Integer(),
            sa.ForeignKey("object_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_comments_uuid", "comments", ["uuid"], unique=True)
    op.create_index("ix_comments_product_id", "comments", ["product_id"])
    op.create_index("ix_comments_target_type", "comments", ["target_type"])
    op.create_index("ix_comments_target_uuid", "comments", ["target_uuid"])
    op.create_index("ix_comments_parent_id", "comments", ["parent_id"])
    op.create_index("ix_comments_author_user_id", "comments", ["author_user_id"])

    op.create_table(
        "comment_mentions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("comment_id", sa.Integer(), sa.ForeignKey("comments.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    )
    op.create_index("ix_comment_mentions_comment_id", "comment_mentions", ["comment_id"])
    op.create_index("ix_comment_mentions_user_id", "comment_mentions", ["user_id"])

    op.create_table(
        "comment_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.String(36), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("comment_id", sa.Integer(), sa.ForeignKey("comments.id"), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("thumb", sa.LargeBinary(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_comment_attachments_uuid", "comment_attachments", ["uuid"], unique=True)
    op.create_index("ix_comment_attachments_product_id", "comment_attachments", ["product_id"])
    op.create_index("ix_comment_attachments_comment_id", "comment_attachments", ["comment_id"])

    op.create_table(
        "user_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("comment_id", sa.Integer(), sa.ForeignKey("comments.id"), nullable=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("target_type", sa.String(24), nullable=False),
        sa.Column("target_uuid", sa.String(80), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("excerpt", sa.String(300), nullable=False, server_default=""),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_notifications_user_id", "user_notifications", ["user_id"])
    op.create_index("ix_user_notifications_comment_id", "user_notifications", ["comment_id"])
    op.create_index("ix_user_notifications_product_id", "user_notifications", ["product_id"])


def downgrade() -> None:
    op.drop_table("user_notifications")
    op.drop_table("comment_attachments")
    op.drop_table("comment_mentions")
    op.drop_table("comments")
