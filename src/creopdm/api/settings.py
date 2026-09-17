from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from creopdm.api.deps import get_context
from creopdm.config import AppSettings
from creopdm.constants import (
    DEFAULT_CAD_MODELS_EXTENSIONS,
    DEFAULT_CREO_MODEL_EXTENSIONS,
    DEFAULT_DOCUMENT_EXTENSIONS,
    DEFAULT_EXTRA_CAD_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
    DEFAULT_OPENABLE_CAD_EXTENSIONS,
)
from creopdm.context import AppContext
from creopdm.creo.connector_factory import create_creo_connector
from creopdm.exceptions import PathValidationError
from creopdm.schemas.common import SettingsResponse, SettingsUpdateRequest
from creopdm.utils.classify import exclude_extensions, unique_type_labels
from creopdm.utils.paths import validate_project_location

router = APIRouter()


def settings_to_response(ctx: AppContext) -> SettingsResponse:
    settings = ctx.settings
    default_root = ctx.config.workspaces_dir
    current_root = ctx.config.workspace_root()
    return SettingsResponse(
        creo_open_mode=settings.creo.open_mode,
        creo_executable=settings.creo.executable,
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
        type_labels=ctx.config.type_labels(),
        ignore_patterns=ctx.config.ignore_patterns(),
        default_ignore_patterns=list(DEFAULT_IGNORE_PATTERNS),
        database_url=ctx.config.database_url(),
        default_database_url=ctx.config.default_sqlite_url(),
        port=settings.server.port,
    )


def apply_settings(ctx: AppContext, settings: AppSettings) -> None:
    ctx.config.save(settings)
    ctx.settings = settings
    ctx.creo = create_creo_connector(
        settings.creo.connector,
        settings.creo.executable,
        settings.creo.open_mode,
    )
    ctx.creo_service.set_connector(ctx.creo)
    ctx.checkins.set_connector(ctx.creo)
    ctx.workspaces.sync_gitignore()


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
    root = (payload.workspace_root or "").strip()
    if root:
        location = validate_project_location(root)
        location.mkdir(parents=True, exist_ok=True)
        default_root = ctx.config.workspaces_dir.resolve()
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
    apply_settings(ctx, current)
    return settings_to_response(ctx)
