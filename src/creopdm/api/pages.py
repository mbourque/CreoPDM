"""HTML pages served to the local browser GUI."""

from __future__ import annotations

import json
import re
from pathlib import Path
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from creopdm.api.checkout import present_object, present_objects
from creopdm.api.deps import (
    accessible_products,
    get_context,
    get_db,
    load_accessible_product,
    require_permission,
    require_product_access,
)
from creopdm.api.serializers import product_to_response, revision_display
from creopdm.auth_constants import PERMISSION_OBJECTS_VIEW, PERMISSION_PRODUCTS_VIEW
from creopdm.constants import APP_NAME, APP_VERSION, ObjectType, SIDEBAR_COLLAPSED_COOKIE
from creopdm.context import AppContext
from creopdm.exceptions import PermissionDeniedError, ProductNotFoundError
from creopdm.permissions import caps_dict
from creopdm.utils.bom_match import bom_generic_label, bom_lookup_keys
from creopdm.utils.classify import (
    display_type_label,
    matches_cad_models,
    resolve_type_icon,
    type_icon_client_payload,
)
from creopdm.utils.files import format_byte_size
from creopdm.utils.folders import folder_crumbs, folder_of, folder_view_counts, normalize_folder_query
from creopdm.utils.native_dialog import native_picker_available
from creopdm.utils.timefmt import format_local, format_local_pretty

PACKAGE_DIR = Path(__file__).resolve().parent.parent
_template_env = Environment(
    loader=FileSystemLoader(str(PACKAGE_DIR / "templates")),
    autoescape=select_autoescape(),
)
_template_env.filters["local_time"] = format_local
_template_env.filters["local_time_pretty"] = format_local_pretty
_template_env.filters["byte_size"] = format_byte_size
_template_env.filters["tojson"] = lambda value: json.dumps(value, separators=(",", ":"))
_template_env.globals["local_time"] = format_local
_template_env.globals["local_time_pretty"] = format_local_pretty
_template_env.globals["byte_size"] = format_byte_size
_template_env.globals["type_icon"] = resolve_type_icon
_template_env.globals["type_label"] = display_type_label
templates = Jinja2Templates(env=_template_env)
router = APIRouter()


def _bom_lookup_keys(filename: str) -> list[str]:
    return bom_lookup_keys(filename)


def _bom_generic_label(filename: str) -> str | None:
    return bom_generic_label(filename)


def _product_bom_index(ctx: AppContext, db: Session, product_id: int) -> dict[str, str]:
    index: dict[str, str] = {}
    for row in ctx.objects.list_objects(db, product_id):
        for key in _bom_lookup_keys(row.filename):
            index.setdefault(key, row.uuid)
    return index


def _enrich_bom_tree(nodes: list, by_logical: dict[str, str]) -> list[dict]:
    enriched: list[dict] = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        item = dict(node)
        filename = str(item.get("filename") or "")
        object_id = ""
        for key in _bom_lookup_keys(filename):
            object_id = by_logical.get(key) or ""
            if object_id:
                break
        if object_id:
            item["object_id"] = object_id
            generic = _bom_generic_label(filename)
            if generic:
                item["open_as"] = generic
        children = item.get("children")
        if isinstance(children, list):
            item["children"] = _enrich_bom_tree(children, by_logical)
        enriched.append(item)
    return enriched


def _folder_page(
    ctx: AppContext,
    db: Session,
    product,
    current_folder: str,
) -> tuple[list, list[dict]]:
    """Show imported folders plus only the files that belong in this view."""
    vault_names = ctx.workspaces.list_immediate_vault_folders(product, current_folder)
    files, folder_entries = ctx.objects.list_folder_view(
        db, product.id, current_folder, vault_folder_names=vault_names
    )
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
    "checkoutable_count": 0,
    "checkin_queue": {"saves": [], "new_files": []},
    "email_notifications_enabled": False,
    "watching_product": False,
    "can_watch_product": False,
    "watch_unavailable_reason": None,
    "local_time": format_local,
    "local_time_pretty": format_local_pretty,
    "creo_label": "Session offline",
    "creo_open_name": "OS",
    "creo_open_mode": "association",
    "creo_open_title": "Opens Creo models as a browser download for the OS association",
    "native_picker": False,
    "agent_base_url": "http://127.0.0.1:8766",
    "workspace_poll_interval_ms": "5000",
    "workspace_poll_idle_minutes": "10",
}

