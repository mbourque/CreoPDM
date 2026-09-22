from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Response
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from creopdm.api.deps import get_context, get_db
from creopdm.api.serializers import object_to_response
from creopdm.constants import LifecycleState
from creopdm.context import AppContext
from creopdm.logging_setup import get_logger
from creopdm.schemas.common import (
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
    user = ctx.users.get_current_user()
    checkouts = ctx.checkouts.active_map(db, [obj.id for obj in objects])
    project = objects[0].project
    status = ctx.workspaces._git_status(project)
    name_labels, ext_labels = type_label_maps(ctx.config.type_labels())
    in_workspace = ctx.workspaces.local_copy_uuids(project, objects)
    extras, vault, dirty_paths, untracked_by_logical = ctx.workspaces._status_lookups(project, status)
    presented: list[ObjectResponse] = []
    for obj in objects:
        checkout = checkouts.get(obj.id)
        view = ctx.checkouts.describe(obj, checkout, user)
        pending = ctx.workspaces._pending_from_status(
            project,
            obj,
            status,
            extras=extras,
            vault=vault,
            dirty_paths=dirty_paths,
            untracked_by_logical=untracked_by_logical,
        )
        modified = pending is not None
        force_checkin = (
            checkout is None
            and pending is not None
            and obj.lifecycle_state == LifecycleState.IN_WORK.value
        )
        presented.append(
            object_to_response(
                obj,
                obj.project.uuid,
                view=view,
                modified_locally=modified,
                current_user=user,
                can_checkin=view.can_checkin or force_checkin,
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


@router.post("/api/objects/batch/checkout", response_model=BatchOperationResponse)
def checkout_batch(
    payload: BatchObjectRequest,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    result = ctx.checkouts.checkout_many(db, payload.object_ids)
    return BatchOperationResponse.model_validate(
        {**result, "workspace_root": str(ctx.config.workspace_root())}
    )


@router.post("/api/objects/batch/undo-checkout", response_model=BatchOperationResponse)
def undo_checkout_batch(
    payload: BatchObjectRequest,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    result = ctx.checkouts.undo_checkout_many(db, payload.object_ids)
    return BatchOperationResponse.model_validate(
        {**result, "workspace_root": str(ctx.config.workspace_root())}
    )


@router.post("/api/objects/batch/workspace", response_model=BatchOperationResponse)
def send_to_workspace(
    payload: BatchObjectRequest,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    pairs = []
    for object_uuid in payload.object_ids:
        obj = ctx.objects.get_object(db, object_uuid)
        pairs.append((obj.project, obj))
    result = ctx.workspaces.materialize_many(pairs)
    return BatchOperationResponse.model_validate(
        {**result, "workspace_root": str(ctx.config.workspace_root())}
    )


@router.post("/api/objects/{object_id}/checkout", response_model=ObjectResponse)
def checkout_object(
    object_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ObjectResponse:
    ctx.checkouts.checkout(db, object_id)
    obj = ctx.objects.get_object(db, object_id)
    return present_object(ctx, db, obj)


@router.post("/api/objects/{object_id}/undo-checkout", response_model=ObjectResponse)
def undo_checkout(
    object_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ObjectResponse:
    ctx.checkouts.undo_checkout(db, object_id)
    obj = ctx.objects.get_object(db, object_id)
    return present_object(ctx, db, obj)


@router.post("/api/objects/batch/heartbeat", status_code=204)
def heartbeat_batch(
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    return _run_heartbeat(db, lambda: ctx.checkouts.heartbeat_mine(db))


@router.post("/api/objects/{object_id}/heartbeat", status_code=204)
def heartbeat(
    object_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
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
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ObjectResponse:
    obj = ctx.checkins.checkin(db, object_id, payload.comment, payload.add_relative_paths)
    obj = ctx.objects.get_object(db, obj.uuid)
    return present_object(ctx, db, obj)
