"""HTML pages served to the local browser GUI."""

from __future__ import annotations

from pathlib import Path
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from creopdm.api.checkout import present_object, present_objects
from creopdm.api.deps import get_context, get_db
from creopdm.api.serializers import project_to_response, revision_display
from creopdm.constants import APP_NAME, APP_VERSION, ObjectType
from creopdm.context import AppContext
from creopdm.exceptions import ProjectNotFoundError
from creopdm.utils.folders import folder_crumbs, folder_list_entries, folder_view_counts, normalize_folder_query

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


def _creo_executable(ctx: AppContext) -> str | None:
    finder = getattr(ctx.creo, "find_executable", None)
    if not callable(finder):
        return None
    found = finder()
    return str(found) if found else None


_CREO_PAGE_TTL = 20.0
_CREO_PAGE_CACHE: tuple[float, dict[str, str | None]] | None = None


def _creo_page(ctx: AppContext) -> dict[str, str | None]:
    global _CREO_PAGE_CACHE
    now = time.monotonic()
    if _CREO_PAGE_CACHE is not None and now - _CREO_PAGE_CACHE[0] < _CREO_PAGE_TTL:
        return _CREO_PAGE_CACHE[1]
    payload = {
        "creo_label": _creo_label(ctx),
        "creo_executable": _creo_executable(ctx),
    }
    _CREO_PAGE_CACHE = (now, payload)
    return payload


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> HTMLResponse:
    projects = [project_to_response(p) for p in ctx.projects.list_projects(db)]
    selected_uuid = request.query_params.get("project") or ctx.config.settings.ui.last_project_uuid
    selected = None
    objects = []
    status = None
    checkin_queue: dict[str, list] = {"saves": [], "new_files": []}
    orm_objects = []
    project = None
    if selected_uuid:
        try:
            project = ctx.projects.get_project(db, selected_uuid)
            selected = project_to_response(project)
            orm_objects = ctx.objects.list_objects(db, project.id)
            objects = present_objects(ctx, db, orm_objects)
            status = ctx.projects.project_status(db, project.uuid)
        except ProjectNotFoundError:
            selected = None
            project = None
    if selected is None and projects:
        selected = projects[0]
        project = ctx.projects.get_project(db, selected.uuid)
        orm_objects = ctx.objects.list_objects(db, project.id)
        objects = present_objects(ctx, db, orm_objects)
        status = ctx.projects.project_status(db, project.uuid)
    if project is not None:
        checkin_queue = ctx.workspaces.project_checkin_queue(project, orm_objects)
        ctx.config.remember_project(project.uuid)
    current_folder = normalize_folder_query(request.query_params.get("folder"))
    if status is not None:
        status = {**status, **folder_view_counts(objects, current_folder)}

    return render(
        request,
        "app.html",
        {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            **_creo_page(ctx),
            "projects": projects,
            "selected": selected,
            "objects": objects,
            "current_folder": current_folder,
            "folder_crumbs": folder_crumbs(current_folder),
            "list_entries": folder_list_entries(objects, current_folder),
            "status": status,
            "checkin_queue": checkin_queue,
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
            **_creo_page(ctx),
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
            **_creo_page(ctx),
            "settings": settings_to_response(ctx),
        },
    )
