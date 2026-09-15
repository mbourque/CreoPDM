from __future__ import annotations

from fastapi import APIRouter

from creopdm.constants import APP_NAME, APP_VERSION
from creopdm.schemas.common import HealthResponse

router = APIRouter()


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", name=APP_NAME, version=APP_VERSION)