_CREO_OPEN_NAMES = {
    "association": "OS",
    "embedded": "Embedded",
}


def render(request: Request, name: str, context: dict) -> HTMLResponse:
    templates.env.filters["local_time"] = format_local
    templates.env.filters["local_time_pretty"] = format_local_pretty
    templates.env.filters["byte_size"] = format_byte_size
    templates.env.globals["local_time"] = format_local
    templates.env.globals["local_time_pretty"] = format_local_pretty
    templates.env.globals["byte_size"] = format_byte_size
    auth_user = getattr(request.state, "auth_user", None)
    caps = caps_dict(request)
    payload = {
        "request": request,
        **_PAGE_DEFAULTS,
        "auth_user": auth_user,
        "agent_token": getattr(request.state, "agent_token", "") or "",
        **caps,
        **context,
    }
    # Role + product lock → one toolbar/gear flag set (see product_state.product_ui_capabilities).
    if "product_ui" not in payload:
        from creopdm.product_state import product_ui_capabilities

        lock_product = payload.get("selected")
        if lock_product is None:
            lock_product = payload.get("product")
        payload["product_ui"] = product_ui_capabilities(
            lock_product,
            can_add_objects=bool(payload.get("can_add_objects")),
            can_checkout=bool(payload.get("can_checkout")),
            can_force_undo_checkout=bool(payload.get("can_force_undo_checkout")),
            can_checkin=bool(payload.get("can_checkin")),
            can_remove_objects=bool(payload.get("can_remove_objects")),
            can_edit_product=bool(payload.get("can_edit_product")),
            can_delete_product=bool(payload.get("can_delete_product")),
            can_update_metadata=bool(payload.get("can_update_metadata")),
            can_revert_objects=bool(payload.get("can_revert_objects")),
        )
    try:
        return templates.TemplateResponse(request, name, payload)
    except TypeError:
        return templates.TemplateResponse(name, payload)


def _creo_label(ctx: AppContext) -> str:
    if ctx.creo.is_running():
        return "Connected"
    if ctx.creo.is_available():
        return "Installed"
    return "Session offline"


def _bundled_creojs_library() -> Path | None:
    path = PACKAGE_DIR / "static" / "vendor" / "creojs.js"
    return path if path.is_file() else None


def _creojs_library(ctx: AppContext) -> Path | None:
    local = ctx.config.config_dir / "creojs.js"
    if local.is_file():
        return local
    finder = getattr(ctx.creo, "find_creojs_library", None)
    if callable(finder):
        found = finder()
        if found is not None:
            path = Path(found)
            if path.is_file():
                return path
    return _bundled_creojs_library()


def _creo_executable(ctx: AppContext) -> str | None:
    finder = getattr(ctx.creo, "find_executable", None)
    if not callable(finder):
        return None
    found = finder()
    return str(found) if found else None


def _creo_open_mode(ctx: AppContext) -> str:
    finder = getattr(ctx.creo, "cad_open_mode", None)
    if callable(finder):
        return (finder() or "association").strip().lower()
    return (ctx.settings.creo.open_mode or "association").strip().lower()


def _creo_view_executable(ctx: AppContext) -> str | None:
    finder = getattr(ctx.creo, "find_view_executable", None)
    if not callable(finder):
        return None
    found = finder()
    return str(found) if found else None


def _creo_open_name(mode: str) -> str:
    return _CREO_OPEN_NAMES.get(mode, "OS")


