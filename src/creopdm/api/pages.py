"""HTML pages served to the local browser GUI."""

from __future__ import annotations

import json
import re
from pathlib import Path
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
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
from creopdm.utils.mass_format import format_mass_value
from creopdm.services.metadata_service import normalize_feature_rows
from creopdm.utils.bom_match import bom_generic_label, bom_lookup_keys, format_bom_qty
from creopdm.utils.classify import (
    display_type_label,
    matches_cad_models,
    resolve_type_icon,
    type_icon_client_payload,
)
from creopdm.utils.creo_model_class import creo_subtype_display, model_type_display
from creopdm.utils.sketch_metadata import sketch_error, sketch_overview
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
_template_env.filters["bom_qty"] = format_bom_qty
_template_env.filters["tojson"] = lambda value: json.dumps(value, separators=(",", ":"))
_template_env.globals["local_time"] = format_local
_template_env.globals["local_time_pretty"] = format_local_pretty
_template_env.globals["byte_size"] = format_byte_size
_template_env.globals["bom_qty"] = format_bom_qty
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


def _enrich_structure_rows(rows: list, by_logical: dict[str, str]) -> list[dict]:
    """Attach product object_id so Structure tip names open like BOM links."""
    enriched: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        filename = str(
            item.get("name")
            or item.get("filename")
            or item.get("file_name")
            or item.get("fileName")
            or ""
        ).strip()
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
    "my_checkout_count": 0,
    "baseline_count": 0,
    "baseline_total": 0,
    "checkoutable_count": 0,
    "checkin_queue": {"saves": [], "new_files": []},
    "email_notifications_enabled": False,
    "watching_product": False,
    "can_watch_product": False,
    "watch_unavailable_reason": None,
    "where_used_present": False,
    "top_level_assembly_uuids": [],
    "product_object_count": 0,
    "is_top_level_assembly": False,
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
    "site_unavailable": False,
    "site_unavailable_message": "",
    "ai_enabled": True,
}

_CREO_OPEN_NAMES = {
    "association": "OS",
    "embedded": "Embedded",
}


