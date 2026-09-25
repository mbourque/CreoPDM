from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from creopdm.api.checkout import present_object
from creopdm.api.deps import get_context, get_db
from creopdm.api.serializers import version_to_response
from creopdm.context import AppContext
from creopdm.constants import ActivityAction
from creopdm.exceptions import CheckoutOwnershipError, CreoPDMError, PathValidationError, ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.schemas.common import (
    BatchItemResult,
    BatchObjectRequest,
    BatchRemoveRequest,
    BatchOperationResponse,
    CreoMetadataRequest,
    CreoMetadataResponse,
    ObjectResponse,
    ObjectVersionResponse,
    WhereUsedResponse,
    WorkspaceContentResponse,
)

router = APIRouter()
logger = get_logger("metadata-api")


def _file_response(path, filename: str) -> FileResponse:
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="attachment",
        headers={"Content-Disposition": disposition},
    )


@router.get("/api/objects/{object_id}/content")
def object_content(
    object_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> FileResponse:
    obj = ctx.objects.get_object(db, object_id)
    project = obj.project
    try:
        path = ctx.workspaces.locate_content(project, obj)
    except PathValidationError:
        path = ctx.workspaces.materialize(
            project,
            obj,
            writable=False,
            overwrite_modified=True,
        )
    if not path.is_file():
        raise PathValidationError(
            f"Vault file not found: {obj.filename}.",
            details={"object_id": object_id},
        )
    return _file_response(path, path.name)


@router.put("/api/objects/{object_id}/workspace-content", response_model=WorkspaceContentResponse)
async def put_workspace_content(
    object_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WorkspaceContentResponse:
    """Stage a local agent/browser file into the vault working copy (no new version)."""
    obj = ctx.objects.get_object(db, object_id)
    project = obj.project
    user = ctx.users.get_current_user()
    ctx.checkouts.require_owned(db, obj, user)
    data = await file.read()
    filename = Path(file.filename or obj.filename).name
    path = ctx.workspaces.stage_workspace_upload(project, obj, filename, data)
    return WorkspaceContentResponse(
        object_id=object_id,
        filename=path.name,
        path=str(path),
        bytes_written=len(data),
    )


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
    payload: BatchRemoveRequest,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    ok: list[BatchItemResult] = []
    failed: list[BatchItemResult] = []
    folder_paths = list(payload.folder_paths or [])
    requested = list(dict.fromkeys(payload.object_ids or []))
    project = None
    project_id = (payload.project_id or "").strip()
    if project_id:
        project = ctx.projects.get_project(db, project_id)
    if folder_paths:
        if project is None and requested:
            found_hint = ctx.objects.get_objects(db, requested[:1])
            if found_hint:
                project = found_hint[0].project
        if project is None:
            raise ValidationAppError(
                "Choose a project before removing folders.",
                details={"folder_paths": folder_paths},
            )
        for folder in folder_paths:
            requested.extend(ctx.objects.uuids_under_folder(db, project.id, folder))
        requested = list(dict.fromkeys(requested))
    found = ctx.objects.get_objects(db, requested) if requested else []
    by_uuid = {obj.uuid: obj for obj in found}
    checkouts = ctx.checkouts.active_map(db, [obj.id for obj in found]) if found else {}
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
    # Drop empty Create-folder trees (.gitkeep) and leftover vault dirs for selected folders.
    if folder_paths and project is not None and not failed:
        for folder in folder_paths:
            try:
                ctx.workspaces.remove_project_folder(project, folder, user)
                ok.append(
                    BatchItemResult(
                        uuid="",
                        filename=folder,
                        status="folder_removed",
                    )
                )
            except CreoPDMError as exc:
                failed.append(
                    BatchItemResult(
                        uuid="",
                        filename=folder,
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


@router.get("/api/objects/{object_id}/creo-metadata", response_model=CreoMetadataResponse)
def get_creo_metadata(
    object_id: str,
    version: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> CreoMetadataResponse:
    return ctx.metadata.get(db, object_id, version)


@router.post("/api/objects/{object_id}/creo-metadata", response_model=CreoMetadataResponse)
def post_creo_metadata(
    object_id: str,
    payload: CreoMetadataRequest,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> CreoMetadataResponse:
    result = ctx.metadata.save(db, object_id, payload)
    params = len(result.parameters or [])
    mats = result.materials if isinstance(result.materials, dict) else {}
    mat_current = str((mats or {}).get("current") or "") or None
    mat_names = len((mats or {}).get("names") or []) if isinstance(mats, dict) else 0
    deps = len(result.dependencies or [])
    bom = result.bom
    bom_n = len(bom) if isinstance(bom, list) else (1 if bom else 0)
    units_ok = False
    if isinstance(result.units, dict):
        units_ok = any(str(result.units.get(k) or "").strip() for k in ("system_name", "length", "mass", "time", "temperature"))
    ident = ""
    if isinstance(result.identity, dict):
        ident = str(result.identity.get("file_name") or result.identity.get("full_name") or "")
    logger.info(
        "Saved Creo metadata for %s (%s): params=%s materials=%s%s deps=%s bom=%s mass=%s units=%s features=%s",
        ident or object_id,
        object_id[:8],
        params,
        mat_current or "none",
        f"/{mat_names} listed" if mat_names else "",
        deps,
        bom_n,
        "yes" if result.mass else "no",
        "yes" if units_ok else "no",
        len(result.features or []) if isinstance(result.features, list) else 0,
    )
    return result


@router.get("/api/objects/{object_id}/where-used", response_model=WhereUsedResponse)
def object_where_used(
    object_id: str,
    debug: bool = False,
    vault_scan: bool = True,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WhereUsedResponse:
    return ctx.metadata.where_used(db, object_id, debug=debug, vault_scan=vault_scan)


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
