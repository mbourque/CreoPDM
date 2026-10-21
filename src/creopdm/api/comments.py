"""Comments API: threads on products, files, versions and baselines, with images and @mentions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from creopdm.api.deps import (
    get_context,
    get_db,
    load_accessible_product,
    require_permission,
    require_product_access,
)
from creopdm.api.watch_notify import notify_product_watchers
from creopdm.auth_constants import (
    PERMISSION_COMMENTS_ADD,
    PERMISSION_COMMENTS_ADMIN,
    PERMISSION_COMMENTS_RESOLVE,
    PERMISSION_COMMENTS_VIEW,
)
from creopdm.context import AppContext
from creopdm.exceptions import ValidationAppError
from creopdm.models.product import Product
from creopdm.models.user import User
from creopdm.services.comment_service import MAX_BODY, Actor
from creopdm.utils.comment_images import MAX_IMAGE_BYTES, thumb_content_type

router = APIRouter()


class CommentCreateRequest(BaseModel):
    target_type: str = Field(default="PRODUCT", max_length=24)
    target: str = Field(default="", max_length=80)
    body: str = Field(default="", max_length=MAX_BODY + 200)
    parent: str | None = Field(default=None, max_length=36)
    attachment_uuids: list[str] = Field(default_factory=list, max_length=8)
    anchor: dict | None = None


class CommentEditRequest(BaseModel):
    body: str = Field(default="", max_length=MAX_BODY + 200)
    add_attachment_uuids: list[str] = Field(default_factory=list, max_length=8)
    remove_attachment_uuids: list[str] = Field(default_factory=list, max_length=8)


class ResolveRequest(BaseModel):
    note: str = Field(default="", max_length=600)


def build_actor(request: Request, ctx: AppContext) -> Actor:
    """Who is acting, and whether their role lets them resolve or delete anyone's comments."""
    user = getattr(request.state, "auth_user", None)
    user = user if isinstance(user, User) else None
    identity = ctx.users.get_current_user()
    perms = getattr(request.state, "permissions", None) or frozenset()
    everything = not ctx.auth_enabled
    username = user.username if user is not None else identity.user_name
    display = (user.display_name or user.username) if user is not None else identity.user_name
    return Actor(
        user=user,
        username=username,
        display_name=display,
        can_resolve_any=everything or PERMISSION_COMMENTS_RESOLVE in perms,
        can_admin=everything or PERMISSION_COMMENTS_ADMIN in perms,
    )


def _identity(ctx: AppContext, actor: Actor):
    identity = ctx.users.get_current_user()
    return identity