def render(request: Request, name: str, context: dict) -> HTMLResponse:
    from creopdm.site_availability import site_is_unavailable, site_unavailable_message

    templates.env.filters["local_time"] = format_local
    templates.env.filters["local_time_pretty"] = format_local_pretty
    templates.env.filters["byte_size"] = format_byte_size
    templates.env.filters["bom_qty"] = format_bom_qty
    templates.env.filters["mass_num"] = format_mass_value
    templates.env.globals["local_time"] = format_local
    templates.env.globals["local_time_pretty"] = format_local_pretty
    templates.env.globals["byte_size"] = format_byte_size
    templates.env.globals["bom_qty"] = format_bom_qty
    templates.env.globals["mass_num"] = format_mass_value
    auth_user = getattr(request.state, "auth_user", None)
    caps = caps_dict(request)
    ctx = getattr(request.app.state, "ctx", None)
    settings = getattr(ctx, "settings", None) if ctx is not None else None
    unavailable = bool(settings and site_is_unavailable(settings))
    ai_enabled = True if settings is None else bool(getattr(settings.ai, "enabled", True))
    # Details has no #metric-filters — body data-purgeable keeps Creo .ext.N tip math working.
    purgeable = []
    if ctx is not None and hasattr(ctx, "config"):
        try:
            purgeable = list(ctx.config.purgeable_cad_extensions() or [])
        except Exception:
            purgeable = []
    payload = {
        "request": request,
        **_PAGE_DEFAULTS,
        "auth_user": auth_user,
        "agent_token": getattr(request.state, "agent_token", "") or "",
        **caps,
        "site_unavailable": unavailable,
        "site_unavailable_message": (
            site_unavailable_message(settings) if settings is not None else ""
        ),
        "ai_enabled": ai_enabled,
        "purgeable_extensions": purgeable,
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
            can_view_objects=bool(payload.get("can_view_objects")),
            can_export_product=bool(payload.get("can_export_product")),
            can_export_objects=bool(payload.get("can_export_objects")),
            can_copy_to_vault=bool(payload.get("can_copy_to_vault")),
            can_remove_objects=bool(payload.get("can_remove_objects")),
            can_edit_product=bool(payload.get("can_edit_product")),
            can_delete_product=bool(payload.get("can_delete_product")),
            can_update_metadata=bool(payload.get("can_update_metadata")),
            can_revert_objects=bool(payload.get("can_revert_objects")),
            can_revise_objects=bool(payload.get("can_revise_objects")),
        )
    if "product_state_description" not in payload:
        from creopdm.product_state import (
            configured_product_state_descriptions,
            product_state_value,
        )

        # Files uses selected; Details uses product — either carries state.
        selected = payload.get("selected")
        if selected is None:
            selected = payload.get("product")
        desc = ""
        if selected is not None:
            key = product_state_value(selected)
            desc = (configured_product_state_descriptions().get(key) or "").strip()
        payload["product_state_description"] = desc
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
                or getattr(request.state, "can_manage_ai", False)
                or getattr(request.state, "can_manage_products", False)
                or getattr(request.state, "can_manage_lifecycle_states", False)
                or getattr(request.state, "can_manage_email", False)
                or getattr(request.state, "can_access_utilities", False)
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
                # Preserve navigator deep-link select/action across the folder redirect.
                q = [f"product={quote(product.uuid)}", f"folder={quote(remembered)}"]
                select = (request.query_params.get("select") or "").strip()
                action = (request.query_params.get("action") or "").strip()
                if select:
                    q.append(f"select={quote(select)}")
                if action:
                    q.append(f"action={quote(action)}")
                return RedirectResponse(url="/?" + "&".join(q), status_code=303)
        current_folder = normalize_folder_query(request.query_params.get("folder"))
        ctx.config.remember_folder(product.uuid, current_folder)
    else:
        current_folder = normalize_folder_query(request.query_params.get("folder"))
    objects: list = []
    list_entries: list = []
    checkout_count = 0
    my_checkout_count = 0
    baseline_count = 0
    baseline_total = 0
    checkoutable_count = 0
    pending_saves = 0
    new_workspace_files = 0
    product_object_count = 0
    if product is not None:
        objects, list_entries = _folder_page(ctx, db, product, current_folder)
        checkout_count = ctx.checkouts.count_for_product(db, product.id)
        my_checkout_count = ctx.checkouts.count_for_product(
            db, product.id, ctx.users.get_current_user().user_name
        )
        checkoutable_count = ctx.checkouts.count_checkoutable_for_product(db, product.id)
        baseline_count = ctx.baselines.count_for_product(db, product.id)
        # Archived baselines still block a delete from this page, so the Delete dialog counts them.
        baseline_total = ctx.baselines.count_for_product(db, product.id, include_archived=True)
        known = ctx.objects.list_path_index(db, product.id)
        product_object_count = len(known)
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
    where_used_present = False
    top_level_assembly_uuids: list[str] = []
    if product is not None:
        where_used_present = ctx.metadata.where_used_index_present(db, product.id)
        if where_used_present:
            top_level_assembly_uuids = ctx.metadata.top_level_assembly_uuids(db, product.id)
            top_set = set(top_level_assembly_uuids)
            status["top_level_assemblies"] = sum(
                1 for obj in objects if getattr(obj, "uuid", None) in top_set
            )
        else:
            status["top_level_assemblies"] = 0

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
            "product_object_count": product_object_count,
            "where_used_present": where_used_present,
            "top_level_assembly_uuids": top_level_assembly_uuids,
            "cad_models_extensions": ctx.config.cad_models_extensions(),
            "cad_model_extensions": ctx.config.model_cad_extensions(),
            "non_openable_extensions": ctx.config.extra_cad_extensions(),
            "document_extensions": ctx.config.document_extensions(),
            "purgeable_extensions": ctx.config.purgeable_cad_extensions(),
            "type_icons": type_icon_client_payload(ctx.config.type_labels()),
            "type_label_settings": ctx.config.type_labels(),
            "checkin_queue": checkin_queue,
            "checkout_count": checkout_count,
            "my_checkout_count": my_checkout_count,
            "baseline_count": baseline_count,
            "baseline_total": baseline_total,
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
    return _object_detail_page(request, ctx, db, product_id, object_id)


