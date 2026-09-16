from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from creopdm.api.checkout import present_object, present_objects
from creopdm.api.deps import get_context, get_db
from creopdm.api.serializers import project_to_response
from creopdm.context import AppContext
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import CreoPDMError, PathValidationError
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
    QueueCheckinRequest,
    WorkspacePickerResponse,
    WorkspaceWatchResponse,
)
from creopdm.utils.launch import open_windows_folder
from creopdm.utils.native_dialog import pick_files, pick_folder

router = APIRouter()


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


@router.get("/api/projects/{project_id}/workspace/add-folder", response_model=WorkspacePickerResponse)
def workspace_add_folder(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WorkspacePickerResponse:
    project = ctx.projects.get_project(db, project_id)
    start = ctx.projects.preferred_import_directory(project)
    start.mkdir(parents=True, exist_ok=True)
    return WorkspacePickerResponse(
        workspace_root=str(ctx.workspaces.root_for(project.uuid)),
        initial_directory=str(start),
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
    selected = [str(path) for path in pick_files(start, title="Add files to the project")]
    return WorkspacePickerResponse(
        workspace_root=str(ctx.workspaces.root_for(project.uuid)),
        initial_directory=str(start),
        selected=selected,
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
        return WorkspacePickerResponse(
            workspace_root=str(ctx.workspaces.root_for(project.uuid)),
            initial_directory=str(start),
            cancelled=True,
        )
    extras = ctx.config.all_cad_extensions()
    ignored = ctx.config.ignore_patterns()
    selected = [
        str(path)
        for path in CreoFileManager.list_latest_in_folder(chosen, extras, ignored)
    ]
    return WorkspacePickerResponse(
        workspace_root=str(ctx.workspaces.root_for(project.uuid)),
        initial_directory=str(chosen),
        selected=selected,
        folder=str(chosen),
    )


@router.post("/api/projects/{project_id}/workspace/open", status_code=204)
def open_workspace_folder(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    project = ctx.projects.get_project(db, project_id)
    folder = ctx.workspaces.root_for(project.uuid)
    try:
        open_windows_folder(folder)
    except OSError as exc:
        raise PathValidationError(
            "Could not open the workspace folder in Explorer.",
            details={"path": str(folder)},
        ) from exc
    return Response(status_code=204)


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
    raw_paths = [Path(raw) for raw in payload.paths]
    missing = [path for path in raw_paths if not path.is_file()]
    present = [
        path
        for path in raw_paths
        if path.is_file() and not CreoFileManager.is_ignored(path.name, ignored)
    ]
    selected = CreoFileManager.filter_to_latest_saves(present, extras)
    for path in missing:
        failed.append(
            BatchItemResult(
                uuid="",
                filename=path.name,
                code="INVALID_PATH",
                message="The selected file was not found.",
            )
        )
    for path in selected:
        try:
            relative = ctx.workspaces.import_relative_path(project, path, payload.base_folder)
            obj = ctx.objects.import_file(
                db,
                project,
                path,
                original_name=path.name,
                relative_path=relative,
                comment=comment,
            )
            checkout = ctx.checkouts.active_for(db, obj.id)
            mine = checkout is not None and checkout.user_name == ctx.users.get_current_user().user_name
            ctx.workspaces.copy_into_workspace(project, obj, writable=mine, keep_local=mine)
            ok.append(BatchItemResult(uuid=obj.uuid, filename=path.name, status="added", path=str(path)))
        except CreoPDMError as exc:
            failed.append(
                BatchItemResult(
                    uuid="",
                    filename=path.name,
                    code=exc.code,
                    message=exc.message,
                )
            )
    return BatchOperationResponse(ok=ok, failed=failed, workspace_root=str(ctx.workspaces.root_for(project.uuid)))
