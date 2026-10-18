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
    BaselineCompareResponse,
    BaselineCreateRequest,
    BaselineDependencyResponse,
    BaselineGitCheckResponse,
    BaselineMemberResponse,
    BaselineResponse,
)
from creopdm.utils.timefmt import as_utc

router = APIRouter()


def baseline_to_response(
    baseline: Baseline, product_uuid: str, product_name: str | None = None
) -> BaselineResponse:
    return BaselineResponse(
        uuid=baseline.uuid,
        product_uuid=product_uuid,
        product_name=product_name,
        name=baseline.name,
        description=baseline.description,
        baseline_type=baseline.baseline_type,
        status=baseline.status,
        member_count=baseline.member_count,
        dependency_count=baseline.dependency_count,
        unresolved_dependency_count=baseline.unresolved_dependency_count,
        structure_indexed=bool(baseline.structure_indexed),
        git_commit_sha=baseline.git_commit_sha,
        git_tag_name=baseline.git_tag_name,
        git_tag_status=baseline.git_tag_status or "NONE",
        git_tag_error=baseline.git_tag_error,
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
        baseline_to_response(row, product.uuid, product.name)
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
    return baseline_to_response(baseline, product.uuid, product.name)


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


@router.get("/api/baselines/{baseline_uuid}/compare", response_model=BaselineCompareResponse)
def compare_baseline(
    baseline_uuid: str,
    request: Request,
    to: str = "current",
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BaselineCompareResponse:
    """Compare this baseline with another baseline of the same product (``to=<uuid>``) or with
    the product as it is now (``to=current``, the default). Exact versions, read only."""
    require_permission(request, ctx, PERMISSION_BASELINES_VIEW)
    baseline = ctx.baselines.get(db, baseline_uuid)
    product = db.get(Product, baseline.product_id)
    require_product_access(request, ctx, product)
    target = (to or "current").strip()
    other = None if target.lower() == "current" else ctx.baselines.get(db, target)
    if other is not None:
        require_product_access(request, ctx, db.get(Product, other.product_id))
    return BaselineCompareResponse(**ctx.baselines.compare(db, baseline, other, product))


@router.get("/api/baselines/{baseline_uuid}/git-check", response_model=BaselineGitCheckResponse)
def check_baseline_git_tag(
    baseline_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BaselineGitCheckResponse:
    """Is the baseline's Git tag still on the stored commit? Reports; never changes anything."""
    require_permission(request, ctx, PERMISSION_BASELINES_VIEW)
    baseline = ctx.baselines.get(db, baseline_uuid)
    product = db.get(Product, baseline.product_id)
    require_product_access(request, ctx, product)
    return BaselineGitCheckResponse(**ctx.baselines.check_tag(product, baseline))


@router.post("/api/baselines/{baseline_uuid}/git-tag", response_model=BaselineResponse)
def retry_baseline_git_tag(
    baseline_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BaselineResponse:
    """Retry a tag that failed or is still pending. The baseline itself is not touched."""
    require_permission(request, ctx, PERMISSION_BASELINES_CREATE)
    baseline = ctx.baselines.get(db, baseline_uuid)
    product = db.get(Product, baseline.product_id)
    require_product_access(request, ctx, product)
    baseline = ctx.baselines.retry_tag(db, baseline, product)
    return baseline_to_response(baseline, product.uuid, product.name)


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
        accept_missing_structure=payload.accept_missing_structure,
        baseline_type=payload.baseline_type,
        git_tag=payload.git_tag,
    )
    return baseline_to_response(baseline, product.uuid, product.name)
