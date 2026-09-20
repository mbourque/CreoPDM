"""HTML pages served to the local browser GUI."""

from __future__ import annotations

from pathlib import Path
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from creopdm.api.checkout import present_object, present_objects
from creopdm.api.deps import get_context, get_db
from creopdm.api.serializers import project_to_response, revision_display
from creopdm.constants import APP_NAME, APP_VERSION, ObjectType, SIDEBAR_COLLAPSED_COOKIE
from creopdm.context import AppContext
from creopdm.exceptions import ProjectNotFoundError
from creopdm.utils.files import format_byte_size
from creopdm.utils.folders import folder_crumbs, folder_of, folder_view_counts, normalize_folder_query
from creopdm.utils.native_dialog import native_picker_available
from creopdm.utils.timefmt import format_local

PACKAGE_DIR = Path(__file__).resolve().parent.parent
_template_env = Environment(
    loader=FileSystemLoader(str(PACKAGE_DIR / "templates")),
    autoescape=select_autoescape(),
)
_template_env.filters["local_time"] = format_local
_template_env.filters["byte_size"] = format_byte_size
_template_env.globals["local_time"] = format_local
_template_env.globals["byte_size"] = format_byte_size
templates = Jinja2Templates(env=_template_env)
router = APIRouter()


def _folder_page(
    ctx: AppContext,
    db: Session,
    project_id: int,
    current_folder: str,
) -> tuple[list, list[dict]]:
    """Show imported folders plus only the files that belong in this view."""
    files, folder_entries = ctx.objects.list_folder_view(db, project_id, current_folder)
    presented = present_objects(ctx, db, files)
    list_entries = list(folder_entries)
    for obj in presented:
        list_entries.append(
            {
                "kind": "file",
                "object": obj,
                "folder": current_folder,
                "depth": 0,
            }
        )
    return presented, list_entries


_PAGE_DEFAULTS = {
    "pending_saves": 0,
    "new_workspace_files": 0,
    "checkout_count": 0,
    "checkin_queue": {"saves": [], "new_files": []},
    "local_time": format_local,
    "creo_label": "Not Connected",
    "creo_open_name": "Parametric",
    "creo_open_title": "Opens CAD with Creo Parametric",
    "native_picker": False,
}

_CREO_OPEN_NAMES = {
    "executable": "Parametric",
    "view": "Creo View",
    "association": "Windows",
    "embedded": "Embedded",
}


def render(request: Request, name: str, context: dict) -> HTMLResponse:
    templates.env.filters["local_time"] = format_local
    templates.env.filters["byte_size"] = format_byte_size
    templates.env.globals["local_time"] = format_local
    templates.env.globals["byte_size"] = format_byte_size
    payload = {"request": request, **_PAGE_DEFAULTS, **context}
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


def _creojs_library(ctx: AppContext) -> Path | None:
    finder = getattr(ctx.creo, "find_creojs_library", None)
    if not callable(finder):
        return None
    found = finder()
    if found is None:
        return None
    path = Path(found)
    return path if path.is_file() else None


def _creo_executable(ctx: AppContext) -> str | None:
    finder = getattr(ctx.creo, "find_executable", None)
    if not callable(finder):
        return None
    found = finder()
    return str(found) if found else None


def _creo_open_mode(ctx: AppContext) -> str:
    finder = getattr(ctx.creo, "cad_open_mode", None)
    if callable(finder):
        return (finder() or "executable").strip().lower()
    return (ctx.settings.creo.open_mode or "executable").strip().lower()


def _creo_view_executable(ctx: AppContext) -> str | None:
    finder = getattr(ctx.creo, "find_view_executable", None)
    if not callable(finder):
        return None
    found = finder()
    return str(found) if found else None


def _creo_open_name(mode: str) -> str:
    return _CREO_OPEN_NAMES.get(mode, "Parametric")


def _creo_open_title(ctx: AppContext, mode: str) -> str:
    if mode == "embedded":
        return "Opens CAD in the Creo session showing this page"
    if mode == "association":
        return "Opens Creo models with the Windows file association"
    if mode == "view":
        return _creo_view_executable(ctx) or "Opens CAD with Creo View"
    return _creo_executable(ctx) or "Opens CAD with Creo Parametric"


_CREO_PAGE_TTL = 20.0
_CREO_PAGE_CACHE: tuple[float, str, dict[str, str | None]] | None = None


