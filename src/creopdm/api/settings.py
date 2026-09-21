from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from creopdm.api.deps import get_context
from creopdm.api.pages import clear_creo_page_cache
from creopdm.config import AppSettings
from creopdm.constants import (
    DEFAULT_CAD_MODELS_EXTENSIONS,
    DEFAULT_CREO_MODEL_EXTENSIONS,
    DEFAULT_DOCUMENT_EXTENSIONS,
    DEFAULT_EXTRA_CAD_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
    DEFAULT_OPENABLE_CAD_EXTENSIONS,
    DEFAULT_PURGEABLE_EXTENSIONS,
)
from creopdm.context import AppContext
from creopdm.creo.connector_factory import create_creo_connector
from creopdm.exceptions import PathValidationError
from creopdm.schemas.common import SettingsResponse, SettingsUpdateRequest
from creopdm.utils.classify import exclude_extensions, unique_type_labels
from creopdm.utils.paths import validate_project_location

router = APIRouter()


def _resolved_creojs(ctx: AppContext) -> Path | None:
    from creopdm.api.pages import _creojs_library

    return _creojs_library(ctx)


def settings_to_response(ctx: AppContext) -> SettingsResponse:
    settings = ctx.settings
    default_root = ctx.config.workspaces_dir
    current_root = ctx.config.workspace_root()
    resolved = _resolved_creojs(ctx)
    return SettingsResponse(
        creo_open_mode=settings.creo.open_mode,
        creo_executable=settings.creo.executable,
        creo_view_open_mode=settings.creo.view_open_mode,
        creo_view_executable=settings.creo.view_executable,
        creo_js_library=settings.creo.js_library,
        creo_js_library_resolved=str(resolved) if resolved else None,
        workspace_root=str(current_root),
        default_workspace_root=str(default_root),
        open_browser_on_start=settings.ui.open_browser_on_start,
        cad_extensions=ctx.config.extra_cad_extensions(),
        default_cad_extensions=list(DEFAULT_EXTRA_CAD_EXTENSIONS),
        cad_openable_extensions=ctx.config.openable_cad_extensions(),
        default_cad_openable_extensions=list(DEFAULT_OPENABLE_CAD_EXTENSIONS),
        cad_model_extensions=ctx.config.model_cad_extensions(),
        default_cad_model_extensions=list(DEFAULT_CREO_MODEL_EXTENSIONS),
        cad_models_extensions=ctx.config.cad_models_extensions(),
        default_cad_models_extensions=list(DEFAULT_CAD_MODELS_EXTENSIONS),
        document_extensions=ctx.config.document_extensions(),
        default_document_extensions=list(DEFAULT_DOCUMENT_EXTENSIONS),
        purgeable_extensions=ctx.config.purgeable_cad_extensions(),
        default_purgeable_extensions=list(DEFAULT_PURGEABLE_EXTENSIONS),
        type_labels=ctx.config.type_labels(),
        ignore_patterns=ctx.config.ignore_patterns(),
        default_ignore_patterns=list(DEFAULT_IGNORE_PATTERNS),
        database_url=ctx.config.database_url(),
        default_database_url=ctx.config.default_sqlite_url(),
        port=settings.server.port,
        agent_base_url=settings.ui.agent_base_url,
        workspace_poll_interval_ms=settings.ui.workspace_poll_interval_ms,
    )


def apply_settings(ctx: AppContext, settings: AppSettings) -> None:
    ctx.config.save(settings)
    ctx.settings = settings
    ctx.creo = create_creo_connector(
        settings.creo.connector,
        settings.creo.executable,
        settings.creo.open_mode,
        settings.creo.view_executable,
        settings.creo.view_open_mode,
        settings.creo.js_library,
    )
    ctx.creo_service.set_connector(ctx.creo)
    ctx.checkins.set_connector(ctx.creo)
    ctx.workspaces.sync_gitignore()
    clear_creo_page_cache()


@router.get("/api/settings", response_model=SettingsResponse)
def get_settings(ctx: AppContext = Depends(get_context)) -> SettingsResponse:
    return settings_to_response(ctx)


