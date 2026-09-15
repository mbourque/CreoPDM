"""HTML pages served to the local browser GUI."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from creopdm.api.checkout import present_object
from creopdm.api.deps import get_context, get_db
from creopdm.api.serializers import project_to_response, revision_display
from creopdm.constants import APP_NAME, APP_VERSION, ObjectType
from creopdm.context import AppContext
from creopdm.exceptions import ProjectNotFoundError

PACKAGE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
router = APIRouter()


def render(request: Request, name: str, context: dict) -> HTMLResponse:
    payload = {"request": request, **context}
    try:
        return templates.TemplateResponse(request, name, payload)
    except TypeError:
        return templates.TemplateResponse(name, payload)


def _creo_label(ctx: AppContext) -> str:
    if ctx.creo.is_running():
        return "Connected"
    if ctx.creo.is_available():
        return "Installed"
    return "Not Connected"


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> HTMLResponse:
    projects = [project_to_response(p) for p in ctx.projects.list_projects(db)]
    selected_uuid = request.query_params.get("project")
    selected = None
    objects = []
    status = None
    if selected_uuid:
        try:
            project = ctx.projects.get_project(db, selected_uuid)
            selected = project_to_response(project)
            objects = [present_object(ctx, db, obj) for obj in ctx.objects.list_objects(db, project.id)]
            status = ctx.projects.project_status(db, project.uuid)
        except ProjectNotFoundError:
            selected = None
    elif projects:
        selected = projects[0]
        project = ctx.projects.get_project(db, selected.uuid)
        objects = [present_object(ctx, db, obj) for obj in ctx.objects.list_objects(db, project.id)]
        status = ctx.projects.project_status(db, project.uuid)

    return render(
        request,
        "app.html",
        {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "creo_label": _creo_label(ctx),
            "projects": projects,
            "selected": selected,
            "objects": objects,
            "status": status,
            "workspace_path": str(ctx.config.workspace_for_project(selected.uuid)) if selected else None,
            "object_types": [item.value for item in ObjectType],
            "revision_display": revision_display,
        },
    )


@router.get("/projects/{project_id}/objects/{object_id}", response_class=HTMLResponse)
def object_detail(
    project_id: str,
    object_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> HTMLResponse:
    project = ctx.projects.get_project(db, project_id)
    obj = ctx.objects.get_object(db, object_id)
    history = ctx.objects.object_history(db, object_id)
    payload = present_object(ctx, db, obj)
    is_assembly = obj.object_type == ObjectType.CREO_ASSEMBLY.value
    is_creo = obj.object_type.startswith("CREO_")
    pending = ctx.workspaces.pending_workspace_save(project, obj)
    return render(
        request,
        "object_detail.html",
        {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "creo_label": _creo_label(ctx),
            "project": project_to_response(project),
            "object": payload,
            "history": history,
            "workspace_pending": pending,
            "is_assembly": is_assembly,
            "is_creo": is_creo,
            "workspace_path": str(ctx.config.workspace_for_project(project.uuid)),
        },
    )


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    ctx: AppContext = Depends(get_context),
) -> HTMLResponse:
    from creopdm.api.settings import settings_to_response

    return render(
        request,
        "settings.html",
        {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "creo_label": _creo_label(ctx),
            "settings": settings_to_response(ctx),
        },
    )
