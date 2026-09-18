from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from creopdm.api.deps import get_context, get_db
from creopdm.context import AppContext
from creopdm.schemas.common import CreoOpenRequest, CreoOpenResponse, CreoStatusResponse

router = APIRouter()


@router.get("/api/creo/status", response_model=CreoStatusResponse)
def creo_status(ctx: AppContext = Depends(get_context)) -> CreoStatusResponse:
    available = ctx.creo.is_available()
    running = ctx.creo.is_running()
    if running:
        label = "Connected"
    elif available:
        label = "Installed"
    else:
        label = "Not Connected"
    return CreoStatusResponse(
        connector=ctx.settings.creo.connector,
        available=available,
        running=running,
        label=label,
    )


@router.post("/api/creo/open", response_model=CreoOpenResponse)
def open_in_creo(
    payload: CreoOpenRequest,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> CreoOpenResponse:
    if payload.object_id:
        result = ctx.creo_service.open_object(db, payload.object_id, launch=payload.launch)
    else:
        project = ctx.projects.get_project(db, payload.project_id or "")
        result = ctx.creo_service.open_workspace_file(
            project, payload.relative_path or "", launch=payload.launch
        )
    return CreoOpenResponse.model_validate(result)