@router.put("/api/settings", response_model=SettingsResponse)
def update_settings(
    payload: SettingsUpdateRequest,
    ctx: AppContext = Depends(get_context),
) -> SettingsResponse:
    current = ctx.settings.model_copy(deep=True)
    current.creo.connector = "auto"
    current.creo.open_mode = payload.creo_open_mode
    executable = (payload.creo_executable or "").strip() or None
    if executable:
        path = Path(executable).expanduser()
        if not path.exists():
            raise PathValidationError(
                "The Creo application path does not exist.",
                details={"path": str(path)},
            )
        current.creo.executable = str(path)
    else:
        current.creo.executable = None
    if "creo_js_library" in payload.model_fields_set:
        js_library = (payload.creo_js_library or "").strip() or None
        if js_library:
            from creopdm.creo.windows_connector import resolve_creojs_setting

            js_path = Path(js_library).expanduser()
            # Path must be readable by this CreoPDM process to serve /creojs.js.
            # Still allow saving a path from another OS so the value is not rejected.
            if js_path.exists() and resolve_creojs_setting(js_path) is None:
                raise PathValidationError(
                    "Creo.JS was not found at that path. Point to creojs.js or a Creo install folder that contains Common Files/apps/creojs/creojsweb/creojs.js.",
                    details={"path": str(js_path)},
                )
            current.creo.js_library = str(js_path)
        else:
            current.creo.js_library = None
    if payload.creo_view_open_mode is not None:
        current.creo.view_open_mode = payload.creo_view_open_mode
    if "creo_view_executable" in payload.model_fields_set:
        view_executable = (payload.creo_view_executable or "").strip() or None
        if view_executable:
            view_path = Path(view_executable).expanduser()
            if not view_path.exists():
                raise PathValidationError(
                    "The Creo View application path does not exist.",
                    details={"path": str(view_path)},
                )
            current.creo.view_executable = str(view_path)
        else:
            current.creo.view_executable = None
    if "workspace_root" in payload.model_fields_set:
        root = (payload.workspace_root or "").strip()
        if root:
            location = validate_project_location(root)
            location.mkdir(parents=True, exist_ok=True)
            default_root = ctx.config.workspaces_dir.resolve()
            data_root = ctx.config.data_dir.resolve()
            if location == data_root:
                location = default_root
            current.workspace.root = None if location == default_root else str(location)
        else:
            current.workspace.root = None
    if payload.open_browser_on_start is not None:
        current.ui.open_browser_on_start = payload.open_browser_on_start
    if payload.cad_model_extensions is not None:
        current.cad.model_extensions = payload.cad_model_extensions
    if payload.cad_models_extensions is not None:
        current.cad.cad_models_extensions = payload.cad_models_extensions or list(
            DEFAULT_CAD_MODELS_EXTENSIONS
        )
    if payload.document_extensions is not None:
        current.cad.document_extensions = payload.document_extensions or list(
            DEFAULT_DOCUMENT_EXTENSIONS
        )
    if payload.purgeable_extensions is not None:
        current.cad.purgeable_extensions = payload.purgeable_extensions or list(
            DEFAULT_PURGEABLE_EXTENSIONS
        )
    if payload.cad_openable_extensions is not None:
        current.cad.openable_extensions = payload.cad_openable_extensions
    if payload.cad_extensions is not None:
        current.cad.extra_extensions = payload.cad_extensions
    if payload.type_labels is not None:
        current.cad.type_labels = unique_type_labels(payload.type_labels)
    current.cad.openable_extensions = exclude_extensions(
        current.cad.openable_extensions,
        current.cad.model_extensions,
    )
    current.cad.extra_extensions = exclude_extensions(
        current.cad.extra_extensions,
        (*current.cad.model_extensions, *current.cad.openable_extensions),
    )
    if payload.ignore_patterns is not None:
        current.ignore.patterns = payload.ignore_patterns
    if payload.database_url is not None:
        text = payload.database_url.strip()
        default = ctx.config.default_sqlite_url()
        current.database.url = "" if not text or text == default else text
    if payload.port is not None:
        current.server.port = payload.port
    if payload.agent_base_url is not None:
        current.ui.agent_base_url = payload.agent_base_url
    if payload.workspace_poll_interval_ms is not None:
        current.ui.workspace_poll_interval_ms = payload.workspace_poll_interval_ms
    apply_settings(ctx, current)
    return settings_to_response(ctx)
