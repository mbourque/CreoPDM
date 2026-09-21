from __future__ import annotations

import mimetypes
import tempfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from creopdm.api.checkout import present_object, present_objects
from creopdm.api.deps import get_context, get_db
from creopdm.api.serializers import project_to_response
from creopdm.context import AppContext
from creopdm.constants import ActivityAction
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import CreoPDMError, PathValidationError, ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.schemas.common import (
    BatchItemResult,
    BatchOperationResponse,
    ForgetProjectRequest,
    ForgetProjectResponse,
    CheckinPreviewResponse,
    ImportLocalRequest,
    ObjectResponse,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectStatusResponse,
    ProjectUpdateRequest,
    PurgeWorkspacePathsRequest,
    QueueCheckinRequest,
    WorkspacePickerResponse,
    WorkspaceWatchResponse,
)
from creopdm.utils.launch import open_windows_folder
from creopdm.utils.native_dialog import pick_files, pick_folder

router = APIRouter()
logger = get_logger("projects")


@router.get("/api/projects", response_model=list[ProjectResponse])
def list_projects(
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[ProjectResponse]:
    return [project_to_response(project) for project in ctx.projects.list_projects(db)]


@router.post("/api/projects", response_model=ProjectResponse, status_code=201)
def create_project(
    payload: ProjectCreateRequest,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ProjectResponse:
    project = ctx.projects.create_project(
        db,
        name=payload.name,
        number=payload.number,
        description=payload.description,
    )
    return project_to_response(project)


@router.get("/api/projects/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ProjectResponse:
    return project_to_response(ctx.projects.get_project(db, project_id))


@router.patch("/api/projects/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ProjectResponse:
    project = ctx.projects.update_project(
        db,
        project_id,
        name=payload.name,
        number=payload.number,
        description=payload.description,
    )
    return project_to_response(project)


@router.delete("/api/projects/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> None:
    ctx.projects.delete_project(db, project_id)


@router.post("/api/projects/{project_id}/forget", response_model=ForgetProjectResponse)
def forget_project(
    project_id: str,
    payload: ForgetProjectRequest,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ForgetProjectResponse:
    workspace = ctx.config.workspace_for_project(project_id)
    result = ctx.projects.forget_project(
        db,
        project_id,
        confirm_name=payload.confirm_name,
        workspace_path=workspace,
    )
    if ctx.config.settings.ui.last_project_uuid == project_id:
        ctx.config.remember_project(None)
    ctx.config.forget_project_view(project_id)
    return ForgetProjectResponse.model_validate(result)


@router.get("/api/projects/{project_id}/objects", response_model=list[ObjectResponse])
def list_objects(
    project_id: str,
    q: str | None = None,
    object_type: str | None = None,
    lifecycle_state: str | None = None,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[ObjectResponse]:
    project = ctx.projects.get_project(db, project_id)
    objects = ctx.objects.search(
        db,
        project,
        query=q,
        object_type=object_type,
        lifecycle_state=lifecycle_state,
    )
    return present_objects(ctx, db, objects)


@router.get("/api/projects/{project_id}/status", response_model=ProjectStatusResponse)
def project_status(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ProjectStatusResponse:
    counts = ctx.projects.project_status(db, project_id)
    return ProjectStatusResponse.model_validate(counts)


@router.get("/api/projects/{project_id}/workspace-watch", response_model=WorkspaceWatchResponse)
def workspace_watch(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WorkspaceWatchResponse:
    project = ctx.projects.get_project(db, project_id)
    known = ctx.objects.list_path_index(db, project.id)
    return WorkspaceWatchResponse.model_validate(ctx.workspaces.watch_stamp(project, known))


@router.get("/api/projects/{project_id}/checkin-preview", response_model=CheckinPreviewResponse)
def project_checkin_preview(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> CheckinPreviewResponse:
    project = ctx.projects.get_project(db, project_id)
    return CheckinPreviewResponse.model_validate(ctx.checkins.preview_queue(db, project))


@router.get("/api/projects/{project_id}/checkin-queue")
def project_checkin_queue_view(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> dict:
    project = ctx.projects.get_project(db, project_id)
    objects = ctx.objects.list_objects(db, project.id)
    return ctx.workspaces.project_checkin_queue(project, objects)


@router.get("/api/projects/{project_id}/checkouts", response_model=list[ObjectResponse])
def list_project_checkouts(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[ObjectResponse]:
    project = ctx.projects.get_project(db, project_id)
    objects = ctx.checkouts.list_for_project(db, project.id)
    return present_objects(ctx, db, objects)


@router.post("/api/projects/{project_id}/checkin-queue", response_model=BatchOperationResponse)
def project_checkin_queue(
    project_id: str,
    payload: QueueCheckinRequest,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    project = ctx.projects.get_project(db, project_id)
    result = ctx.checkins.checkin_queue(
        db,
        project,
        payload.comment,
        payload.object_ids,
        payload.add_relative_paths,
    )
    return BatchOperationResponse.model_validate(
        {**result, "workspace_root": str(ctx.workspaces.root_for(project.uuid))}
    )


@router.post(
    "/api/projects/{project_id}/workspace/purge-paths",
    response_model=BatchOperationResponse,
)
def purge_workspace_paths(
    project_id: str,
    payload: PurgeWorkspacePathsRequest,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    project = ctx.projects.get_project(db, project_id)
    objects = ctx.objects.list_objects(db, project.id)
    ok: list[BatchItemResult] = []
    failed: list[BatchItemResult] = []
    try:
        removed = ctx.workspaces.purge_untracked_paths(project, payload.relative_paths, objects)
        user = ctx.users.get_current_user()
        for item in removed:
            ctx.activities.record(
                db,
                ActivityAction.WORKSPACE_CLEARED,
                user,
                project_id=project.id,
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
        workspace_root=str(ctx.workspaces.root_for(project.uuid)),
    )


def _picker_filters(ctx: AppContext) -> dict[str, list[str]]:
    extensions = [
        *ctx.config.model_cad_extensions(),
        *ctx.config.openable_cad_extensions(),
        *ctx.config.data_cad_extensions(),
        *ctx.config.document_extensions(),
    ]
    seen: set[str] = set()
    unique: list[str] = []
    for raw in extensions:
        ext = str(raw or "").strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = f".{ext}"
        if ext in seen:
            continue
        seen.add(ext)
        unique.append(ext)
    return {
        "ignore_patterns": list(ctx.config.ignore_patterns()),
        "import_extensions": unique,
    }


@router.get("/api/projects/{project_id}/workspace/add-folder", response_model=WorkspacePickerResponse)
def workspace_add_folder(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WorkspacePickerResponse:
    project = ctx.projects.get_project(db, project_id)
    start = ctx.projects.preferred_import_directory(project)
    start.mkdir(parents=True, exist_ok=True)
    filters = _picker_filters(ctx)
    return WorkspacePickerResponse(
        workspace_root=str(ctx.workspaces.root_for(project.uuid)),
        initial_directory=str(start),
        ignore_patterns=filters["ignore_patterns"],
        import_extensions=filters["import_extensions"],
    )


@router.post("/api/projects/{project_id}/workspace/choose-files", response_model=WorkspacePickerResponse)
def choose_workspace_files(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WorkspacePickerResponse:
    project = ctx.projects.get_project(db, project_id)
    start = ctx.projects.preferred_import_directory(project)
    start.mkdir(parents=True, exist_ok=True)
    picked = pick_files(start, title="Add files to the project")
    ignored = ctx.config.ignore_patterns()
    extras = ctx.config.all_cad_extensions()
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
        scan_disk_siblings=False,
    )
    return WorkspacePickerResponse(
        workspace_root=str(ctx.workspaces.root_for(project.uuid)),
        initial_directory=str(start),
        selected=[str(path) for path in selected],
        ignored_count=ignored_count,
    )


@router.post("/api/projects/{project_id}/workspace/choose-folder", response_model=WorkspacePickerResponse)
def choose_workspace_folder(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WorkspacePickerResponse:
    project = ctx.projects.get_project(db, project_id)
    start = ctx.projects.preferred_import_directory(project)
    start.mkdir(parents=True, exist_ok=True)
    chosen = pick_folder(start, title="Add a folder to the project")
    if chosen is None:
        logger.info("Folder picker cancelled")
        return WorkspacePickerResponse(
            workspace_root=str(ctx.workspaces.root_for(project.uuid)),
            initial_directory=str(start),
            cancelled=True,
        )
    logger.info("Chose folder %s", chosen)
    return WorkspacePickerResponse(
        workspace_root=str(ctx.workspaces.root_for(project.uuid)),
        initial_directory=str(chosen),
        selected=[],
        folder=str(chosen),
    )


@router.post("/api/projects/{project_id}/workspace/open", status_code=204)
def open_workspace_folder(
    project_id: str,
    folder: str | None = Query(default=None),
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    project = ctx.projects.get_project(db, project_id)
    opened = ctx.workspaces.explorer_directory(project.uuid, folder or "")
    try:
        open_windows_folder(opened)
    except OSError as exc:
        raise PathValidationError(
            "Could not open the vault folder in Explorer.",
            details={"path": str(opened)},
        ) from exc
    return Response(status_code=204)


@router.get("/api/projects/{project_id}/workspace/content")
def workspace_file_content(
    project_id: str,
    path: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> FileResponse:
    project = ctx.projects.get_project(db, project_id)
    target = ctx.workspaces.file_path(project.uuid, path)
    if not target.is_file():
        raise PathValidationError(
            f"Vault file not found: {Path(path).name}.",
            details={"relative_path": path},
        )
    media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    disposition = f"attachment; filename*=UTF-8''{quote(target.name)}"
    return FileResponse(
        target,
        media_type=media_type,
        filename=target.name,
        content_disposition_type="attachment",
        headers={"Content-Disposition": disposition},
    )


@router.post("/api/projects/{project_id}/objects/from-disk", response_model=BatchOperationResponse)
def import_from_disk(
    project_id: str,
    payload: ImportLocalRequest,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    project = ctx.projects.get_project(db, project_id)
    comment = (payload.comment or "").strip() or None
    extras = ctx.config.all_cad_extensions()
    ignored = ctx.config.ignore_patterns()
    ok: list[BatchItemResult] = []
    failed: list[BatchItemResult] = []
    folder = Path(payload.folder) if (payload.folder or "").strip() else None
    if folder is not None and not folder.is_dir():
        raise PathValidationError(
            "The selected folder was not found.",
            details={"path": str(folder)},
        )
    if folder is not None:
        logger.info("Scanning folder %s", folder)
        selected = CreoFileManager.list_latest_in_folder(folder, extras, ignored)
        base_folder = payload.base_folder or str(folder)
        logger.info("Adding %s file(s) from folder %s", len(selected), folder)
        missing: list[Path] = []
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
    for path in missing:
        failed.append(
            BatchItemResult(
                uuid="",
                filename=path.name,
                code="INVALID_PATH",
                message="The selected file was not found.",
            )
        )
    jobs = [
        (path, path.name, ctx.workspaces.import_relative_path(project, path, base_folder))
        for path in selected
    ]
    if folder is not None and not jobs:
        raise ValidationAppError(
            "No files to add were found in that folder.",
            details={"folder": str(folder)},
        )
    if jobs:
        for outcome in ctx.objects.import_files(db, project, jobs, comment):
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
    return BatchOperationResponse(ok=ok, failed=failed, workspace_root=str(ctx.workspaces.root_for(project.uuid)))


@router.post("/api/projects/{project_id}/objects/from-uploads", response_model=BatchOperationResponse)
async def import_from_uploads(
    project_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BatchOperationResponse:
    # Browser folder picks send many parts; Starlette defaults to 1000 files/fields.
    form = await request.form(max_files=20000, max_fields=40000)
    uploaded_files = form.getlist("files")
    rels = [str(item) for item in form.getlist("relative_paths")]
    comment_raw = form.get("comment")
    note = str(comment_raw).strip() if comment_raw not in (None, "") else None
    project = ctx.projects.get_project(db, project_id)
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
            data = await uploaded.read()
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
            jobs.append((temp_path, filename, relative or None))
        if jobs:
            for outcome in ctx.objects.import_files(db, project, jobs, note):
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
    return BatchOperationResponse(ok=ok, failed=failed, workspace_root=str(ctx.workspaces.root_for(project.uuid)))