def _frozen_where_used(ctx: AppContext, db: Session, baseline, version_uuid: str, product_uuid: str):
    """Parents of one version as the baseline froze them, and whether it is a top-level assembly."""
    members = {m["version_uuid"]: m for m in ctx.baselines.members(db, baseline)}
    rows: list[dict] = []
    used_by_assembly = False
    for edge in ctx.baselines.dependencies(db, baseline):
        if edge.get("child_version_uuid") != version_uuid:
            continue
        parent = members.get(edge["parent_version_uuid"]) or {}
        if str(parent.get("object_type") or "").upper() == ObjectType.CREO_ASSEMBLY.value:
            used_by_assembly = True
        object_uuid = parent.get("object_uuid") or ""
        rows.append(
            {
                "object_id": object_uuid,
                "filename": edge["parent_filename"],
                "relative_path": parent.get("relative_path") or "",
                "type_label": str(parent.get("object_type") or "").replace("CREO_", "").title(),
                "display_revision": edge.get("parent_display_version") or "",
                "quantity": edge.get("quantity") or 1.0,
                "dependency_type": edge.get("dependency_type") or "",
                "href": (
                    f"/products/{product_uuid}/objects/{object_uuid}/versions/"
                    f"{edge['parent_version_uuid']}?baseline={baseline.uuid}"
                    if object_uuid
                    else ""
                ),
            }
        )
    return rows, used_by_assembly


