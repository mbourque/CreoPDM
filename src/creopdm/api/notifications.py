"""The signed-in user's notifications: what the toast and the bell show."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from creopdm.api.deps import get_context, get_db, require_permission
from creopdm.auth_constants import PERMISSION_COMMENTS_VIEW
from creopdm.context import AppContext
from creopdm.models.comment import Comment
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product
from creopdm.models.user import User
from creopdm.models.version import ObjectVersion
from creopdm.utils.timefmt import as_utc

router = APIRouter()


class NotificationIds(BaseModel):
    ids: list[int] | None = Field(default=None, max_length=200)


def _user(request: Request) -> User | None:
    user = getattr(request.state, "auth_user", None)
    return user if isinstance(user, User) else None


@router.get("/api/notifications")
def list_notifications(
    request: Request,
    after: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> dict:
    """``after=<id>``: only newer ones, oldest first (the toast poll). Otherwise the latest first."""
    require_permission(request, ctx, PERMISSION_COMMENTS_VIEW)
    user = _user(request)
    if user is None:
        return {"enabled": False, "unread": 0, "latest_id": 0, "items": []}
    rows = ctx.user_notifications.list_for_user(db, user, after=max(0, after), limit=limit)
    products = {
        p.id: p
        for p in db.scalars(select(Product).where(Product.id.in_({r.product_id for r in rows})))
    }
    comment_ids = {r.comment_id for r in rows if r.comment_id}
    comments = (
        {c.id: c for c in db.scalars(select(Comment).where(Comment.id.in_(comment_ids)))}
        if comment_ids
        else {}
    )
    # Deep links need the file and exact version a thread belongs to.
    version_ids = {c.version_id for c in comments.values() if c.version_id}
    versions = (
        {
            v.id: v
            for v in db.scalars(select(ObjectVersion).where(ObjectVersion.id.in_(version_ids)))
        }
        if version_ids
        else {}
    )
    object_ids = {v.object_id for v in versions.values()}
    objects = (
        {o.id: o for o in db.scalars(select(EngineeringObject).where(EngineeringObject.id.in_(object_ids)))}
        if object_ids
        else {}
    )
    items = []
    for r in rows:
        product = products.get(r.product_id)
        comment = comments.get(r.comment_id) if r.comment_id else None
        version = versions.get(comment.version_id) if comment is not None and comment.version_id else None
        file_obj = objects.get(version.object_id) if version is not None else None
        object_uuid = r.target_uuid if r.target_type == "OBJECT" else (
            r.target_uuid.partition("/")[2] if r.target_type == "BASELINE_MEMBER" else ""
        )
        if not object_uuid and file_obj is not None:
            object_uuid = file_obj.uuid
        items.append(
            {
                "id": r.id,
                "kind": r.kind,
                "title": r.title,
                "excerpt": r.excerpt,
                "actor": r.actor,
                "product_uuid": product.uuid if product else "",
                "product_name": product.name if product else "",
                "target_type": r.target_type,
                "target_uuid": r.target_uuid,
                "object_uuid": object_uuid,
                "version_uuid": version.uuid if version is not None else "",
                "comment_uuid": comment.uuid if comment else "",
                "thread_uuid": (
                    db.scalar(select(Comment.uuid).where(Comment.id == comment.parent_id))
                    if comment is not None and comment.parent_id
                    else (comment.uuid if comment else "")
                ),
                "created_at": as_utc(r.created_at).isoformat() if r.created_at else None,
                "seen": r.seen_at is not None,
                "read": r.read_at is not None,
            }
        )
    return {
        "enabled": True,
        "unread": ctx.user_notifications.unread_count(db, user),
        "latest_id": ctx.user_notifications.latest_id(db, user),
        "items": items,
    }


@router.post("/api/notifications/seen", status_code=204)
def mark_seen(
    payload: NotificationIds,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> None:
    """Toasted: a reload or a second tab does not toast the same message again."""
    require_permission(request, ctx, PERMISSION_COMMENTS_VIEW)
    user = _user(request)
    if user is not None:
        ctx.user_notifications.mark_seen(db, user, payload.ids or [])


@router.post("/api/notifications/read", status_code=204)
def mark_read(
    payload: NotificationIds,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> None:
    """Opened (``ids``) or everything (``ids`` omitted)."""
    require_permission(request, ctx, PERMISSION_COMMENTS_VIEW)
    user = _user(request)
    if user is not None:
        ctx.user_notifications.mark_read(db, user, payload.ids)