def _creo_open_title(ctx: AppContext, mode: str) -> str:
    if mode == "embedded":
        return "Opens CAD in the Creo session showing this page"
    return "Opens Creo models as a browser download for the OS association"


def _watch_page_flags(request: Request, ctx: AppContext, db: Session, product) -> dict:
    email_on = bool(ctx.settings.email.enabled)
    auth_user = getattr(request.state, "auth_user", None)
    if not email_on or product is None:
        return {
            "email_notifications_enabled": email_on,
            "watching_product": False,
            "can_watch_product": False,
            "watch_unavailable_reason": None,
        }
    # Never let watch/email probes 500 the Files page (missing table, detached user, etc.).
    try:
        can_watch, reason = ctx.product_watches.watch_eligibility(auth_user, email_enabled=email_on)
        watching = False
        if auth_user is not None:
            watching = ctx.product_watches.is_watching(db, int(auth_user.id), int(product.id))
        return {
            "email_notifications_enabled": email_on,
            "watching_product": watching,
            "can_watch_product": can_watch,
            "watch_unavailable_reason": None if can_watch else reason,
        }
    except Exception:
        from creopdm.logging_setup import get_logger

        get_logger("pages").exception("product watch page flags failed")
        return {
            "email_notifications_enabled": email_on,
            "watching_product": False,
            "can_watch_product": False,
            "watch_unavailable_reason": "Product watch is temporarily unavailable.",
        }


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
        "creo_open_mode": mode,
        "creo_open_name": _creo_open_name(mode),
        "creo_open_title": _creo_open_title(ctx, mode),
        "agent_base_url": ctx.settings.ui.agent_base_url,
        "workspace_poll_interval_ms": str(ctx.settings.ui.workspace_poll_interval_ms),
        "workspace_poll_idle_minutes": str(ctx.settings.ui.workspace_poll_idle_minutes),
    }
    _CREO_PAGE_CACHE = (now, stamp, payload)
    return payload


def _sidebar_collapsed(request: Request) -> bool:
    raw = (request.cookies.get(SIDEBAR_COLLAPSED_COOKIE) or "").strip().lower()
    return raw in {"1", "true", "yes"}


_CREO_UNSUPPORTED_BROWSER_ALERT_RE = re.compile(
    r"alert\s*\(\s*['\"]The page attempts to access Creo environment which is not supported"
    r" by your browser\. Some functionalty may not be available['\"]\s*\)",
    re.IGNORECASE,
)