def _object_detail_page(
    request: Request,
    ctx: AppContext,
    db: Session,
    product_id: str,
    object_id: str,
    version_id: str | None = None,
) -> HTMLResponse:
    """Details of a file: its current state, or ONE exact version of it (``version_id``).

    The exact-version form is what a baseline member opens: the same page and tabs, read from the
    version's own stored metadata, never redirected to the current version.
    """
    from sqlalchemy import select

    from creopdm.exceptions import ObjectNotFoundError
    from creopdm.models.version import ObjectVersion

    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    obj = ctx.objects.get_object(db, object_id)
    version = None
    from_baseline = None
    baseline_row = None
    if version_id:
        if obj.product_id != product.id:
            raise ObjectNotFoundError("Object not found in this product.", details={"object": object_id})
        version = db.scalar(
            select(ObjectVersion).where(
                ObjectVersion.uuid == (version_id or "").strip(),
                ObjectVersion.object_id == obj.id,
            )
        )
        if version is None:
            raise ObjectNotFoundError(
                "That version does not belong to this file.", details={"version": version_id}
            )
        # Opened from a baseline's file list: breadcrumbs lead back, Where Used is the frozen one.
        baseline_uuid = (request.query_params.get("baseline") or "").strip()
        if baseline_uuid and caps_dict(request).get("can_view_baselines"):
            try:
                candidate = ctx.baselines.get(db, baseline_uuid)
                if candidate.product_id == product.id:
                    baseline_row = candidate
                    from_baseline = {
                        "uuid": candidate.uuid,
                        "name": candidate.name,
                        "workspace_folder": ctx.baselines.workspace_folder(candidate),
                    }
            except Exception:
                baseline_row = None
                from_baseline = None
    history = ctx.objects.object_history(db, object_id)
    payload = present_object(ctx, db, obj)
    version_view = None
    if version is not None:
        from creopdm.api.serializers import version_to_response
        from creopdm.constants import LifecycleState

        current = obj.current_version
        display = f"{version.revision}.{version.iteration}"
        # The file as it was at this version: nothing about checkout or the vault applies.
        payload = payload.model_copy(
            update={
                "revision": version.revision,
                "iteration": version.iteration,
                "display_revision": display,
                "lifecycle_state": version.lifecycle_state or LifecycleState.IN_WORK.value,
                "creo_release": version.creo_release,
                "checkout_status": "",
                "checkout_user": None,
                "checkout_since": None,
                "owned_by_me": False,
                "modified_locally": False,
                "can_checkout": False,
                "can_checkin": False,
                "can_revise": False,
                "updated_at": version.created_at,
                "current_version": version_to_response(version),
            }
        )
        version_view = {
            "uuid": version.uuid,
            "display": display,
            "is_current": current is not None and current.id == version.id,
            "current_display": f"{current.revision}.{current.iteration}" if current is not None else "",
            "lifecycle_label": (version.lifecycle_state or LifecycleState.IN_WORK.value)
            .replace("_", " ")
            .title(),
            "created_by": version.created_by,
            "created_at": version.created_at,
            "comment": version.comment,
            "content_hash": version.content_hash,
            "relative_path": version.relative_path or obj.relative_path,
            "git_commit": version.git_commit_hash,
            "baseline": from_baseline,
        }
    is_assembly = obj.object_type == ObjectType.CREO_ASSEMBLY.value
    is_part = obj.object_type == ObjectType.CREO_PART.value
    is_creo = obj.object_type.startswith("CREO_")
    pending = ctx.workspaces.pending_workspace_save(product, obj) if version is None else None
    metadata_note = ""
    if baseline_row is not None and version is not None:
        # A baseline shows the metadata it copied when it was made, never today's.
        from creopdm.models.baseline import BaselineMember

        member = db.scalar(
            select(BaselineMember).where(
                BaselineMember.baseline_id == baseline_row.id,
                BaselineMember.object_version_id == version.id,
            )
        )
        metadata = ctx.metadata.response_from_snapshot(
            obj.uuid, version.uuid, member.metadata_json if member is not None else None
        )
        if not metadata.captured:
            metadata_note = (
                "No Creo metadata was kept with this baseline for this file: none had been "
                "collected for this version when the baseline was made."
            )
    else:
        metadata = ctx.metadata.get(db, object_id, version.uuid if version is not None else None)
    # Where Used is only meaningful for Creo Models (Settings → Creo Models chip list).
    show_where_used = matches_cad_models(
        str(obj.filename or ""),
        ctx.config.cad_models_extensions(),
        str(getattr(obj, "extension", "") or ""),
    )
    # Dependency + BOM only — vault byte scan is too slow on large products for SSR.
    # Where Used tab loads the full result (including vault scan) via API.
    where_used = None
    where_used_rows: list = []
    is_top_level_assembly = False
    if version is None:
        where_used = (
            ctx.metadata.where_used(db, object_id, vault_scan=False)
            if show_where_used
            else None
        )
        where_used_rows = where_used.items if where_used is not None else []
        if is_assembly and ctx.metadata.where_used_index_present(db, product.id):
            is_top_level_assembly = str(obj.uuid) in set(
                ctx.metadata.top_level_assembly_uuids(db, product.id)
            )
    elif baseline_row is not None and show_where_used:
        # The structure the baseline froze: nothing is looked up in today's product.
        where_used_rows, used_by_assembly = _frozen_where_used(
            ctx, db, baseline_row, version.uuid, product.uuid
        )
        is_top_level_assembly = bool(is_assembly and not used_by_assembly)
    else:
        # A historical version outside a baseline has no frozen structure to show.
        show_where_used = False
    identity = metadata.identity or {}
    # Creo 2D section (.sec): Toolkit sketch domain → Overview rows + Sketch tab.
    sketch_view = sketch_overview(metadata.sketch if isinstance(metadata.sketch, dict) else None)
    materials = metadata.materials or {}
    units = metadata.units or {}
    mass = metadata.mass if isinstance(metadata.mass, dict) else None
    family_table = metadata.family_table if isinstance(metadata.family_table, dict) else {}
    features = normalize_feature_rows(
        metadata.features if isinstance(metadata.features, list) else []
    )
    structure = (
        metadata.structure if isinstance(metadata.structure, list) else []
    )
    bom = metadata.bom if isinstance(metadata.bom, list) else []
    is_drawing = obj.object_type == ObjectType.CREO_DRAWING.value
    product_index = _product_bom_index(ctx, db, product.id)
    bom = _enrich_bom_tree(bom, product_index)
    structure = _enrich_structure_rows(structure, product_index)
    show_mass_tab = bool(
        mass
        and (
            mass.get("mass") is not None
            or mass.get("volume") is not None
            or mass.get("density") is not None
            or mass.get("surface_area") is not None
            or mass.get("gravity_center") is not None
            or mass.get("principal_moments") is not None
        )
    )
    show_family_tab = bool(
        family_table.get("columns") or family_table.get("rows")
    )
    # Features = Creo inventory list; Structure = assembly component tree (separate tabs).
    show_features_tab = bool(features)
    show_structure_tab = bool(is_assembly)
    # Modifications tab when ≥1 saved snap: tip-only = pending NEW; 2+ = history compare.
    snapshot_count = (
        ctx.ai_snapshots.count_with_snapshot(db, object_id) if is_creo and version is None else 0
    )
    show_snapshot_tab = bool(is_creo and snapshot_count >= 1)
    snapshot_tab_label = "Modifications"
    snapshot_tab_mode = "compare" if snapshot_count >= 2 else "pending"
    checkout_count = ctx.checkouts.count_for_product(db, product.id)
    my_checkout_count = ctx.checkouts.count_for_product(
        db, product.id, ctx.users.get_current_user().user_name
    )
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
            "is_top_level_assembly": is_top_level_assembly,
            "is_part": is_part,
            "is_creo": is_creo,
            "metadata": metadata,
            "identity": identity,
            # Toolkit identity.subtype + model_role (None → show what Overview showed before).
            "subtype_display": creo_subtype_display(identity),
            # Overview "Model type": a 2D section reads SKETCH.
            "model_type_label": model_type_display(identity.get("model_type")),
            "sketch_view": sketch_view,
            "sketch_error": sketch_error(metadata.sketch),
            "show_sketch_tab": bool(sketch_view),
            "materials": materials,
            "units": units,
            "mass": mass,
            "family_table": family_table,
            "features": features,
            "structure": structure,
            "is_drawing": is_drawing,
            "show_mass_tab": show_mass_tab,
            "show_family_tab": show_family_tab,
            "show_features_tab": show_features_tab,
            "show_structure_tab": show_structure_tab,
            "show_snapshot_tab": show_snapshot_tab,
            "snapshot_tab_label": snapshot_tab_label,
            "snapshot_tab_mode": snapshot_tab_mode,
            "bom": bom,
            "show_where_used": show_where_used,
            "where_used": where_used_rows,
            "version_view": version_view,
            "metadata_note": metadata_note,
            "from_baseline": from_baseline,
            "workspace_path": str(ctx.workspaces.vault_for(product)),
            "workspace_folder": folder_of(obj.relative_path),
            "checkout_count": checkout_count,
            "my_checkout_count": my_checkout_count,
            "checkoutable_count": checkoutable_count,
            "pending_saves": pending_saves,
            "new_workspace_files": new_workspace_files,
        },
    )


