from __future__ import annotations

from collections.abc import Callable

from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from creopdm.api.deps import (
    get_context,
    get_db,
    load_accessible_objects,
    load_accessible_product,
    require_permission,
    require_product_access,
)
from creopdm.api.serializers import object_to_response
from creopdm.auth_constants import (
    PERMISSION_OBJECTS_CHECKIN,
    PERMISSION_OBJECTS_CHECKOUT,
    PERMISSION_OBJECTS_COPY_TO_VAULT,
    PERMISSION_OBJECTS_FORCE_CHECKIN,
    PERMISSION_OBJECTS_VIEW,
)
from creopdm.constants import LifecycleState
from creopdm.context import AppContext
from creopdm.exceptions import ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.services.agent_cache_zip import build_agent_cache_zip, manifest_items_for_objects
from creopdm.schemas.common import (
    AgentCacheManifestItem,
    AgentCacheManifestResponse,
    BatchObjectRequest,
    BatchOperationResponse,
    CheckinPreviewResponse,
    CheckinRequest,
    ObjectResponse,
)
from creopdm.utils.classify import display_type_label, type_label_maps

router = APIRouter()
logger = get_logger("checkout.api")


def _sqlite_busy(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "database is locked" in text or "database table is locked" in text


def _run_heartbeat(db: Session, work: Callable[[], None]) -> Response:
    """Heartbeats are best-effort; never fail a bulk write storm with 500s."""
    try:
        work()
    except OperationalError as exc:
        if not _sqlite_busy(exc):
            raise
        db.rollback()
        logger.warning("Heartbeat skipped while the database is busy")
    return Response(status_code=204)


def present_object(ctx: AppContext, db: Session, obj) -> ObjectResponse:
    return present_objects(ctx, db, [obj])[0]


def present_objects(ctx: AppContext, db: Session, objects: list) -> list[ObjectResponse]:
    """Build list rows without SHA-256 of every file. Git status is the dirty signal."""
    if not objects:
        return []
    from creopdm.product_state import product_allows_mutation

    user = ctx.users.get_current_user()
    checkouts = ctx.checkouts.active_map(db, [obj.id for obj in objects])
    product = objects[0].product
    mutable = product_allows_mutation(product)
    status = ctx.workspaces._git_status(product)
    name_labels, ext_labels = type_label_maps(ctx.config.type_labels())
    in_workspace = ctx.workspaces.local_copy_uuids(product, objects)
    extras, vault, dirty_paths, untracked_by_logical = ctx.workspaces._status_lookups(product, status)
    presented: list[ObjectResponse] = []
    for obj in objects:
        checkout = checkouts.get(obj.id)
        view = ctx.checkouts.describe(obj, checkout, user)
        pending = ctx.workspaces._pending_from_status(
            product,
            obj,
            status,
            extras=extras,
            vault=vault,
            dirty_paths=dirty_paths,
            untracked_by_logical=untracked_by_logical,
        )
        modified = pending is not None
        force_checkin = (
            mutable
            and checkout is None
            and pending is not None
            and obj.lifecycle_state == LifecycleState.IN_WORK.value
        )
        can_checkin = (view.can_checkin or force_checkin) if mutable else False
        presented.append(
            object_to_response(
                obj,
                obj.product.uuid,
                view=view,
                modified_locally=modified,
                current_user=user,
                can_checkin=can_checkin,
                in_workspace=obj.uuid in in_workspace,
                type_label=display_type_label(
                    obj.filename,
                    obj.object_type,
                    names=name_labels,
                    extensions=ext_labels,
                ),
            )
        )
    return presented


def _notify_batch_by_product(
    request: Request,
    ctx: AppContext,
    db: Session,
    objects: list,
    result: dict,
    action: str,
) -> None:
    from collections import defaultdict

    from creopdm.api.watch_notify import notify_product_watchers

    by_uuid = {obj.uuid: obj for obj in objects}
    names_by_product: dict[int, list[str]] = defaultdict(list)
    product_by_id = {}
    for item in result.get("ok") or []:
        obj = by_uuid.get(item.get("uuid") or "")
        name = item.get("filename")
        if obj is None or not name:
            continue
        names_by_product[obj.product.id].append(name)
        product_by_id[obj.product.id] = obj.product
    for product_id, names in names_by_product.items():
        notify_product_watchers(
            request,
            ctx,
            db,
            product_by_id[product_id],
            action=action,
            filenames=names,
        )


@router.post("/api/objects/batch/checkout", response_model=BatchOperationResponse)
def checkout_batch(
    payload: BatchObjectRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_CHECKOUT)
    objects = load_accessible_objects(request, ctx, db, payload.object_ids)
    result = ctx.checkouts.checkout_many(db, payload.object_ids)
    if result.get("ok"):
        _notify_batch_by_product(request, ctx, db, objects, result, "Checked out")
    return BatchOperationResponse.model_validate(
        {**result, "workspace_root": str(ctx.config.workspace_root())}
    )


@router.post("/api/objects/batch/undo-checkout", response_model=BatchOperationResponse)
def undo_checkout_batch(
    payload: BatchObjectRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_CHECKOUT)
    objects = load_accessible_objects(request, ctx, db, payload.object_ids)
    result = ctx.checkouts.undo_checkout_many(db, payload.object_ids)
    if result.get("ok"):
        _notify_batch_by_product(request, ctx, db, objects, result, "Checkout canceled")
    return BatchOperationResponse.model_validate(
        {**result, "workspace_root": str(ctx.config.workspace_root())}
    )


@router.post("/api/objects/batch/force-checkin", response_model=BatchOperationResponse)
def force_checkin_batch(
    payload: BatchObjectRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    """Force Undo Checkout: release another user's checkout; no new version."""
    require_permission(request, ctx, PERMISSION_OBJECTS_FORCE_CHECKIN)
    objects = load_accessible_objects(request, ctx, db, payload.object_ids)
    result = ctx.checkouts.force_undo_checkout_many(db, payload.object_ids)
    if result.get("ok"):
        _notify_batch_by_product(request, ctx, db, objects, result, "Checkout force-canceled")
    return BatchOperationResponse.model_validate(
        {**result, "workspace_root": str(ctx.config.workspace_root())}
    )


@router.post("/api/objects/batch/agent-cache-manifest", response_model=AgentCacheManifestResponse)
def agent_cache_manifest(
    payload: BatchObjectRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> AgentCacheManifestResponse:
    """Content identities for agent-cache hit detection (no file bodies)."""
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    objects = load_accessible_objects(request, ctx, db, payload.object_ids)
    product_ids = {obj.product.uuid for obj in objects}
    if len(product_ids) != 1:
        raise ValidationAppError("All files must belong to the same product.")
    return AgentCacheManifestResponse(
        product_id=objects[0].product.uuid,
        items=[AgentCacheManifestItem.model_validate(item) for item in manifest_items_for_objects(objects)],
    )


@router.post("/api/objects/batch/agent-cache-archive")
def agent_cache_archive(
    payload: BatchObjectRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> FileResponse:
    """Zip vault files (nested relative paths) for one-shot agent-cache download — no Creo open prep."""
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    objects = load_accessible_objects(request, ctx, db, payload.object_ids)
    product_ids = {obj.product.uuid for obj in objects}
    if len(product_ids) != 1:
        raise ValidationAppError("All files must belong to the same product.")
    product = objects[0].product
    zip_path, count = build_agent_cache_zip(ctx.workspaces, product, objects)
    background_tasks.add_task(lambda path=zip_path: path.unlink(missing_ok=True))
    filename = f"creopdm-cache-{product.uuid[:8]}.zip"
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
        content_disposition_type="attachment",
        headers={
            "Content-Disposition": disposition,
            "X-CreoPDM-File-Count": str(count),
        },
    )


@router.post("/api/objects/batch/workspace", response_model=BatchOperationResponse)
def send_to_workspace(
    payload: BatchObjectRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_COPY_TO_VAULT)
    pairs = []
    for object_uuid in payload.object_ids:
        obj = ctx.objects.get_object(db, object_uuid)
        require_product_access(request, ctx, obj.product)
        pairs.append((obj.product, obj))
    result = ctx.workspaces.materialize_many(pairs)
    return BatchOperationResponse.model_validate(
        {**result, "workspace_root": str(ctx.config.workspace_root())}
    )


@router.post("/api/objects/{object_id}/checkout", response_model=ObjectResponse)
def checkout_object(
    object_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ObjectResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_CHECKOUT)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    ctx.checkouts.checkout(db, object_id)
    obj = ctx.objects.get_object(db, object_id)
    from creopdm.api.watch_notify import notify_product_watchers

    notify_product_watchers(
        request,
        ctx,
        db,
        obj.product,
        action="Checked out",
        filenames=[obj.filename],
        object_uuid=obj.uuid,
    )
    return present_object(ctx, db, obj)


@router.post("/api/objects/{object_id}/undo-checkout", response_model=ObjectResponse)
def undo_checkout(
    object_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ObjectResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_CHECKOUT)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    ctx.checkouts.undo_checkout(db, object_id)
    obj = ctx.objects.get_object(db, object_id)
    from creopdm.api.watch_notify import notify_product_watchers

    notify_product_watchers(
        request,
        ctx,
        db,
        obj.product,
        action="Checkout canceled",
        filenames=[obj.filename],
        object_uuid=obj.uuid,
    )
    return present_object(ctx, db, obj)


@router.post("/api/objects/{object_id}/force-checkin", response_model=ObjectResponse)
def force_checkin(
    object_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ObjectResponse:
    """Force Undo Checkout: release another user's checkout; no new version."""
    require_permission(request, ctx, PERMISSION_OBJECTS_FORCE_CHECKIN)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    ctx.checkouts.force_undo_checkout(db, object_id)
    obj = ctx.objects.get_object(db, object_id)
    from creopdm.api.watch_notify import notify_product_watchers

    notify_product_watchers(
        request,
        ctx,
        db,
        obj.product,
        action="Checkout force-canceled",
        filenames=[obj.filename],
        object_uuid=obj.uuid,
    )
    return present_object(ctx, db, obj)


@router.post("/api/objects/batch/heartbeat", status_code=204)
def heartbeat_batch(
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    require_permission(request, ctx, PERMISSION_OBJECTS_CHECKOUT)
    return _run_heartbeat(db, lambda: ctx.checkouts.heartbeat_mine(db))


@router.post("/api/objects/{object_id}/heartbeat", status_code=204)
def heartbeat(
    object_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    require_permission(request, ctx, PERMISSION_OBJECTS_CHECKOUT)
    return _run_heartbeat(db, lambda: ctx.checkouts.heartbeat(db, object_id))


@router.get("/api/objects/{object_id}/checkin-preview", response_model=CheckinPreviewResponse)
def checkin_preview(
    object_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> CheckinPreviewResponse:
    return CheckinPreviewResponse.model_validate(ctx.checkins.preview(db, object_id))


@router.post("/api/objects/{object_id}/checkin", response_model=ObjectResponse)
def checkin_object(
    object_id: str,
    payload: CheckinRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ObjectResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_CHECKIN)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    obj = ctx.checkins.checkin(db, object_id, payload.comment, payload.add_relative_paths)
    obj = ctx.objects.get_object(db, obj.uuid)
    from creopdm.api.watch_notify import notify_product_watchers

    notify_product_watchers(
        request,
        ctx,
        db,
        obj.product,
        action="Checked in",
        filenames=[obj.filename],
        object_uuid=obj.uuid,
    )
    return present_object(ctx, db, obj)
