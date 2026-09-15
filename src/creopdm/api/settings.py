from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from creopdm.api.deps import get_context
from creopdm.config import AppSettings
from creopdm.constants import DEFAULT_EXTRA_CAD_EXTENSIONS
from creopdm.context import AppContext
from creopdm.creo.connector_factory import create_creo_connector
from creopdm.exceptions import PathValidationError
from creopdm.schemas.common import SettingsResponse, SettingsUpdateRequest
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
    if payload.cad_extensions is not None:
        current.cad.extra_extensions = payload.cad_extensions
    apply_settings(ctx, current)
    return settings_to_response(ctx)
