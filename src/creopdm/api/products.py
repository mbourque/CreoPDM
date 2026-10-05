from __future__ import annotations

import mimetypes
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from creopdm.api.checkout import present_object, present_objects
from creopdm.api.deps import (
    accessible_products,
    get_context,
    get_db,
    load_accessible_product,
    load_accessible_product_for_delete,
    require_any_permission,
    require_permission,
)
from creopdm.api.serializers import product_to_response
from creopdm.auth_constants import (
    PERMISSION_OBJECTS_ADD,
    PERMISSION_OBJECTS_CHECKIN,
    PERMISSION_OBJECTS_EXPORT,
    PERMISSION_OBJECTS_METADATA,
    PERMISSION_OBJECTS_REMOVE,
    PERMISSION_OBJECTS_VIEW,
    PERMISSION_PRODUCTS_CREATE,
    PERMISSION_PRODUCTS_DELETE,
    PERMISSION_PRODUCTS_EDIT,
    PERMISSION_PRODUCTS_EXPORT,
    PERMISSION_PRODUCTS_VIEW,
    PERMISSION_UTILITIES_REBUILD_PRODUCT,
)
from creopdm.context import AppContext
from creopdm.constants import ActivityAction
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import CreoPDMError, PathValidationError, ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.schemas.common import (
    BatchItemResult,
    BatchOperationResponse,
    CreateFolderRequest,
    CreateFolderResponse,
    ForgetProductRequest,
    ForgetProductResponse,
    CheckinPreviewResponse,
    ImportLocalRequest,
    ObjectResponse,
    ProductCreateRequest,
    ProductExportRequest,
    ProductResponse,
    ProductStatusResponse,
    ProductUpdateRequest,
    ProductWatchResponse,
    PurgeFloorsResponse,
    PurgeFloorItem,
    PurgeWorkspacePathsRequest,
    QueueCheckinRequest,
    WhereUsedIndexJobResponse,
    ZipImportJobResponse,
    WorkspaceContentResponse,
    WorkspacePickerResponse,
    WorkspaceWatchResponse,
)
from creopdm.services.export_zip import build_export_zip, export_zip_basename
from creopdm.utils.launch import open_windows_folder
from creopdm.utils.native_dialog import pick_files, pick_folder

router = APIRouter()
logger = get_logger("products")