@router.get(
    "/products/{product_id}/objects/{object_id}/versions/{version_id}",
    response_class=HTMLResponse,
)
def object_version_detail(
    product_id: str,
    object_id: str,
    version_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> HTMLResponse:
    """One EXACT historical version, by its version uuid. Never redirects to the current version:
    a baseline member opens the version it captured even when the file is at C.4 now. It is the
    ordinary Details page (same tabs), read from that version."""
    return _object_detail_page(request, ctx, db, product_id, object_id, version_id)


@router.get("/help")
def user_help_page() -> FileResponse:
    """Standalone user help (opened from the top-bar Help pill in a named tab)."""
    path = PACKAGE_DIR / "static" / "help" / "index.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Help page is not available.")
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/help/admin")
def admin_help_page(request: Request) -> FileResponse:
    """How to administrate CreoPDM — opened from the Help pill on Administration / System Settings."""
    if not caps_dict(request).get("can_open_administration"):
        raise HTTPException(status_code=403, detail="Administrator help is for administrators.")
    path = PACKAGE_DIR / "static" / "help" / "admin.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Administrator help is not available.")
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/help/agent-tray", response_class=HTMLResponse)
def agent_tray_help_page(request: Request) -> HTMLResponse:
    """Start / download / Windows autostart for creopdm-agent-tray (Agent offline pill)."""
    ctx: AppContext = request.app.state.ctx
    tray_path = ctx.config.agent_tray_exe_path()
    return render(
        request,
        "help_agent_tray.html",
        {
            "agent_tray_available": tray_path.is_file(),
            "agent_tray_name": ctx.config.AGENT_TRAY_DOWNLOAD_NAME,
        },
    )


