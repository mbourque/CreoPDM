from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from sqlalchemy.orm import Session

from creopdm.api.checkout import present_object
from creopdm.api.deps import get_context, get_db
from creopdm.api.serializers import version_to_response
from creopdm.context import AppContext
from creopdm.constants import ActivityAction
from creopdm.exceptions import CheckoutOwnershipError, CreoPDMError, PathValidationError, ValidationAppError
from creopdm.schemas.common import (
    BatchItemResult,
    BatchObjectRequest,
    BatchOperationResponse,
    ObjectResponse,
    ObjectVersionResponse,
)

router = APIRouter()


@router.post("/api/projects/{project_id}/objects", response_model=ObjectResponse, status_code=201)
async def add_object(
    project_id: str,
    file: UploadFile = File(...),
    comment: str | None = Form(default=None),
    relative_path: str | None = Form(default=None),
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ObjectResponse:
    project = ctx.projects.get_project(db, project_id)
    data = await file.read()
    filename = file.filename or "untitled"
    if not filename:
        raise ValidationAppError("A filename is required.")
    obj = ctx.objects.import_upload(
        db,
        project,
        filename=filename,
        data=data,
        relative_path=relative_path,
        comment=comment,
    )
    db.refresh(obj)
    obj = ctx.objects.get_object(db, obj.uuid)
    checkout = ctx.checkouts.active_for(db, obj.id)
    mine = checkout is not None and checkout.user_name == ctx.users.get_current_user().user_name
    ctx.workspaces.copy_into_workspace(project, obj, writable=mine, keep_local=mine)
    return present_object(ctx, db, obj)


@router.post("/api/objects/batch/purge-workspace", response_model=BatchOperationResponse)
def purge_workspace_batch(
    payload: BatchObjectRequest,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    ok: list[BatchItemResult] = []
    failed: list[BatchItemResult] = []
    for object_uuid in payload.object_ids:
        filename = object_uuid
        try:
            obj = ctx.objects.get_object(db, object_uuid)
            filename = obj.filename
            _purge_and_release(ctx, db, obj, ignore_locked=False)
            ctx.activities.record(
                db,
                ActivityAction.WORKSPACE_CLEARED,
                ctx.users.get_current_user(),
                project_id=obj.project.id,
                object_id=obj.id,
                details={"filename": obj.filename},
            )
            ok.append(BatchItemResult(uuid=object_uuid, filename=filename, status="purged"))
        except CreoPDMError as exc:
            failed.append(
                BatchItemResult(uuid=object_uuid, filename=filename, code=exc.code, message=exc.message)
            )
    return BatchOperationResponse(ok=ok, failed=failed, workspace_root=str(ctx.config.workspace_root()))


@router.post("/api/objects/batch/remove", response_model=BatchOperationResponse)
def remove_batch(
    payload: BatchObjectRequest,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    ok: list[BatchItemResult] = []
    failed: list[BatchItemResult] = []
    requested = list(dict.fromkeys(payload.object_ids))
    found = ctx.objects.get_objects(db, requested)
    by_uuid = {obj.uuid: obj for obj in found}
    checkouts = ctx.checkouts.active_map(db, [obj.id for obj in found])
    user = ctx.users.get_current_user()
    to_remove: list = []
    for object_uuid in requested:
        obj = by_uuid.get(object_uuid)
        if obj is None:
            failed.append(
                BatchItemResult(
                    uuid=object_uuid,
                    filename=object_uuid,
                    code="OBJECT_NOT_FOUND",
                    message="Object not found.",
                )
            )
            continue
        checkout = checkouts.get(obj.id)
        if checkout is not None and checkout.user_name != user.user_name:
            failed.append(
                BatchItemResult(
                    uuid=object_uuid,
                    filename=obj.filename,
                    code="CHECKOUT_OWNERSHIP",
                    message=f"{obj.filename} is checked out by {checkout.user_name}.",
                )
            )
            continue
        to_remove.append(obj)
    grouped: dict[int, list] = {}
    for obj in to_remove:
        grouped.setdefault(obj.project_id, []).append(obj)
    for group in grouped.values():
        summaries = [{"uuid": obj.uuid, "filename": obj.filename} for obj in group]
        try:
            ctx.workspaces.purge_local_many(group[0].project, group, ignore_locked=True)
            ctx.checkouts.release_mine_many(db, group)
            ctx.objects.delete_objects(db, group)
            for item in summaries:
                ok.append(
                    BatchItemResult(uuid=item["uuid"], filename=item["filename"], status="removed")
                )
        except CreoPDMError as exc:
            for item in summaries:
                failed.append(
                    BatchItemResult(
                        uuid=item["uuid"],
                        filename=item["filename"],
                        code=exc.code,
                        message=exc.message,
                    )
                )
    return BatchOperationResponse(ok=ok, failed=failed, workspace_root=str(ctx.config.workspace_root()))


@router.get("/api/objects/{object_id}", response_model=ObjectResponse)
def get_object(
    object_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ObjectResponse:
    obj = ctx.objects.get_object(db, object_id)
    return present_object(ctx, db, obj)


@router.get("/api/objects/{object_id}/history", response_model=list[ObjectVersionResponse])
def object_history(
    object_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[ObjectVersionResponse]:
    versions = ctx.objects.object_history(db, object_id)
    return [item for item in (version_to_response(v) for v in versions) if item is not None]


def _assert_can_remove(ctx: AppContext, db: Session, obj) -> None:
    user = ctx.users.get_current_user()
    checkout = ctx.checkouts.active_for(db, obj.id)
    if checkout is None:
        return
    if checkout.user_name != user.user_name:
        raise CheckoutOwnershipError(
            f"{obj.filename} is checked out by {checkout.user_name}.",
            details={"user": checkout.user_name, "machine": checkout.machine_name},
        )


def _purge_and_release(ctx: AppContext, db: Session, obj, *, ignore_locked: bool) -> None:
    _assert_can_remove(ctx, db, obj)
    try:
        ctx.workspaces.purge_local(obj.project, obj)
    except PathValidationError:
        if not ignore_locked:
            raise
    ctx.checkouts.release_mine(db, obj)


@router.post("/api/objects/{object_id}/purge-workspace", status_code=204)
def purge_workspace(
    object_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    obj = ctx.objects.get_object(db, object_id)
    _purge_and_release(ctx, db, obj, ignore_locked=False)
    ctx.activities.record(
        db,
        ActivityAction.WORKSPACE_CLEARED,
        ctx.users.get_current_user(),
        project_id=obj.project.id,
        object_id=obj.id,
        details={"filename": obj.filename},
    )
    return Response(status_code=204)


@router.delete("/api/objects/{object_id}", status_code=204)
def delete_object(
    object_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    obj = ctx.objects.get_object(db, object_id)
    _purge_and_release(ctx, db, obj, ignore_locked=True)
    ctx.objects.delete_object(db, object_id)
    return Response(status_code=204)