@router.get("/api/products", response_model=list[ProductResponse])
def list_products(
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[ProductResponse]:
    require_permission(request, ctx, PERMISSION_PRODUCTS_VIEW)
    return [product_to_response(product) for product in accessible_products(request, ctx, db)]


@router.post("/api/products", response_model=ProductResponse, status_code=201)
def create_product(
    payload: ProductCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ProductResponse:
    require_permission(request, ctx, PERMISSION_PRODUCTS_CREATE)
    product = ctx.products.create_product(
        db,
        name=payload.name,
        number=payload.number,
        description=payload.description,
        vault_folder=payload.vault_folder,
    )
    user = getattr(request.state, "auth_user", None)
    if user is not None and ctx.auth_enabled:
        ctx.user_accounts.grant_product_access(db, user, product)
    return product_to_response(product)


@router.get("/api/products/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ProductResponse:
    require_permission(request, ctx, PERMISSION_PRODUCTS_VIEW)
    return product_to_response(load_accessible_product(request, ctx, db, product_id))


@router.get("/api/products/{product_id}/watch", response_model=ProductWatchResponse)
def get_product_watch(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ProductWatchResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    email_on = bool(ctx.settings.email.enabled)
    auth_user = getattr(request.state, "auth_user", None)
    try:
        can_watch, reason = ctx.product_watches.watch_eligibility(auth_user, email_enabled=email_on)
        watching = False
        if auth_user is not None:
            watching = ctx.product_watches.is_watching(db, int(auth_user.id), int(product.id))
        return ProductWatchResponse(
            watching=watching,
            can_watch=can_watch,
            email_notifications_enabled=email_on,
            reason=None if can_watch else reason,
        )
    except Exception:
        from creopdm.logging_setup import get_logger

        get_logger("products").exception("get_product_watch failed")
        return ProductWatchResponse(
            watching=False,
            can_watch=False,
            email_notifications_enabled=email_on,
            reason="Product watch is temporarily unavailable.",
        )


@router.post("/api/products/{product_id}/watch", response_model=ProductWatchResponse)
def subscribe_product_watch(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ProductWatchResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    auth_user = getattr(request.state, "auth_user", None)
    if auth_user is None:
        raise ValidationAppError("Sign in to watch a product.")
    email_on = bool(ctx.settings.email.enabled)
    ctx.product_watches.subscribe(db, auth_user, product, email_enabled=email_on)
    db.commit()
    # Re-read for this user only — never trust a hard-coded watching=True.
    watching = ctx.product_watches.is_watching(db, int(auth_user.id), int(product.id))
    can_watch, reason = ctx.product_watches.watch_eligibility(auth_user, email_enabled=email_on)
    return ProductWatchResponse(
        watching=watching,
        can_watch=can_watch,
        email_notifications_enabled=email_on,
        reason=None if can_watch else reason,
    )


@router.delete("/api/products/{product_id}/watch", response_model=ProductWatchResponse)
def unsubscribe_product_watch(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ProductWatchResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    auth_user = getattr(request.state, "auth_user", None)
    if auth_user is None:
        raise ValidationAppError("Sign in to manage product watches.")
    email_on = bool(ctx.settings.email.enabled)
    ctx.product_watches.unsubscribe(db, auth_user, product)
    db.commit()
    watching = ctx.product_watches.is_watching(db, int(auth_user.id), int(product.id))
    can_watch, reason = ctx.product_watches.watch_eligibility(auth_user, email_enabled=email_on)
    return ProductWatchResponse(
        watching=watching,
        can_watch=can_watch,
        email_notifications_enabled=email_on,
        reason=None if can_watch else reason,
    )


@router.patch("/api/products/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: str,
    payload: ProductUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ProductResponse:
    require_permission(request, ctx, PERMISSION_PRODUCTS_EDIT)
    product = load_accessible_product(request, ctx, db, product_id)
    from creopdm.product_state import ensure_product_mutable

    ensure_product_mutable(product, action="rename this product")
    product = ctx.products.update_product(
        db,
        product_id,
        name=payload.name,
        number=payload.number,
        description=payload.description,
    )
    from creopdm.api.watch_notify import notify_product_watchers

    notify_product_watchers(
        request,
        ctx,
        db,
        product,
        action="Product updated",
        filenames=[],
    )
    return product_to_response(product)


@router.delete("/api/products/{product_id}", status_code=204)
def delete_product(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> None:
    require_permission(request, ctx, PERMISSION_PRODUCTS_DELETE)
    load_accessible_product_for_delete(request, ctx, db, product_id)
    ctx.products.delete_product(db, product_id)


@router.post("/api/products/{product_id}/forget", response_model=ForgetProductResponse)
def forget_product(
    product_id: str,
    payload: ForgetProductRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ForgetProductResponse:
    require_permission(request, ctx, PERMISSION_PRODUCTS_DELETE)
    product = load_accessible_product_for_delete(request, ctx, db, product_id)
    # Stop background Where Used so Delete is not stuck behind vault/DB scans.
    ctx.where_used_index.cancel(product_id)
    workspace = ctx.workspaces.vault_for(product)
    result = ctx.products.forget_product(
        db,
        product_id,
        confirm_name=payload.confirm_name,
        workspace_path=workspace,
    )
    if ctx.config.settings.ui.last_product_uuid == product_id:
        ctx.config.remember_product(None)
    ctx.config.forget_product_view(product_id)
    return ForgetProductResponse.model_validate(result)


@router.get("/api/products/{product_id}/objects", response_model=list[ObjectResponse])
def list_objects(
    product_id: str,
    request: Request,
    q: str | None = None,
    object_type: str | None = None,
    lifecycle_state: str | None = None,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[ObjectResponse]:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    try:
        ctx.objects.migrate_numbered_vault_tips(
            db, product, vault=ctx.workspaces.ensure_vault(product)
        )
    except Exception:
        # Migration is best-effort; listing must still work.
        from creopdm.logging_setup import get_logger

        get_logger("products").exception(
            "Vault-name migrate failed for product %s", product.uuid
        )
    objects = ctx.objects.search(
        db,
        product,
        query=q,
        object_type=object_type,
        lifecycle_state=lifecycle_state,
    )
    return present_objects(ctx, db, objects)


@router.post("/api/products/{product_id}/export")
def export_product_zip(
    product_id: str,
    payload: ProductExportRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> FileResponse:
    """Zip vault tip files for download. Does not checkout or lock anything."""
    product = load_accessible_product(request, ctx, db, product_id)
    selected = bool(payload.object_ids or payload.folder_paths)
    if selected:
        require_permission(request, ctx, PERMISSION_OBJECTS_EXPORT)
        requested = list(payload.object_ids)
        for folder in payload.folder_paths:
            requested.extend(ctx.objects.uuids_under_folder(db, product.id, folder))
        requested = list(dict.fromkeys(requested))
        if not requested:
            raise ValidationAppError("Nothing to export for that selection.")
        objects = ctx.objects.get_objects(db, requested)
        by_uuid = {obj.uuid: obj for obj in objects}
        ordered = [by_uuid[uid] for uid in requested if uid in by_uuid]
        missing = [uid for uid in requested if uid not in by_uuid]
        if missing and not ordered:
            raise ValidationAppError("Nothing to export for that selection.")
        for obj in ordered:
            if obj.product_id != product.id:
                raise ValidationAppError("All exported files must belong to this product.")
    else:
        require_permission(request, ctx, PERMISSION_PRODUCTS_EXPORT)
        ordered = ctx.objects.list_objects(db, product.id)
    zip_path, count = build_export_zip(ctx.workspaces, product, ordered)
    background_tasks.add_task(lambda path=zip_path: path.unlink(missing_ok=True))
    filename = export_zip_basename(product, selected=selected)
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=filename,
        content_disposition_type="attachment",
        headers={
            "Content-Disposition": disposition,
            "X-CreoPDM-File-Count": str(count),
            "X-CreoPDM-Export-Name": quote(filename),
        },
    )


@router.get("/api/products/{product_id}/status", response_model=ProductStatusResponse)
def product_status(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ProductStatusResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    load_accessible_product(request, ctx, db, product_id)
    counts = ctx.products.product_status(db, product_id)
    return ProductStatusResponse.model_validate(counts)


@router.get("/api/products/{product_id}/workspace-watch", response_model=WorkspaceWatchResponse)
def workspace_watch(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WorkspaceWatchResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    known = ctx.objects.list_path_index(db, product.id)
    return WorkspaceWatchResponse.model_validate(ctx.workspaces.watch_stamp(product, known))


@router.get("/api/products/{product_id}/checkin-preview", response_model=CheckinPreviewResponse)
def product_checkin_preview(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> CheckinPreviewResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    return CheckinPreviewResponse.model_validate(ctx.checkins.preview_queue(db, product))


@router.get("/api/products/{product_id}/checkin-queue")
def product_checkin_queue_view(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> dict:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    objects = ctx.objects.list_objects(db, product.id)
    return ctx.workspaces.product_checkin_queue(product, objects)


@router.get("/api/products/{product_id}/checkouts", response_model=list[ObjectResponse])
def list_product_checkouts(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[ObjectResponse]:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    objects = ctx.checkouts.list_for_product(db, product.id)
    return present_objects(ctx, db, objects)


@router.post("/api/products/{product_id}/checkin-queue", response_model=BatchOperationResponse)
def product_checkin_queue(
    product_id: str,
    payload: QueueCheckinRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    object_ids = [item for item in (payload.object_ids or []) if str(item or "").strip()]
    add_paths = [
        str(item).replace("\\", "/").strip()
        for item in (payload.add_relative_paths or [])
        if str(item or "").strip()
    ]
    # Check-in dirty tips needs objects.checkin. Add-only New files may use objects.add.
    if object_ids:
        require_permission(request, ctx, PERMISSION_OBJECTS_CHECKIN)
    elif add_paths:
        require_any_permission(
            request, ctx, PERMISSION_OBJECTS_ADD, PERMISSION_OBJECTS_CHECKIN
        )
    else:
        require_permission(request, ctx, PERMISSION_OBJECTS_CHECKIN)
    product = load_accessible_product(request, ctx, db, product_id)
    result = ctx.checkins.checkin_queue(
        db,
        product,
        payload.comment,
        object_ids,
        add_paths,
    )
    return BatchOperationResponse.model_validate(
        {**result, "workspace_root": str(ctx.workspaces.vault_for(product))}
    )


@router.post(
    "/api/products/{product_id}/rebuild-where-used",
    response_model=WhereUsedIndexJobResponse,
)
def start_rebuild_where_used(
    product_id: str,
    request: Request,
    ctx: AppContext = Depends(get_context),
) -> WhereUsedIndexJobResponse:
    """Start background vault → Dependency indexing (no-op if already running).

    Does not touch the DB here so a busy indexer cannot block Start.
    """
    require_any_permission(
        request, ctx, PERMISSION_OBJECTS_METADATA, PERMISSION_UTILITIES_REBUILD_PRODUCT
    )
    status = ctx.where_used_index.start(product_id)
    return _where_used_job_response(status)


@router.get(
    "/api/products/{product_id}/rebuild-where-used",
    response_model=WhereUsedIndexJobResponse,
)
def rebuild_where_used_status(
    product_id: str,
    request: Request,
    ctx: AppContext = Depends(get_context),
) -> WhereUsedIndexJobResponse:
    """Poll background Where Used index job status (memory only — never waits on SQLite)."""
    require_any_permission(
        request, ctx, PERMISSION_OBJECTS_VIEW, PERMISSION_UTILITIES_REBUILD_PRODUCT
    )
    return _where_used_job_response(ctx.where_used_index.get(product_id))


@router.delete(
    "/api/products/{product_id}/rebuild-where-used",
    response_model=WhereUsedIndexJobResponse,
)
def cancel_rebuild_where_used(
    product_id: str,
    request: Request,
    ctx: AppContext = Depends(get_context),
) -> WhereUsedIndexJobResponse:
    """Cancel a running Where Used index so the busy overlay can clear cleanly."""
    require_any_permission(
        request, ctx, PERMISSION_OBJECTS_METADATA, PERMISSION_UTILITIES_REBUILD_PRODUCT
    )
    ctx.where_used_index.cancel(product_id)
    return _where_used_job_response(ctx.where_used_index.get(product_id))


def _where_used_job_response(status) -> WhereUsedIndexJobResponse:
    return WhereUsedIndexJobResponse(
        product_id=status.product_id,
        state=status.state,
        parents_total=status.parents_total,
        parents_done=status.parents_done,
        edges_added=status.edges_added,
        edges_existing=status.edges_existing,
        parents_missing_vault=status.parents_missing_vault,
        error=status.error,
        done=status.state in {"done", "error", "cancelled"},
        started_at=status.started_at,
        finished_at=status.finished_at,
    )


@router.post(
    "/api/products/{product_id}/workspace/purge-paths",
    response_model=BatchOperationResponse,
)
def purge_workspace_paths(
    product_id: str,
    payload: PurgeWorkspacePathsRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_REMOVE)
    product = load_accessible_product(request, ctx, db, product_id)
    objects = ctx.objects.list_objects(db, product.id)
    ok: list[BatchItemResult] = []
    failed: list[BatchItemResult] = []
    try:
        removed = ctx.workspaces.purge_untracked_paths(product, payload.relative_paths, objects)
        user = ctx.users.get_current_user()
        for item in removed:
            ctx.activities.record(
                db,
                ActivityAction.WORKSPACE_CLEARED,
                user,
                product_id=product.id,
                details={"filename": item["filename"], "relative_path": item["relative_path"]},
            )
            ok.append(
                BatchItemResult(
                    uuid=item["relative_path"],
                    filename=item["filename"],
                    status="purged",
                    path=item["relative_path"],
                )
            )
    except CreoPDMError as exc:
        for relative in payload.relative_paths:
            failed.append(
                BatchItemResult(
                    uuid=relative,
                    filename=Path(relative).name,
                    code=exc.code,
                    message=exc.message,
                )
            )
    return BatchOperationResponse(
        ok=ok,
        failed=failed,
        workspace_root=str(ctx.workspaces.vault_for(product)),
    )


@router.get(
    "/api/products/{product_id}/workspace/purge-floors",
    response_model=PurgeFloorsResponse,
)
def workspace_purge_floors(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> PurgeFloorsResponse:
    """Vault save floors for Purge workspace (local agent deletes only older cache saves)."""
    from creopdm.utils.classify import extra_cad_set

    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    purgeable = ctx.config.purgeable_cad_extensions()
    allowed = extra_cad_set(purgeable)
    floors: list[PurgeFloorItem] = []
    for obj in ctx.objects.list_objects(db, product.id):
        logical_name = CreoFileManager.logical_filename(obj.filename, purgeable)
        if Path(logical_name).suffix.lower() not in allowed:
            continue
        min_keep = CreoFileManager.purge_floor_for_vault_tip(obj.filename, purgeable)
        if min_keep <= 0:
            continue
        logical_path = CreoFileManager.logical_repo_path(obj.relative_path, purgeable)
        floors.append(
            PurgeFloorItem(
                logical_path=logical_path,
                min_keep=min_keep,
                filename=obj.filename,
                object_id=obj.uuid,
            )
        )
    floors.sort(key=lambda item: item.logical_path.lower())
    return PurgeFloorsResponse(floors=floors, model_extensions=list(purgeable))


def _picker_filters(ctx: AppContext) -> dict[str, list[str]]:
    return {
        "ignore_patterns": list(ctx.config.ignore_patterns()),
        # Used by the Add dialog to omit older .ext.N saves (Settings → Purgeable).
        "import_extensions": list(ctx.config.purgeable_cad_extensions()),
    }


@router.get("/api/products/{product_id}/workspace/add-folder", response_model=WorkspacePickerResponse)
def workspace_add_folder(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WorkspacePickerResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    start = ctx.products.preferred_import_directory(product)
    start.mkdir(parents=True, exist_ok=True)
    filters = _picker_filters(ctx)
    return WorkspacePickerResponse(
        workspace_root=str(ctx.workspaces.vault_for(product)),
        initial_directory=str(start),
        ignore_patterns=filters["ignore_patterns"],
        import_extensions=filters["import_extensions"],
    )


@router.post("/api/products/{product_id}/workspace/choose-files", response_model=WorkspacePickerResponse)
def choose_workspace_files(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WorkspacePickerResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_ADD)
    product = load_accessible_product(request, ctx, db, product_id)
    start = ctx.products.preferred_import_directory(product)
    start.mkdir(parents=True, exist_ok=True)
    picked = pick_files(start, title="Add files to the product")
    ignored = ctx.config.ignore_patterns()
    extras = ctx.config.purgeable_cad_extensions()
    ignored_count = 0
    present: list[Path] = []
    for path in picked:
        if CreoFileManager.is_ignored(path.name, ignored):
            ignored_count += 1
            continue
        if path.is_file():
            present.append(path)
    selected = CreoFileManager.filter_to_latest_saves(
        present,
        extras,
        scan_disk_siblings=True,
    )
    return WorkspacePickerResponse(
        workspace_root=str(ctx.workspaces.vault_for(product)),
        initial_directory=str(start),
        selected=[str(path) for path in selected],
        ignored_count=ignored_count,
    )


@router.post("/api/products/{product_id}/workspace/choose-folder", response_model=WorkspacePickerResponse)
def choose_workspace_folder(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WorkspacePickerResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_ADD)
    product = load_accessible_product(request, ctx, db, product_id)
    start = ctx.products.preferred_import_directory(product)
    start.mkdir(parents=True, exist_ok=True)
    chosen = pick_folder(start, title="Add a folder to the product")
    if chosen is None:
        logger.info("Folder picker cancelled")
        return WorkspacePickerResponse(
            workspace_root=str(ctx.workspaces.vault_for(product)),
            initial_directory=str(start),
            cancelled=True,
        )
    logger.info("Chose folder %s", chosen)
    return WorkspacePickerResponse(
        workspace_root=str(ctx.workspaces.vault_for(product)),
        initial_directory=str(chosen),
        selected=[],
        folder=str(chosen),
    )


@router.post("/api/products/{product_id}/workspace/open", status_code=204)
def open_workspace_folder(
    product_id: str,
    request: Request,
    folder: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    opened = ctx.workspaces.explorer_directory(product, folder or "")
    try:
        open_windows_folder(opened)
    except OSError as exc:
        raise PathValidationError(
            "Could not open the vault folder in Explorer.",
            details={"path": str(opened)},
        ) from exc
    return Response(status_code=204)


@router.put("/api/products/{product_id}/workspace-content", response_model=WorkspaceContentResponse)
async def put_product_workspace_content(
    product_id: str,
    request: Request,
    path: str = Query(..., min_length=1),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WorkspaceContentResponse:
    """Stage a new local agent file into the vault (no PDM object required yet)."""
    require_permission(request, ctx, PERMISSION_OBJECTS_ADD)
    product = load_accessible_product(request, ctx, db, product_id)
    relative = str(path or "").replace("\\", "/").lstrip("/")
    extras = ctx.config.purgeable_cad_extensions()
    logical = CreoFileManager.logical_repo_path(relative, extras)
    for existing_rel, _filename in ctx.objects.list_path_index(db, product.id):
        if CreoFileManager.logical_repo_path(existing_rel, extras) == logical:
            raise PathValidationError(
                "That path already belongs to a product file. Check it out to update it.",
                details={"relative_path": relative, "existing": existing_rel},
            )
    data = await file.read()
    written = ctx.workspaces.stage_new_workspace_file(product, path, data)
    return WorkspaceContentResponse(
        object_id=product_id,
        filename=written.name,
        path=str(written),
        bytes_written=len(data),
    )


@router.get("/api/products/{product_id}/workspace/content")
def workspace_file_content(
    product_id: str,
    request: Request,
    path: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> FileResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    target = ctx.workspaces.file_path(product, path)
    if not target.is_file():
        raise PathValidationError(
            f"Vault file not found: {Path(path).name}.",
            details={"relative_path": path},
        )
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    download_name = CreoFileManager.canonical_repository_name(
        target.name, ctx.workspaces._cad_extensions()
    )
    disposition = f"attachment; filename*=UTF-8''{quote(download_name)}"
    return FileResponse(
        target,
        media_type=media_type,
        filename=download_name,
        content_disposition_type="attachment",
        headers={"Content-Disposition": disposition},
    )


@router.post("/api/products/{product_id}/objects/from-disk", response_model=BatchOperationResponse)
def import_from_disk(
    product_id: str,
    payload: ImportLocalRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_ADD)
    product = load_accessible_product(request, ctx, db, product_id)
    comment = (payload.comment or "").strip() or None
    batch_total = payload.batch_total if (payload.batch_total or 0) > 0 else None
    import_batch_id = (payload.import_batch_id or "").strip()[:80] or None
    extras = ctx.config.purgeable_cad_extensions()
    ignored = ctx.config.ignore_patterns()
    ok: list[BatchItemResult] = []
    failed: list[BatchItemResult] = []
    recursive = bool(payload.recursive)
    parent_folder = (payload.parent_folder or "").strip()
    folder_paths: list[Path] = []
    if (payload.folder or "").strip():
        folder_paths.append(Path(payload.folder))
    for raw in payload.folders or []:
        text = str(raw or "").strip()
        if text:
            folder_paths.append(Path(text))
    seen_folders: set[str] = set()
    unique_folders: list[Path] = []
    for folder in folder_paths:
        key = str(folder.resolve()) if folder.exists() else str(folder)
        if key in seen_folders:
            continue
        seen_folders.add(key)
        unique_folders.append(folder)

    jobs: list[tuple[Path, str, str | None]] = []
    missing: list[Path] = []
    if unique_folders:
        for folder in unique_folders:
            if not folder.is_dir():
                raise PathValidationError(
                    "The selected folder was not found.",
                    details={"path": str(folder)},
                )
            logger.info("Scanning folder %s (recursive=%s)", folder, recursive)
            selected = CreoFileManager.list_latest_in_folder(
                folder, extras, ignored, recursive=recursive
            )
            base_folder = payload.base_folder or str(folder)
            logger.info("Adding %s file(s) from folder %s", len(selected), folder)
            for path in selected:
                jobs.append(
                    (
                        path,
                        path.name,
                        ctx.workspaces.import_relative_path(
                            product,
                            path,
                            base_folder,
                            parent_folder=parent_folder,
                            keep_root_folder=bool(payload.keep_root_folder),
                        ),
                    )
                )
        if not jobs:
            raise ValidationAppError(
                "No files to add were found in that folder.",
                details={"folder": str(unique_folders[0])},
            )
    else:
        raw_paths = [Path(raw) for raw in payload.paths]
        if not raw_paths:
            raise ValidationAppError("Choose files or a folder first.")
        missing = [path for path in raw_paths if not path.is_file()]
        present = [
            path
            for path in raw_paths
            if path.is_file() and not CreoFileManager.is_ignored(path.name, ignored)
        ]
        selected = CreoFileManager.filter_to_latest_saves(present, extras)
        base_folder = payload.base_folder
        if not base_folder:
            from creopdm.creo.file_manager import common_import_root

            inferred = common_import_root(selected)
            if inferred is not None:
                base_folder = str(inferred)
        jobs = [
            (
                path,
                path.name,
                ctx.workspaces.import_relative_path(
                    product,
                    path,
                    base_folder,
                    parent_folder=parent_folder,
                    keep_root_folder=bool(payload.keep_root_folder),
                ),
            )
            for path in selected
        ]
    for path in missing:
        failed.append(
            BatchItemResult(
                uuid="",
                filename=path.name,
                code="INVALID_PATH",
                message="The selected file was not found.",
            )
        )
    if jobs:
        for outcome in ctx.objects.import_files(
            db,
            product,
            jobs,
            comment,
            batch_total=batch_total,
            import_batch_id=import_batch_id,
        ):
            if outcome.error is not None:
                failed.append(
                    BatchItemResult(
                        uuid="",
                        filename=outcome.filename,
                        code=outcome.error.code,
                        message=outcome.error.message,
                    )
                )
            elif outcome.obj is not None:
                ok.append(
                    BatchItemResult(
                        uuid=outcome.obj.uuid,
                        filename=outcome.filename,
                        status="added",
                        path=str(outcome.source),
                    )
                )
            else:
                failed.append(
                    BatchItemResult(
                        uuid="",
                        filename=outcome.filename,
                        code="APPLICATION_ERROR",
                        message="The file was not added.",
                    )
                )
    db.commit()
    # Do not start Where Used here: Add is chunked (25/400), and indexing mid-upload
    # contends on SQLite. The browser starts indexing once after all chunks finish.
    if ok:
        from creopdm.api.watch_notify import notify_product_watchers

        notify_product_watchers(
            request,
            ctx,
            db,
            product,
            action="Files added",
            filenames=[item.filename for item in ok if item.filename],
        )
    return BatchOperationResponse(
        ok=ok,
        failed=failed,
        workspace_root=str(ctx.workspaces.vault_for(product)),
    )


@router.post(
    "/api/products/{product_id}/folders",
    response_model=CreateFolderResponse,
    status_code=201,
)
def create_product_folder(
    product_id: str,
    payload: CreateFolderRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> CreateFolderResponse:
    """Create an empty folder in the vault at the current Files view location."""
    require_permission(request, ctx, PERMISSION_OBJECTS_ADD)
    product = load_accessible_product(request, ctx, db, product_id)
    user = ctx.users.get_current_user()
    created = ctx.workspaces.create_folder(
        product,
        name=payload.name,
        parent_folder=payload.parent_folder or "",
        user=user,
        comment=(payload.comment or "").strip() or None,
    )
    db.commit()
    return CreateFolderResponse(path=created, name=Path(created).name)


@router.post("/api/products/{product_id}/objects/from-uploads", response_model=BatchOperationResponse)
async def import_from_uploads(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_ADD)
    # Browser folder picks send many parts; Starlette defaults to 1000 files/fields.
    try:
        form = await request.form(max_files=20000, max_fields=40000)
    except OSError as exc:
        # Multipart spills to /tmp; a full disk surfaces here as Errno 28.
        if getattr(exc, "errno", None) == 28:
            raise ValidationAppError(
                "CreoPDM host disk is full (could not receive the upload). "
                "Free space under /tmp and ~/.local/share/CreoPDM, then retry."
            ) from exc
        raise
    uploaded_files = form.getlist("files")
    rels = [str(item) for item in form.getlist("relative_paths")]
    comment_raw = form.get("comment")
    note = str(comment_raw).strip() if comment_raw not in (None, "") else None
    parent_raw = form.get("parent_folder")
    parent_folder = str(parent_raw or "").strip().replace("\\", "/").strip("/")
    batch_total: int | None = None
    batch_raw = form.get("batch_total")
    if batch_raw not in (None, ""):
        try:
            parsed = int(str(batch_raw).strip())
            if parsed > 0:
                batch_total = parsed
        except (TypeError, ValueError):
            batch_total = None
    batch_id_raw = form.get("import_batch_id")
    import_batch_id = (
        str(batch_id_raw).strip()[:80] if batch_id_raw not in (None, "") else None
    ) or None
    product = load_accessible_product(request, ctx, db, product_id)
    temps: list[Path] = []
    jobs: list[tuple[Path, str | None, str | None]] = []
    ok: list[BatchItemResult] = []
    failed: list[BatchItemResult] = []
    try:
        for index, uploaded in enumerate(uploaded_files):
            if not hasattr(uploaded, "read"):
                continue
            filename = Path(getattr(uploaded, "filename", None) or "untitled").name
            if not filename:
                failed.append(
                    BatchItemResult(
                        uuid="",
                        filename="untitled",
                        code="VALIDATION_ERROR",
                        message="A filename is required.",
                    )
                )
                continue
            try:
                data = await uploaded.read()
            except OSError as exc:
                if getattr(exc, "errno", None) == 28:
                    failed.append(
                        BatchItemResult(
                            uuid="",
                            filename=filename,
                            code="DISK_FULL",
                            message="CreoPDM host disk is full while reading the upload.",
                        )
                    )
                    break
                raise
            if not data:
                failed.append(
                    BatchItemResult(
                        uuid="",
                        filename=filename,
                        code="VALIDATION_ERROR",
                        message="The uploaded file is empty.",
                    )
                )
                continue
            handle = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}")
            try:
                handle.write(data)
            finally:
                handle.close()
            temp_path = Path(handle.name)
            temps.append(temp_path)
            relative = rels[index] if index < len(rels) else None
            if relative:
                rel = str(relative).replace("\\", "/").lstrip("/")
                if parent_folder and rel != parent_folder and not rel.startswith(f"{parent_folder}/"):
                    relative = f"{parent_folder}/{rel}"
                else:
                    relative = rel
            elif parent_folder:
                relative = f"{parent_folder}/{filename}"
            jobs.append((temp_path, filename, relative or None))
        if jobs:
            for outcome in ctx.objects.import_files(
                db,
                product,
                jobs,
                note,
                batch_total=batch_total,
                import_batch_id=import_batch_id,
            ):
                if outcome.error is not None:
                    failed.append(
                        BatchItemResult(
                            uuid="",
                            filename=outcome.filename,
                            code=outcome.error.code,
                            message=outcome.error.message,
                        )
                    )
                elif outcome.obj is not None:
                    ok.append(
                        BatchItemResult(
                            uuid=outcome.obj.uuid,
                            filename=outcome.filename,
                            status="added",
                        )
                    )
                else:
                    failed.append(
                        BatchItemResult(
                            uuid="",
                            filename=outcome.filename,
                            code="APPLICATION_ERROR",
                            message="The file was not added.",
                        )
                    )
    finally:
        for path in temps:
            path.unlink(missing_ok=True)
        try:
            await form.close()
        except Exception:
            pass
    if not jobs and not failed:
        raise ValidationAppError("Drop files or a folder first.")
    db.commit()
    # Where Used starts from the browser after all Add chunks finish (not per chunk).
    if ok:
        from creopdm.api.watch_notify import notify_product_watchers

        notify_product_watchers(
            request,
            ctx,
            db,
            product,
            action="Files added",
            filenames=[item.filename for item in ok if item.filename],
        )
    return BatchOperationResponse(
        ok=ok,
        failed=failed,
        workspace_root=str(ctx.workspaces.vault_for(product)),
    )


def _zip_import_job_response(status) -> ZipImportJobResponse:
    return ZipImportJobResponse(
        job_id=status.job_id,
        product_id=status.product_id,
        state=status.state,
        phase=status.phase,
        message=status.message,
        bytes_total=status.bytes_total,
        bytes_done=status.bytes_done,
        files_total=status.files_total,
        files_done=status.files_done,
        error=status.error,
        done=status.done,
        started_at=status.started_at,
        finished_at=status.finished_at,
    )


def _zip_extract_and_import(
    ctx: AppContext,
    product_uuid: str,
    zip_tmp: Path,
    parent_folder: str,
    note: str | None,
    job_id: str,
) -> tuple[list[BatchItemResult], list[BatchItemResult], Path | None]:
    """Extract + import on a worker thread so progress polls are not blocked."""
    from creopdm.models.product import Product
    from creopdm.utils.zip_import import extract_zip_to_temp, plan_zip_import_jobs

    if job_id:
        ctx.zip_imports.set_extracting(job_id)
    extract_parent, extract_dir = extract_zip_to_temp(zip_tmp)
    jobs = plan_zip_import_jobs(
        extract_dir,
        parent_folder=parent_folder,
        purgeable_extensions=ctx.config.purgeable_cad_extensions(),
        ignore_patterns=ctx.config.ignore_patterns(),
    )
    if not jobs:
        raise ValidationAppError("No files to add were found in that zip.")

    def _on_import_progress(phase: str, done: int, files_total: int) -> None:
        if not job_id:
            return
        if phase == "importing":
            ctx.zip_imports.set_importing(job_id, files_done=done, files_total=files_total)
        elif phase == "committing":
            ctx.zip_imports.set_committing(job_id, files_total=files_total)
        elif phase == "recording":
            ctx.zip_imports.set_recording(job_id, files_done=done, files_total=files_total)

    if job_id:
        ctx.zip_imports.set_importing(job_id, files_done=0, files_total=len(jobs))

    ok: list[BatchItemResult] = []
    failed: list[BatchItemResult] = []
    session = ctx.session_factory()
    try:
        product = session.scalar(select(Product).where(Product.uuid == product_uuid))
        if product is None:
            raise ValidationAppError("Product not found.")
        for outcome in ctx.objects.import_files(
            session, product, jobs, note, on_progress=_on_import_progress
        ):
            if outcome.error is not None:
                failed.append(
                    BatchItemResult(
                        uuid="",
                        filename=outcome.filename,
                        code=outcome.error.code,
                        message=outcome.error.message,
                    )
                )
            elif outcome.obj is not None:
                ok.append(
                    BatchItemResult(
                        uuid=outcome.obj.uuid,
                        filename=outcome.filename,
                        status="added",
                    )
                )
            else:
                failed.append(
                    BatchItemResult(
                        uuid="",
                        filename=outcome.filename,
                        code="APPLICATION_ERROR",
                        message="The file was not added.",
                    )
                )
        session.commit()
        if job_id:
            ctx.zip_imports.set_done(job_id, files_total=len(ok))
        return ok, failed, extract_parent
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@router.post(
    "/api/products/{product_id}/zip-import/jobs",
    response_model=ZipImportJobResponse,
)
def start_zip_import_job(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ZipImportJobResponse:
    """Create a progress job for Compressed data… (browser polls while agent uploads)."""
    from creopdm.product_state import ensure_product_mutable

    require_permission(request, ctx, PERMISSION_OBJECTS_ADD)
    product = load_accessible_product(request, ctx, db, product_id)
    ensure_product_mutable(product, action="add files")
    return _zip_import_job_response(ctx.zip_imports.create(product_id))


@router.get(
    "/api/products/{product_id}/zip-import/jobs/{job_id}",
    response_model=ZipImportJobResponse,
)
def zip_import_job_status(
    product_id: str,
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ZipImportJobResponse:
    """Poll zip import phase / counts for the busy overlay."""
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    load_accessible_product(request, ctx, db, product_id)
    status = ctx.zip_imports.get(job_id)
    if status is None or status.product_id != product_id:
        raise ValidationAppError("Zip import job not found.")
    return _zip_import_job_response(status)


@router.post("/api/products/{product_id}/objects/from-zip", response_model=BatchOperationResponse)
async def import_from_zip(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    """Upload one .zip, extract on the host, import like Add folders… (strip single root)."""
    from creopdm.product_state import ensure_product_mutable
    from creopdm.utils.zip_import import MAX_ZIP_IMPORT_BYTES, assert_zip_filename

    require_permission(request, ctx, PERMISSION_OBJECTS_ADD)
    try:
        form = await request.form(max_files=5, max_fields=20)
    except OSError as exc:
        if getattr(exc, "errno", None) == 28:
            raise ValidationAppError(
                "CreoPDM host disk is full (could not receive the upload). "
                "Free space under /tmp and ~/.local/share/CreoPDM, then retry."
            ) from exc
        raise
    uploaded = form.get("file") or form.get("files")
    comment_raw = form.get("comment")
    note = str(comment_raw).strip() if comment_raw not in (None, "") else None
    parent_raw = form.get("parent_folder")
    parent_folder = str(parent_raw or "").strip().replace("\\", "/").strip("/")
    job_raw = form.get("job_id")
    job_id = str(job_raw or "").strip()
    zip_bytes_raw = form.get("zip_bytes")
    try:
        zip_bytes_hint = int(str(zip_bytes_raw or "0").strip() or "0")
    except ValueError:
        zip_bytes_hint = 0
    product = load_accessible_product(request, ctx, db, product_id)
    ensure_product_mutable(product, action="add files")

    if job_id:
        status = ctx.zip_imports.get(job_id)
        if status is None or status.product_id != product_id:
            raise ValidationAppError("Zip import job not found.")

    if uploaded is None or not hasattr(uploaded, "read"):
        if job_id:
            ctx.zip_imports.set_error(job_id, "Choose a .zip file first.")
        raise ValidationAppError("Choose a .zip file first.")
    filename = assert_zip_filename(getattr(uploaded, "filename", None) or "archive.zip")

    zip_tmp: Path | None = None
    extract_parent: Path | None = None
    ok: list[BatchItemResult] = []
    failed: list[BatchItemResult] = []
    try:
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{filename}")
        zip_tmp = Path(handle.name)
        total = 0
        bytes_total_hint = max(0, zip_bytes_hint)
        if job_id:
            ctx.zip_imports.set_uploading(job_id, bytes_done=0, bytes_total=bytes_total_hint)
        try:
            while True:
                try:
                    chunk = await uploaded.read(1024 * 1024)
                except OSError as exc:
                    if getattr(exc, "errno", None) == 28:
                        raise ValidationAppError(
                            "CreoPDM host disk is full while reading the upload."
                        ) from exc
                    raise
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ZIP_IMPORT_BYTES:
                    raise ValidationAppError(
                        "That zip is larger than the 2 GB limit."
                    )
                handle.write(chunk)
                # Every chunk (~1 MB) so the busy overlay keeps moving.
                if job_id:
                    ctx.zip_imports.set_uploading(
                        job_id,
                        bytes_done=total,
                        bytes_total=max(bytes_total_hint, total),
                    )
        finally:
            handle.close()
        if total <= 0:
            raise ValidationAppError("The uploaded zip is empty.")
        if job_id:
            ctx.zip_imports.set_uploading(job_id, bytes_done=total, bytes_total=total)
            ctx.zip_imports.set_extracting(job_id)

        # Extract/import are sync and long — run off the event loop so GET
        # zip-import/jobs polls (busy overlay) are not frozen at the last upload %.
        ok, failed, extract_parent = await run_in_threadpool(
            _zip_extract_and_import,
            ctx,
            product_id,
            zip_tmp,
            parent_folder,
            note,
            job_id,
        )
    except Exception as exc:
        if job_id:
            message = getattr(exc, "message", None) or str(exc) or "Compressed import failed."
            ctx.zip_imports.set_error(job_id, str(message))
        raise
    finally:
        if zip_tmp is not None:
            zip_tmp.unlink(missing_ok=True)
        if extract_parent is not None:
            shutil.rmtree(extract_parent, ignore_errors=True)
        try:
            await form.close()
        except Exception:
            pass

    # Where Used starts from the browser after all Add chunks finish (not per chunk).
    if ok:
        from creopdm.api.watch_notify import notify_product_watchers

        notify_product_watchers(
            request,
            ctx,
            db,
            product,
            action="Files added",
            filenames=[item.filename for item in ok if item.filename],
        )
    return BatchOperationResponse(
        ok=ok,
        failed=failed,
        workspace_root=str(ctx.workspaces.vault_for(product)),
    )
