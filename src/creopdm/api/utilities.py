"""Administration → Utilities JSON probes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from creopdm.api.deps import get_context, get_db
from creopdm.context import AppContext
from creopdm.exceptions import PermissionDeniedError
from creopdm.schemas.common import UtilitiesStatusResponse
from creopdm.services.utilities_service import collect_utilities_status

router = APIRouter()


def _require_utilities_access(request: Request, ctx: AppContext) -> None:
    if ctx.auth_enabled and not getattr(request.state, "can_access_utilities", False):
        raise PermissionDeniedError("Utilities access required (utilities.access).")


@router.get("/api/admin/utilities/status", response_model=UtilitiesStatusResponse)
def utilities_status(
    request: Request,
    ctx: AppContext = Depends(get_context),
    db: Session = Depends(get_db),
) -> UtilitiesStatusResponse:
    _require_utilities_access(request, ctx)
    return collect_utilities_status(ctx, db)
