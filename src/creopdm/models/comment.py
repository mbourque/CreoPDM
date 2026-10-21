"""Collaboration: comments (threads on products, files, versions, baselines), their images, mentions
and the per-user notifications they create."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from creopdm.database.base import Base

TARGET_PRODUCT = "PRODUCT"
TARGET_OBJECT = "OBJECT"
TARGET_VERSION = "VERSION"
TARGET_BASELINE = "BASELINE"
TARGET_BASELINE_MEMBER = "BASELINE_MEMBER"
TARGET_TYPES = (TARGET_PRODUCT, TARGET_OBJECT, TARGET_VERSION, TARGET_BASELINE, TARGET_BASELINE_MEMBER)

NOTIFY_MENTION = "MENTION"
NOTIFY_REPLY = "REPLY"
NOTIFY_ON_MINE = "COMMENT_ON_MINE"
NOTIFY_RESOLVED = "RESOLVED"
NOTIFY_REOPENED = "REOPENED"
NOTIFY_WATCH = "WATCH"  # activity on a product the user watches (not a comment)


class Comment(Base):
    """One comment. ``parent_id`` points at the thread's first comment (one reply level)."""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    # PRODUCT | OBJECT | VERSION | BASELINE | BASELINE_MEMBER, and the uuid of that thing.
    target_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    target_uuid: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    # A version purge (Compact / Rebuild file list) keeps the comment and clears the pin.
    version_id: Mapped[int | None] = mapped_column(
        ForeignKey("object_versions.id", ondelete="SET NULL"), nullable=True
    )
    anchor_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(64), nullable=False)
    author_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resolved_in_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("object_versions.id", ondelete="SET NULL"), nullable=True
    )


class CommentMention(Base):
    __tablename__ = "comment_mentions"

    id: Mapped[int] = mapped_column(primary_key=True)
    comment_id: Mapped[int] = mapped_column(ForeignKey("comments.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class CommentAttachment(Base):
    """An image on a comment. ``comment_id`` is NULL while it is only an uploaded draft."""

    __tablename__ = "comment_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    thumb: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UserNotification(Base):
    """What the toast and the bell show to one user. ``seen_at``: toasted; ``read_at``: opened."""

    __tablename__ = "user_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"), nullable=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_uuid: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    excerpt: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
