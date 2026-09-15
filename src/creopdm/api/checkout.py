from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from creopdm.api.deps import get_context, get_db
from creopdm.api.serializers import object_to_response
from creopdm.context import AppContext
from creopdm.schemas.common import (
    BatchObjectRequest,
    BatchOperationResponse,
    CheckinPreviewResponse,
    CheckinRequest,
    ObjectResponse,
)

router = APIRouter()


def present_object(ctx: AppContext, db: Session, obj) -> ObjectResponse:
    user = ctx.users.get_current_user()
    checkout = ctx.checkouts.active_for(db, obj.id)
    view = ctx.checkouts.describe(obj, checkout, user)
    modified = ctx.workspaces.is_modified(obj.project, obj)
    return object_to_response(
        obj,
        obj.project.uuid,
        view=view,
        modified_locally=modified,
        current_user=user,
    )


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


@router.post("/api/objects/{object_id}/heartbeat", status_code=204)
def heartbeat(
    object_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    ctx.checkouts.heartbeat(db, object_id)
    return Response(status_code=204)


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