def clear_creo_page_cache() -> None:
    global _CREO_PAGE_CACHE
    _CREO_PAGE_CACHE = None


def _creo_page(ctx: AppContext) -> dict[str, str | None]:
    global _CREO_PAGE_CACHE
    now = time.monotonic()
    stamp = str(ctx.config.settings_path)
    if (
        _CREO_PAGE_CACHE is not None
        and now - _CREO_PAGE_CACHE[0] < _CREO_PAGE_TTL
        and _CREO_PAGE_CACHE[1] == stamp
    ):
        return _CREO_PAGE_CACHE[2]
    mode = _creo_open_mode(ctx)
    payload = {
        "creo_label": _creo_label(ctx),
        "creo_executable": _creo_executable(ctx),
        "creo_open_name": _creo_open_name(mode),
        "creo_open_title": _creo_open_title(ctx, mode),
    }
    _CREO_PAGE_CACHE = (now, stamp, payload)
    return payload


def _sidebar_collapsed(request: Request) -> bool:
    raw = (request.cookies.get(SIDEBAR_COLLAPSED_COOKIE) or "").strip().lower()
    return raw in {"1", "true", "yes"}


@router.get("/creojs.js")
def creojs_library(ctx: AppContext = Depends(get_context)) -> FileResponse:
    """Serve Creo's Creo.JS bridge so the embedded browser can talk to this session."""
    path = _creojs_library(ctx)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="Creo.JS was not found next to the Creo executable in Settings.",
        )
    return FileResponse(path, media_type="application/javascript")


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> HTMLResponse:
    projects = [project_to_response(p) for p in ctx.projects.list_projects(db)]
    selected_uuid = request.query_params.get("project") or ctx.config.settings.ui.last_project_uuid
    selected = None
    status = None
    checkin_queue: dict[str, list] = {"saves": [], "new_files": []}
    project = None
    if selected_uuid:
        try:
            project = ctx.projects.get_project(db, selected_uuid)
            selected = project_to_response(project)
        except ProjectNotFoundError:
            selected = None
            project = None
    if selected is None and projects:
        selected = projects[0]
        project = ctx.projects.get_project(db, selected.uuid)
    if project is not None:
        ctx.config.remember_project(project.uuid)
        if "folder" not in request.query_params:
            remembered = ctx.config.remembered_folder(project.uuid)
            if remembered:
                return RedirectResponse(
                    url=f"/?project={quote(project.uuid)}&folder={quote(remembered)}",
                    status_code=303,
                )
        current_folder = normalize_folder_query(request.query_params.get("folder"))
        ctx.config.remember_folder(project.uuid, current_folder)
    else:
        current_folder = normalize_folder_query(request.query_params.get("folder"))
    objects: list = []
    list_entries: list = []
    checkout_count = 0
    pending_saves = 0
    new_workspace_files = 0
    if project is not None:
        objects, list_entries = _folder_page(ctx, db, project.id, current_folder)
        checkout_count = ctx.checkouts.count_for_project(db, project.id)
        known = ctx.objects.list_path_index(db, project.id)
        watch = ctx.workspaces.watch_stamp(project, known)
        pending_saves = int(watch.get("pending_saves") or 0)
        new_workspace_files = int(watch.get("new_files") or 0)
    status = folder_view_counts(
        objects,
        current_folder,
        ctx.config.cad_models_extensions(),
        ctx.config.document_extensions(),
    )

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
            "list_entries": list_entries,
            "status": status,
            "cad_models_extensions": ctx.config.cad_models_extensions(),
            "document_extensions": ctx.config.document_extensions(),
            "checkin_queue": checkin_queue,
            "checkout_count": checkout_count,
            "pending_saves": pending_saves,
            "new_workspace_files": new_workspace_files,
            "workspace_path": str(ctx.config.workspace_for_project(selected.uuid)) if selected else None,
            "sidebar_collapsed": _sidebar_collapsed(request),
            "object_types": [item.value for item in ObjectType],
            "revision_display": revision_display,
            "native_picker": native_picker_available(),
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
            "workspace_folder": folder_of(obj.relative_path),
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


@router.get("/settings/types", response_class=HTMLResponse)
def settings_types_page(
    request: Request,
    ctx: AppContext = Depends(get_context),
) -> HTMLResponse:
    from creopdm.api.settings import settings_to_response

    return render(
        request,
        "settings_types.html",
        {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            **_creo_page(ctx),
            "settings": settings_to_response(ctx),
        },
    )
