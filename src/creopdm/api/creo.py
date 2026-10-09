from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from creopdm.api.deps import get_context, get_db, load_accessible_product, require_permission, require_product_access
from creopdm.auth_constants import PERMISSION_OBJECTS_VIEW
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
        label = "Session offline"
    return CreoStatusResponse(
        connector=ctx.settings.creo.connector,
        available=available,
        running=running,
        label=label,
    )


@router.post("/api/creo/open", response_model=CreoOpenResponse)
def open_in_creo(
    payload: CreoOpenRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> CreoOpenResponse:
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    from creopdm.product_state import ensure_product_content_accessible

    if payload.object_id:
        obj = ctx.objects.get_object(db, payload.object_id)
        require_product_access(request, ctx, obj.product)
        ensure_product_content_accessible(obj.product, action="open files from this product")
        result = ctx.creo_service.open_object(
            db,
            payload.object_id,
            launch=payload.launch,
            include_dependencies=payload.include_dependencies,
        )
    else:
        product = load_accessible_product(request, ctx, db, payload.product_id or "")
        ensure_product_content_accessible(product, action="open files from this product")
        result = ctx.creo_service.open_workspace_file(
            db,
            product,
            payload.relative_path or "",
            launch=payload.launch,
            include_dependencies=payload.include_dependencies,
        )
    return CreoOpenResponse.model_validate(result)