def _require_settings_page(request: Request, ctx: AppContext) -> HTMLResponse | None:
    if ctx.auth_enabled and not getattr(request.state, "can_manage_settings", False):
        return HTMLResponse(
            "<h1>403 Forbidden</h1><p>Only administrators can open Settings.</p>",
            status_code=403,
        )
    return None


def _require_ai_settings_page(request: Request, ctx: AppContext) -> HTMLResponse | None:
    if ctx.auth_enabled and not getattr(request.state, "can_manage_ai", False):
        return HTMLResponse(
            "<h1>403 Forbidden</h1><p>AI settings access required (settings.ai).</p>",
            status_code=403,
        )
    return None


def _require_availability_settings_page(request: Request, ctx: AppContext) -> HTMLResponse | None:
    if not ctx.auth_enabled:
        return None
    if getattr(request.state, "can_manage_settings", False) or getattr(
        request.state, "can_utilities_availability", False
    ):
        return None
    return HTMLResponse(
        "<h1>403 Forbidden</h1><p>Availability or Settings access required "
        "(utilities.availability or settings.manage).</p>",
        status_code=403,
    )


def _can_open_settings_hub(request: Request, ctx: AppContext) -> bool:
    if not ctx.auth_enabled:
        return True
    return bool(
        getattr(request.state, "can_manage_settings", False)
        or getattr(request.state, "can_manage_ai", False)
        or getattr(request.state, "can_manage_email", False)
        or getattr(request.state, "can_utilities_availability", False)
    )


def _settings_hub_tiles(request: Request, ctx: AppContext):
    from creopdm.settings_hub import SETTINGS_HUB_TILES

    can_settings = not ctx.auth_enabled or bool(
        getattr(request.state, "can_manage_settings", False)
    )
    can_ai = not ctx.auth_enabled or bool(getattr(request.state, "can_manage_ai", False))
    can_email = not ctx.auth_enabled or bool(
        getattr(request.state, "can_manage_email", False)
    )
    can_availability = not ctx.auth_enabled or bool(
        getattr(request.state, "can_utilities_availability", False)
        or can_settings
    )
    tiles = []
    for tile in SETTINGS_HUB_TILES:
        if tile.slug == "ai":
            if can_ai:
                tiles.append(tile)
        elif tile.slug == "email":
            if can_email:
                tiles.append(tile)
        elif tile.slug == "availability":
            if can_availability:
                tiles.append(tile)
        elif can_settings:
            tiles.append(tile)
    return tuple(tiles)


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    ctx: AppContext = Depends(get_context),
) -> HTMLResponse:
    if ctx.auth_enabled and not _can_open_settings_hub(request, ctx):
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
            "settings_tiles": _settings_hub_tiles(request, ctx),
        },
    )


@router.get("/settings/{section}", response_class=HTMLResponse)
def settings_section_page(
    section: str,
    request: Request,
    ctx: AppContext = Depends(get_context),
) -> HTMLResponse:
    from creopdm.api.settings import settings_to_response
    from creopdm.settings_hub import settings_tile

    slug = (section or "").strip().lower()
    # Email is owned by auth_pages (/settings/email) — registered before this router.
    if slug == "email":
        return RedirectResponse("/settings/email", status_code=303)
    if slug == "availability":
        blocked = _require_availability_settings_page(request, ctx)
    elif slug == "ai":
        blocked = _require_ai_settings_page(request, ctx)
    else:
        blocked = _require_settings_page(request, ctx)
    if blocked is not None:
        return blocked
    tile = settings_tile(section)
    if tile is None:
        return HTMLResponse("<h1>404 Not Found</h1><p>Unknown System Settings page.</p>", status_code=404)
    if tile.page_template:
        return render(
            request,
            tile.page_template,
            {
                "app_name": APP_NAME,
                "app_version": APP_VERSION,
                **_creo_page(ctx),
                "settings": settings_to_response(ctx),
                "section": tile,
            },
        )
    return render(
        request,
        "settings_section.html",
        {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            **_creo_page(ctx),
            "settings": settings_to_response(ctx),
            "section": tile,
        },
    )
