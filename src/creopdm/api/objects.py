from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from creopdm.api.checkout import present_object
from creopdm.api.deps import get_context, get_db, load_accessible_product, require_permission, require_product_access
from creopdm.api.serializers import version_to_response
from creopdm.auth_constants import (
    PERMISSION_OBJECTS_ADD,
    PERMISSION_OBJECTS_CHECKOUT,
    PERMISSION_OBJECTS_METADATA,
    PERMISSION_OBJECTS_REMOVE,
    PERMISSION_OBJECTS_REVERT,
    PERMISSION_OBJECTS_VIEW,
)
from creopdm.context import AppContext
from creopdm.constants import ActivityAction
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import CheckoutOwnershipError, CreoPDMError, PathValidationError, ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.schemas.common import (
    AiSnapshotComparePendingRequest,
    AiSnapshotCompareRequest,
    AiSnapshotCompareResponse,
    AiSnapshotListResponse,
    AiSnapshotOutlineRequest,
    AiSnapshotOutlineResponse,
    AiSnapshotRequest,
    AiSnapshotResponse,
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
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> FileResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    product = obj.product
    try:
        path = ctx.workspaces.locate_content(product, obj)
    except PathValidationError:
        path = ctx.workspaces.materialize(
            product,
            obj,
            writable=False,
            overwrite_modified=True,
        )
    if not path.is_file():
        raise PathValidationError(
            f"Vault file not found: {obj.filename}.",
            details={"object_id": object_id},
        )
    # Browser / Open download name matches vault tip (logical), not a Creo .N cache leaf.
    extras = ctx.workspaces._cad_extensions()
    download_name = CreoFileManager.canonical_repository_name(path.name, extras)
    return _file_response(path, download_name)


@router.put("/api/objects/{object_id}/workspace-content", response_model=WorkspaceContentResponse)
async def put_workspace_content(
    object_id: str,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WorkspaceContentResponse:
    """Stage a local agent/browser file into the vault working copy (no new version)."""
    require_permission(request, ctx, PERMISSION_OBJECTS_CHECKOUT)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    product = obj.product
    user = ctx.users.get_current_user()
    ctx.checkouts.require_owned(db, obj, user)
    data = await file.read()
    filename = Path(file.filename or obj.filename).name
    path = ctx.workspaces.stage_workspace_upload(product, obj, filename, data)
    return WorkspaceContentResponse(
        object_id=object_id,
        filename=path.name,
        path=str(path),
        bytes_written=len(data),
    )


@router.post("/api/products/{product_id}/objects", response_model=ObjectResponse, status_code=201)
async def add_object(
    product_id: str,
    request: Request,
    file: UploadFile = File(...),
    comment: str | None = Form(default=None),
    relative_path: str | None = Form(default=None),
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ObjectResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_ADD)
    product = load_accessible_product(request, ctx, db, product_id)
    data = await file.read()
    filename = file.filename or "untitled"
    if not filename:
        raise ValidationAppError("A filename is required.")
    obj = ctx.objects.import_upload(
        db,
        product,
        filename=filename,
        data=data,
        relative_path=relative_path,
        comment=comment,
    )
    db.refresh(obj)
    obj = ctx.objects.get_object(db, obj.uuid)
    checkout = ctx.checkouts.active_for(db, obj.id)
    mine = checkout is not None and checkout.user_name == ctx.users.get_current_user().user_name
    ctx.workspaces.copy_into_workspace(product, obj, writable=mine, keep_local=mine)
    from creopdm.api.watch_notify import notify_product_watchers

    notify_product_watchers(
        request,
        ctx,
        db,
        product,
        action="File added",
        filenames=[obj.filename],
        object_uuid=obj.uuid,
    )
    return present_object(ctx, db, obj)


@router.post("/api/objects/batch/purge-workspace", response_model=BatchOperationResponse)
def purge_workspace_batch(
    payload: BatchObjectRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_REMOVE)
    ok: list[BatchItemResult] = []
    failed: list[BatchItemResult] = []
    for object_uuid in payload.object_ids:
        filename = object_uuid
        try:
            obj = ctx.objects.get_object(db, object_uuid)
            require_product_access(request, ctx, obj.product)
            filename = obj.filename
            _purge_and_release(ctx, db, obj, ignore_locked=False)
            ctx.activities.record(
                db,
                ActivityAction.WORKSPACE_CLEARED,
                ctx.users.get_current_user(),
                product_id=obj.product.id,
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
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_REMOVE)
    ok: list[BatchItemResult] = []
    failed: list[BatchItemResult] = []
    folder_paths = list(payload.folder_paths or [])
    requested = list(dict.fromkeys(payload.object_ids or []))
    product = None
    product_id = (payload.product_id or "").strip()
    if product_id:
        product = load_accessible_product(request, ctx, db, product_id)
    if folder_paths:
        if product is None and requested:
            found_hint = ctx.objects.get_objects(db, requested[:1])
            if found_hint:
                require_product_access(request, ctx, found_hint[0].product)
                product = found_hint[0].product
        if product is None:
            raise ValidationAppError(
                "Choose a product before removing folders.",
                details={"folder_paths": folder_paths},
            )
        for folder in folder_paths:
            requested.extend(ctx.objects.uuids_under_folder(db, product.id, folder))
        requested = list(dict.fromkeys(requested))
    found = ctx.objects.get_objects(db, requested) if requested else []
    for obj in found:
        require_product_access(request, ctx, obj.product)
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
        grouped.setdefault(obj.product_id, []).append(obj)
    for group in grouped.values():
        summaries = [{"uuid": obj.uuid, "filename": obj.filename} for obj in group]
        try:
            from creopdm.product_state import ensure_product_mutable

            # Gate before purge/release so a locked product does not drop checkouts on failure.
            ensure_product_mutable(group[0].product, action="remove files")
            ctx.workspaces.purge_local_many(group[0].product, group, ignore_locked=True)
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
    if folder_paths and product is not None and not failed:
        for folder in folder_paths:
            try:
                ctx.workspaces.remove_product_folder(product, folder, user)
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
    # Commit before the response leaves the process. FastAPI yield-deps commit after
    # the body is sent — soft reload would otherwise re-paint deleted folders/files.
    db.commit()
    if ok:
        from creopdm.api.watch_notify import notify_product_watchers

        names = [item.filename for item in ok if item.filename]
        proj = product
        if proj is None and to_remove:
            proj = to_remove[0].product
        if proj is not None and names:
            notify_product_watchers(
                request,
                ctx,
                db,
                proj,
                action="Files removed",
                filenames=names,
            )
    return BatchOperationResponse(ok=ok, failed=failed, workspace_root=str(ctx.config.workspace_root()))


@router.get("/api/objects/{object_id}", response_model=ObjectResponse)
def get_object(
    object_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ObjectResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    return present_object(ctx, db, obj)


@router.get("/api/objects/{object_id}/history", response_model=list[ObjectVersionResponse])
def object_history(
    object_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[ObjectVersionResponse]:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    versions = ctx.objects.object_history(db, object_id)
    return [item for item in (version_to_response(v) for v in versions) if item is not None]


@router.post("/api/objects/{object_id}/versions/{version_id}/revert", response_model=ObjectResponse)
def revert_object_version(
    object_id: str,
    version_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ObjectResponse:
    """Restore an older history row onto vault (new check-in) so local can rematerialize."""
    require_permission(request, ctx, PERMISSION_OBJECTS_REVERT)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    obj = ctx.checkins.revert_to_version(db, object_id, version_id)
    db.commit()
    db.refresh(obj)
    from creopdm.api.watch_notify import notify_product_watchers

    notify_product_watchers(
        request,
        ctx,
        db,
        obj.product,
        action="Version restored",
        filenames=[obj.filename],
        object_uuid=obj.uuid,
    )
    return present_object(ctx, db, obj)


@router.get("/api/objects/{object_id}/creo-metadata", response_model=CreoMetadataResponse)
def get_creo_metadata(
    object_id: str,
    request: Request,
    version: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> CreoMetadataResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    return ctx.metadata.get(db, object_id, version)


@router.post("/api/objects/{object_id}/creo-metadata", response_model=CreoMetadataResponse)
def post_creo_metadata(
    object_id: str,
    payload: CreoMetadataRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> CreoMetadataResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_METADATA)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
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
    model_type = ""
    model_role = ""
    skeleton_filename = ""
    if isinstance(result.identity, dict):
        ident = str(result.identity.get("file_name") or result.identity.get("full_name") or "")
        model_type = str(result.identity.get("model_type") or "")
        model_role = str(result.identity.get("model_role") or "")
        skeleton_filename = str(result.identity.get("skeleton_filename") or "")
    logger.info(
        "Saved Creo metadata for %s (%s): type=%s role=%s skel=%s params=%s materials=%s%s deps=%s bom=%s mass=%s units=%s features=%s",
        ident or object_id,
        object_id[:8],
        model_type or "-",
        model_role or "-",
        skeleton_filename or "-",
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


@router.get("/api/objects/{object_id}/ai-snapshot", response_model=AiSnapshotResponse)
def get_ai_snapshot(
    object_id: str,
    request: Request,
    version: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> AiSnapshotResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    return ctx.ai_snapshots.get(db, object_id, version)


@router.get("/api/objects/{object_id}/ai-snapshots", response_model=AiSnapshotListResponse)
def list_ai_snapshots(
    object_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> AiSnapshotListResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    return ctx.ai_snapshots.list_for_object(db, object_id)


@router.post("/api/objects/{object_id}/ai-snapshot", response_model=AiSnapshotResponse)
def post_ai_snapshot(
    object_id: str,
    payload: AiSnapshotRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> AiSnapshotResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_METADATA)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    result = ctx.ai_snapshots.save(db, object_id, payload)
    logger.info(
        "Saved AI snapshot for %s (%s): rev=%s status=%s schema=%s",
        obj.filename or object_id,
        object_id[:8],
        result.display_revision or "-",
        result.capture_status or "-",
        result.schema_version,
    )
    return result


@router.post(
    "/api/objects/{object_id}/ai-snapshot/outline",
    response_model=AiSnapshotOutlineResponse,
)
def outline_ai_snapshot(
    object_id: str,
    payload: AiSnapshotOutlineRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> AiSnapshotOutlineResponse:
    """Format a gathered snapshot as Compare outline text (no save, no Ollama)."""
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    outline, display_revision = ctx.ai_snapshots.outline_from_snapshot(
        payload.snapshot,
        display_revision=payload.display_revision,
    )
    return AiSnapshotOutlineResponse(outline=outline, display_revision=display_revision)


@router.post(
    "/api/objects/{object_id}/ai-snapshot/compare",
    response_model=AiSnapshotCompareResponse,
)
def compare_ai_snapshots(
    object_id: str,
    payload: AiSnapshotCompareRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> AiSnapshotCompareResponse:
    """Ask the configured Ollama model to summarize older → newer snapshot changes."""
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    result = ctx.ai_snapshots.compare_with_ollama(
        db,
        object_id,
        payload.older_version_id,
        payload.newer_version_id,
        ctx.settings,
    )
    logger.info(
        "AI snapshot compare for %s (%s): %s → %s model=%s chars=%s",
        obj.filename or object_id,
        object_id[:8],
        result.older_display_revision or "-",
        result.newer_display_revision or "-",
        result.model or "-",
        len(result.summary or ""),
    )
    return result


@router.post(
    "/api/objects/{object_id}/ai-snapshot/compare-pending",
    response_model=AiSnapshotCompareResponse,
)
def compare_pending_ai_snapshot(
    object_id: str,
    payload: AiSnapshotComparePendingRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> AiSnapshotCompareResponse:
    """Compare tip snapshot to a gathered not-yet-checked-in model snapshot (check-in comment)."""
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    result = ctx.ai_snapshots.compare_pending_with_ollama(
        db,
        object_id,
        payload.newer_snapshot,
        ctx.settings,
        older_version_id=payload.older_version_id,
        newer_display_revision=payload.newer_display_revision,
    )
    logger.info(
        "AI pending snapshot compare for %s (%s): %s → %s model=%s chars=%s",
        obj.filename or object_id,
        object_id[:8],
        result.older_display_revision or "-",
        result.newer_display_revision or "-",
        result.model or "-",
        len(result.summary or ""),
    )
    return result


@router.get("/api/objects/{object_id}/where-used", response_model=WhereUsedResponse)
def object_where_used(
    object_id: str,
    request: Request,
    debug: bool = False,
    vault_scan: bool = True,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WhereUsedResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
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
        ctx.workspaces.purge_local(obj.product, obj)
    except PathValidationError:
        if not ignore_locked:
            raise
    ctx.checkouts.release_mine(db, obj)


@router.post("/api/objects/{object_id}/purge-workspace", status_code=204)
def purge_workspace(
    object_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    require_permission(request, ctx, PERMISSION_OBJECTS_REMOVE)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    _purge_and_release(ctx, db, obj, ignore_locked=False)
    ctx.activities.record(
        db,
        ActivityAction.WORKSPACE_CLEARED,
        ctx.users.get_current_user(),
        product_id=obj.product.id,
        object_id=obj.id,
        details={"filename": obj.filename},
    )
    return Response(status_code=204)


@router.delete("/api/objects/{object_id}", status_code=204)
def delete_object(
    object_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    require_permission(request, ctx, PERMISSION_OBJECTS_REMOVE)
    obj = ctx.objects.get_object(db, object_id)
    require_product_access(request, ctx, obj.product)
    _purge_and_release(ctx, db, obj, ignore_locked=True)
    ctx.objects.delete_object(db, object_id)
    # See batch/remove — commit before 204 so a follow-up soft reload sees the delete.
    db.commit()
    return Response(status_code=204)
