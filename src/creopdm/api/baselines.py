"""Baselines API: list and create exact, immutable configuration snapshots of a product."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from creopdm.api.deps import (
    get_context,
    get_db,
    load_accessible_product,
    require_permission,
    require_product_access,
)
from creopdm.auth_constants import PERMISSION_BASELINES_CREATE, PERMISSION_BASELINES_VIEW
from creopdm.context import AppContext
from creopdm.models.baseline import Baseline
from creopdm.models.product import Product
from creopdm.schemas.common import (
    BaselineCreateRequest,
    BaselineDependencyResponse,
    BaselineMemberResponse,
    BaselineResponse,
)
from creopdm.utils.timefmt import as_utc

router = APIRouter()


def baseline_to_response(baseline: Baseline, product_uuid: str) -> BaselineResponse:
    return BaselineResponse(
        uuid=baseline.uuid,
        product_uuid=product_uuid,
        name=baseline.name,
        description=baseline.description,
        baseline_type=baseline.baseline_type,
        status=baseline.status,
        member_count=baseline.member_count,
        dependency_count=baseline.dependency_count,
        unresolved_dependency_count=baseline.unresolved_dependency_count,
        created_by=baseline.created_by,
        created_at=as_utc(baseline.created_at),
        finalized_at=as_utc(baseline.finalized_at),
    )


@router.get("/api/products/{product_id}/baselines", response_model=list[BaselineResponse])
def list_baselines(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[BaselineResponse]:
    require_permission(request, ctx, PERMISSION_BASELINES_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    return [
        baseline_to_response(row, product.uuid)
        for row in ctx.baselines.list_for_product(db, product)
    ]


@router.get("/api/baselines/{baseline_uuid}", response_model=BaselineResponse)
def get_baseline(
    baseline_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BaselineResponse:
    """One baseline, found by its uuid (the name is never used to look a baseline up)."""
    require_permission(request, ctx, PERMISSION_BASELINES_VIEW)
    baseline = ctx.baselines.get(db, baseline_uuid)
    product = db.get(Product, baseline.product_id)
    require_product_access(request, ctx, product)
    return baseline_to_response(baseline, product.uuid)


@router.get("/api/baselines/{baseline_uuid}/members", response_model=list[BaselineMemberResponse])
def list_baseline_members(
    baseline_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[BaselineMemberResponse]:
    """Every exact version in the baseline, with the two uuids that identify it."""
    require_permission(request, ctx, PERMISSION_BASELINES_VIEW)
    baseline = ctx.baselines.get(db, baseline_uuid)
    require_product_access(request, ctx, db.get(Product, baseline.product_id))
    return [BaselineMemberResponse(**row) for row in ctx.baselines.members(db, baseline)]


@router.get(
    "/api/baselines/{baseline_uuid}/dependencies", response_model=list[BaselineDependencyResponse]
)
def list_baseline_dependencies(
    baseline_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[BaselineDependencyResponse]:
    """The structure captured with the baseline (stored edges, never recomputed)."""
    require_permission(request, ctx, PERMISSION_BASELINES_VIEW)
    baseline = ctx.baselines.get(db, baseline_uuid)
    require_product_access(request, ctx, db.get(Product, baseline.product_id))
    return [BaselineDependencyResponse(**row) for row in ctx.baselines.dependencies(db, baseline)]


@router.post("/api/products/{product_id}/baselines", response_model=BaselineResponse, status_code=201)
def create_baseline(
    product_id: str,
    payload: BaselineCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BaselineResponse:
    """Capture the product's current configuration: every file's exact current version."""
    require_permission(request, ctx, PERMISSION_BASELINES_CREATE)
    product = load_accessible_product(request, ctx, db, product_id)
    baseline = ctx.baselines.create(
        db,
        product,
        payload.name,
        payload.description,
        payload.operation_id,
    )
    return baseline_to_response(baseline, product.uuid)
