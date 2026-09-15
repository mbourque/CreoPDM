from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from creopdm.api.checkout import present_object
from creopdm.api.deps import get_context, get_db
from creopdm.api.serializers import project_to_response
from creopdm.context import AppContext
from creopdm.exceptions import CreoPDMError, PathValidationError
from creopdm.schemas.common import (
    BatchItemResult,
    BatchOperationResponse,
    ImportLocalRequest,
    ObjectResponse,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectStatusResponse,
    WorkspacePickerResponse,
)
from creopdm.utils.launch import open_windows_folder
from creopdm.utils.native_dialog import pick_files

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
        repository_path=payload.repository_path,
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


@router.delete("/api/projects/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> None:
    ctx.projects.delete_project(db, project_id)


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
    return [present_object(ctx, db, obj) for obj in objects]


@router.get("/api/projects/{project_id}/status", response_model=ProjectStatusResponse)
def project_status(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> ProjectStatusResponse:
    counts = ctx.projects.project_status(db, project_id)
    return ProjectStatusResponse.model_validate(counts)


def _owned_relative_paths(ctx: AppContext, db: Session, project) -> list[str]:
    user = ctx.users.get_current_user()
    owned: list[str] = []
    for obj in ctx.objects.list_objects(db, project.id):
        checkout = ctx.checkouts.active_for(db, obj.id)
        if checkout is not None and checkout.user_name == user.user_name:
            owned.append(obj.relative_path)
    return owned


@router.get("/api/projects/{project_id}/workspace/add-folder", response_model=WorkspacePickerResponse)
def workspace_add_folder(
    project_id: str,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> WorkspacePickerResponse:
    project = ctx.projects.get_project(db, project_id)
    start = ctx.workspaces.preferred_add_directory(project.uuid, _owned_relative_paths(ctx, db, project))
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
    start = ctx.workspaces.preferred_add_directory(project.uuid, _owned_relative_paths(ctx, db, project))
    start.mkdir(parents=True, exist_ok=True)
    selected = [str(path) for path in pick_files(start, title="Add files from workspace")]
    return WorkspacePickerResponse(
        workspace_root=str(ctx.workspaces.root_for(project.uuid)),
        initial_directory=str(start),
        selected=selected,
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
    ok: list[BatchItemResult] = []
    failed: list[BatchItemResult] = []
    for raw in payload.paths:
        path = Path(raw)
        try:
            if not path.is_file():
                raise PathValidationError(
                    "The selected file was not found.",
                    details={"path": str(path)},
                )
            relative = ctx.workspaces.relative_if_inside(project.uuid, path)
            obj = ctx.objects.import_file(
                db,
                project,
                path,
                original_name=path.name,
                relative_path=relative,
                comment=comment,
            )
            ok.append(BatchItemResult(uuid=obj.uuid, filename=obj.filename, status="added", path=str(path)))
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