@router.get("/creojs.js")
def creojs_library(ctx: AppContext = Depends(get_context)) -> Response:
    """Serve Creo's Creo.JS bridge so the embedded browser can talk to this session."""
    path = _creojs_library(ctx)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Creo.JS was not found. Expected the bundled copy at "
                "static/vendor/creojs.js, a Settings path, or config/creojs.js."
            ),
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    # Outside Creo's browser this alert is normal noise; suppress it for any served copy.
    text, n = _CREO_UNSUPPORTED_BROWSER_ALERT_RE.subn("/* creo env alert suppressed */", text)
    if n == 0 and "Creo environment which is not supported" in text:
        # Fallback for odd spacing/quoting in older Creo builds.
        text = text.replace(
            "The page attempts to access Creo environment which is not supported by your browser. Some functionalty may not be available",
            "",
        )
    return Response(
        content=text,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> HTMLResponse:
    if ctx.auth_enabled:
        perms = getattr(request.state, "permissions", None) or frozenset()
        if PERMISSION_PRODUCTS_VIEW not in perms:
            # Admin-only accounts (no product browse) → Administration, not a JSON 403.
            if (
                getattr(request.state, "can_manage_users", False)
                or getattr(request.state, "can_manage_roles", False)
                or getattr(request.state, "can_manage_settings", False)
                or getattr(request.state, "can_manage_products", False)
                or getattr(request.state, "can_manage_email", False)
                or getattr(request.state, "can_assign_products", False)
                or getattr(request.state, "can_set_passwords", False)
                or getattr(request.state, "can_assign_roles", False)
            ):
                return RedirectResponse("/admin", status_code=303)
            return RedirectResponse("/no-access", status_code=303)
    products = [product_to_response(p) for p in accessible_products(request, ctx, db)]
    selected_uuid = request.query_params.get("product") or ctx.config.settings.ui.last_product_uuid
    selected = None
    status = None
    checkin_queue: dict[str, list] = {"saves": [], "new_files": []}
    product = None
    if selected_uuid:
        try:
            product = load_accessible_product(request, ctx, db, selected_uuid)
            # ARCHIVED products stay out of the normal Files list (admin restores via Administration).
            from creopdm.product_state import product_is_archived

            if product_is_archived(product):
                product = None
            else:
                selected = product_to_response(product)
        except (ProductNotFoundError, PermissionDeniedError):
            selected = None
            product = None
    if selected is None and products:
        selected = products[0]
        product = load_accessible_product(request, ctx, db, selected.uuid)
    if product is not None:
        ctx.config.remember_product(product.uuid)
        if "folder" not in request.query_params:
            remembered = ctx.config.remembered_folder(product.uuid)
            if remembered:
                return RedirectResponse(
                    url=f"/?product={quote(product.uuid)}&folder={quote(remembered)}",
                    status_code=303,
                )
        current_folder = normalize_folder_query(request.query_params.get("folder"))
        ctx.config.remember_folder(product.uuid, current_folder)
    else:
        current_folder = normalize_folder_query(request.query_params.get("folder"))
    objects: list = []
    list_entries: list = []
    checkout_count = 0
    checkoutable_count = 0
    pending_saves = 0
    new_workspace_files = 0
    if product is not None:
        objects, list_entries = _folder_page(ctx, db, product, current_folder)
        checkout_count = ctx.checkouts.count_for_product(db, product.id)
        checkoutable_count = ctx.checkouts.count_checkoutable_for_product(db, product.id)
        known = ctx.objects.list_path_index(db, product.id)
        watch = ctx.workspaces.watch_stamp(product, known)
        pending_saves = int(watch.get("pending_saves") or 0)
        new_workspace_files = int(watch.get("new_files") or 0)
    status = folder_view_counts(
        objects,
        current_folder,
        ctx.config.cad_models_extensions(),
        ctx.config.document_extensions(),
    )
    status["folders"] = sum(1 for entry in list_entries if entry.get("kind") == "folder")

    return render(
        request,
        "app.html",
        {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            **_creo_page(ctx),
            "products": products,
            "selected": selected,
            "objects": objects,
            "current_folder": current_folder,
            "folder_crumbs": folder_crumbs(current_folder),
            "list_entries": list_entries,
            "status": status,
            "cad_models_extensions": ctx.config.cad_models_extensions(),
            "cad_model_extensions": ctx.config.model_cad_extensions(),
            "document_extensions": ctx.config.document_extensions(),
            "purgeable_extensions": ctx.config.purgeable_cad_extensions(),
            "type_icons": type_icon_client_payload(ctx.config.type_labels()),
            "type_label_settings": ctx.config.type_labels(),
            "checkin_queue": checkin_queue,
            "checkout_count": checkout_count,
            "checkoutable_count": checkoutable_count,
            "pending_saves": pending_saves,
            "new_workspace_files": new_workspace_files,
            "workspace_path": str(ctx.workspaces.vault_for(selected)) if selected else None,
            "sidebar_collapsed": _sidebar_collapsed(request),
            "object_types": [item.value for item in ObjectType],
            "revision_display": revision_display,
            "native_picker": native_picker_available(),
            **_watch_page_flags(request, ctx, db, product),
        },
    )


@router.get("/products/{product_id}/objects/{object_id}", response_class=HTMLResponse)
def object_detail(
    product_id: str,
    object_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> HTMLResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    obj = ctx.objects.get_object(db, object_id)
    history = ctx.objects.object_history(db, object_id)
    payload = present_object(ctx, db, obj)
    is_assembly = obj.object_type == ObjectType.CREO_ASSEMBLY.value
    is_part = obj.object_type == ObjectType.CREO_PART.value
    is_creo = obj.object_type.startswith("CREO_")
    pending = ctx.workspaces.pending_workspace_save(product, obj)
    metadata = ctx.metadata.get(db, object_id)
    # Where Used is only meaningful for Creo Models (Settings → Creo Models chip list).
    show_where_used = matches_cad_models(
        str(obj.filename or ""),
        ctx.config.cad_models_extensions(),
        str(getattr(obj, "extension", "") or ""),
    )
    # Dependency + BOM only — vault byte scan is too slow on large products for SSR.
    # Where Used tab loads the full result (including vault scan) via API.
    where_used = (
        ctx.metadata.where_used(db, object_id, vault_scan=False)
        if show_where_used
        else None
    )
    identity = metadata.identity or {}
    materials = metadata.materials or {}
    units = metadata.units or {}
    mass = metadata.mass if isinstance(metadata.mass, dict) else None
    family_table = metadata.family_table if isinstance(metadata.family_table, dict) else {}
    features = metadata.features if isinstance(metadata.features, list) else []
    bom = metadata.bom if isinstance(metadata.bom, list) else []
    bom = _enrich_bom_tree(bom, _product_bom_index(ctx, db, product.id))
    show_mass_tab = bool(
        mass
        and (
            mass.get("mass") is not None
            or mass.get("volume") is not None
            or mass.get("density") is not None
        )
    )
    show_family_tab = bool(
        family_table.get("columns") or family_table.get("rows")
    )
    # Features = Creo feature list; Structure = assembly model tree (separate tabs).
    show_features_tab = bool(features)
    show_structure_tab = bool(is_assembly)
    checkout_count = ctx.checkouts.count_for_product(db, product.id)
    checkoutable_count = ctx.checkouts.count_checkoutable_for_product(db, product.id)
    siblings = ctx.objects.list_objects(db, product.id)
    watch = ctx.workspaces.watch_stamp(product, [(o.relative_path, o.filename) for o in siblings])
    pending_saves = int(watch.get("pending_saves") or 0)
    new_workspace_files = int(watch.get("new_files") or 0)
    return render(
        request,
        "object_detail.html",
        {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            **_creo_page(ctx),
            "product": product_to_response(product),
            "object": payload,
            "history": history,
            "workspace_pending": pending,
            "is_assembly": is_assembly,
            "is_part": is_part,
            "is_creo": is_creo,
            "metadata": metadata,
            "identity": identity,
            "materials": materials,
            "units": units,
            "mass": mass,
            "family_table": family_table,
            "features": features,
            "show_mass_tab": show_mass_tab,
            "show_family_tab": show_family_tab,
            "show_features_tab": show_features_tab,
            "show_structure_tab": show_structure_tab,
            "bom": bom,
            "show_where_used": show_where_used,
            "where_used": where_used.items if where_used is not None else [],
            "workspace_path": str(ctx.workspaces.vault_for(product)),
            "workspace_folder": folder_of(obj.relative_path),
            "checkout_count": checkout_count,
            "checkoutable_count": checkoutable_count,
            "pending_saves": pending_saves,
            "new_workspace_files": new_workspace_files,
        },
    )


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    ctx: AppContext = Depends(get_context),
) -> HTMLResponse:
    from creopdm.api.settings import settings_to_response

    if ctx.auth_enabled and not getattr(request.state, "can_manage_settings", False):
        return HTMLResponse(
            "<h1>403 Forbidden</h1><p>Only administrators can open Settings.</p>",
            status_code=403,
        )
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

    if ctx.auth_enabled and not getattr(request.state, "can_manage_settings", False):
        return HTMLResponse(
            "<h1>403 Forbidden</h1><p>Only administrators can open Settings.</p>",
            status_code=403,
        )
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