@router.get("/api/products/{product_id}/comments")
def list_comments(
    product_id: str,
    request: Request,
    target_type: str = "",
    target: str = "",
    filter: str = "open",
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[dict]:
    require_permission(request, ctx, PERMISSION_COMMENTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    actor = build_actor(request, ctx)
    return ctx.comments.list_threads(
        db,
        product,
        actor,
        target_type=target_type.strip().upper() or None,
        target_uuid=target.strip() or None,
        filter=filter,
    )


@router.get("/api/products/{product_id}/comments/summary")
def comments_summary(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> dict:
    require_permission(request, ctx, PERMISSION_COMMENTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    return ctx.comments.summary(db, product, build_actor(request, ctx))


@router.get("/api/products/{product_id}/mentionable")
def mentionable_users(
    product_id: str,
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[dict]:
    """People who can be @mentioned: the product's audience (never e-mail addresses)."""
    require_permission(request, ctx, PERMISSION_COMMENTS_ADD)
    product = load_accessible_product(request, ctx, db, product_id)
    return ctx.comments.mentionable(db, product, q, exclude_user_id=build_actor(request, ctx).user_id)


@router.post("/api/products/{product_id}/comments", status_code=201)
def create_comment(
    product_id: str,
    payload: CommentCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> dict:
    require_permission(request, ctx, PERMISSION_COMMENTS_ADD)
    product = load_accessible_product(request, ctx, db, product_id)
    actor = build_actor(request, ctx)
    result = ctx.comments.create(
        db,
        product,
        actor,
        _identity(ctx, actor),
        target_type=payload.target_type.strip().upper(),
        target_uuid=payload.target,
        body=payload.body,
        parent_uuid=payload.parent,
        attachment_uuids=payload.attachment_uuids,
        anchor=payload.anchor,
        base_url=str(request.base_url),
    )
    excerpt = " ".join((result.get("body") or "").split())[:200]
    notify_product_watchers(
        request,
        ctx,
        db,
        product,
        action="Comment added",
        filenames=[],
        what=f"{result.get('target_name') or product.name}: {excerpt}".strip(": "),
        what_label="Comment",
    )
    return result


@router.patch("/api/comments/{comment_uuid}")
def edit_comment(
    comment_uuid: str,
    payload: CommentEditRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> dict:
    require_permission(request, ctx, PERMISSION_COMMENTS_ADD)
    product = _product_of(request, ctx, db, comment_uuid)
    actor = build_actor(request, ctx)
    return ctx.comments.edit(
        db,
        product,
        actor,
        _identity(ctx, actor),
        comment_uuid,
        body=payload.body,
        add_attachment_uuids=payload.add_attachment_uuids,
        remove_attachment_uuids=payload.remove_attachment_uuids,
        base_url=str(request.base_url),
    )


@router.delete("/api/comments/{comment_uuid}", status_code=204)
def delete_comment(
    comment_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    require_permission(request, ctx, PERMISSION_COMMENTS_ADD)
    product = _product_of(request, ctx, db, comment_uuid)
    actor = build_actor(request, ctx)
    ctx.comments.delete(db, product, actor, _identity(ctx, actor), comment_uuid)
    return Response(status_code=204)


@router.post("/api/comments/{comment_uuid}/resolve")
def resolve_comment(
    comment_uuid: str,
    payload: ResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> dict:
    require_permission(request, ctx, PERMISSION_COMMENTS_ADD)
    product = _product_of(request, ctx, db, comment_uuid)
    actor = build_actor(request, ctx)
    return ctx.comments.resolve(
        db,
        product,
        actor,
        _identity(ctx, actor),
        comment_uuid,
        note=payload.note,
        base_url=str(request.base_url),
    )


@router.post("/api/comments/{comment_uuid}/reopen")
def reopen_comment(
    comment_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> dict:
    require_permission(request, ctx, PERMISSION_COMMENTS_ADD)
    product = _product_of(request, ctx, db, comment_uuid)
    actor = build_actor(request, ctx)
    return ctx.comments.reopen(
        db, product, actor, _identity(ctx, actor), comment_uuid, base_url=str(request.base_url)
    )


def _product_of(request: Request, ctx: AppContext, db: Session, comment_uuid: str) -> Product:
    comment = ctx.comments.find(db, comment_uuid)
    product = db.get(Product, comment.product_id)
    require_product_access(request, ctx, product)
    return product


# ---------------------------------------------------------------------- images
@router.post("/api/products/{product_id}/comment-attachments", status_code=201)
async def upload_comment_image(
    product_id: str,
    request: Request,
    filename: str = "",
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> dict:
    """One image as the raw request body (a paste or a picked file). Returns a draft to attach."""
    require_permission(request, ctx, PERMISSION_COMMENTS_ADD)
    product = load_accessible_product(request, ctx, db, product_id)
    declared = int(request.headers.get("content-length") or 0)
    if declared > MAX_IMAGE_BYTES + 1024:
        raise ValidationAppError("An image can be at most 5 MB.")
    raw = await request.body()
    row = ctx.comments.upload_attachment(db, product, build_actor(request, ctx), filename, raw)
    return {
        "uuid": row.uuid,
        "filename": row.filename,
        "size": row.size,
        "width": row.width,
        "height": row.height,
        "url": f"/api/comment-attachments/{row.uuid}",
        "thumb_url": f"/api/comment-attachments/{row.uuid}/thumb",
    }


def _serve(request: Request, ctx: AppContext, db: Session, attachment_uuid: str, thumb: bool):
    require_permission(request, ctx, PERMISSION_COMMENTS_VIEW)
    row = ctx.comments.get_attachment(db, attachment_uuid)
    require_product_access(request, ctx, db.get(Product, row.product_id))
    return Response(
        content=row.thumb if thumb else row.data,
        media_type=thumb_content_type(row.content_type) if thumb else row.content_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/api/comment-attachments/{attachment_uuid}")
def get_comment_image(
    attachment_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    return _serve(request, ctx, db, attachment_uuid, False)


@router.get("/api/comment-attachments/{attachment_uuid}/thumb")
def get_comment_image_thumb(
    attachment_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    return _serve(request, ctx, db, attachment_uuid, True)
