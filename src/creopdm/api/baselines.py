"""Baselines API: list and create exact, immutable configuration snapshots of a product."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from creopdm.api.deps import (
    get_context,
    get_db,
    load_accessible_product,
    refuse_for_template,
    require_permission,
    require_product_access,
)
from creopdm.auth_constants import (
    PERMISSION_BASELINES_ADMIN,
    PERMISSION_BASELINES_CREATE,
    PERMISSION_BASELINES_VIEW,
)
from creopdm.context import AppContext
from creopdm.models.baseline import Baseline
from creopdm.services.baseline_service import BaselineService
from creopdm.models.product import Product
from creopdm.schemas.common import (
    BaselineAdminList,
    BaselineArchiveRequest,
    BaselineCompareResponse,
    BaselineIntegrityReport,
    BaselineCreateRequest,
    BaselineDependencyResponse,
    BaselineGitCheckResponse,
    BaselineMemberResponse,
    BaselineResponse,
    BaselineWorkspaceManifest,
    ProductReleaseResponse,
)
from creopdm.utils.timefmt import as_utc

router = APIRouter()


def baseline_to_response(
    baseline: Baseline,
    product_uuid: str,
    product_name: str | None = None,
    release_label: str | None = None,
) -> BaselineResponse:
    return BaselineResponse(
        uuid=baseline.uuid,
        product_uuid=product_uuid,
        product_name=product_name,
        release_label=release_label,
        name=baseline.name,
        description=baseline.description,
        baseline_type=baseline.baseline_type,
        status=baseline.status,
        member_count=baseline.member_count,
        dependency_count=baseline.dependency_count,
        unresolved_dependency_count=baseline.unresolved_dependency_count,
        structure_indexed=bool(baseline.structure_indexed),
        git_commit_sha=baseline.git_commit_sha,
        workspace_folder=BaselineService.workspace_folder(baseline),
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
    include_archived: bool = False,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[BaselineResponse]:
    require_permission(request, ctx, PERMISSION_BASELINES_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    rows = ctx.baselines.list_for_product(db, product, include_archived=include_archived)
    labels = ctx.baselines.release_labels(db, [row.id for row in rows])
    return [
        baseline_to_response(row, product.uuid, product.name, labels.get(row.id)) for row in rows
    ]


@router.get("/api/products/{product_id}/releases", response_model=list[ProductReleaseResponse])
def list_product_releases(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[ProductReleaseResponse]:
    """The product's releases (R1, R2, ...), newest first, each with the exact baseline it
    released. Rebuild an old release by downloading that baseline."""
    require_permission(request, ctx, PERMISSION_BASELINES_VIEW)
    product = load_accessible_product(request, ctx, db, product_id)
    return [ProductReleaseResponse(**row) for row in ctx.baselines.list_releases(db, product)]


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
    labels = ctx.baselines.release_labels(db, [baseline.id])
    return baseline_to_response(baseline, product.uuid, product.name, labels.get(baseline.id))


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


@router.get("/api/admin/baselines", response_model=BaselineAdminList)
def admin_list_baselines(
    request: Request,
    q: str = "",
    type: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BaselineAdminList:
    """Administration → Baselines: every baseline of every product, with overall counts."""
    require_permission(request, ctx, PERMISSION_BASELINES_ADMIN)
    return BaselineAdminList(
        summary=ctx.baselines.admin_summary(db),
        items=ctx.baselines.admin_list(db, q=q, baseline_type=type, status=status),
    )


@router.post("/api/admin/baselines/integrity", response_model=list[BaselineIntegrityReport])
def admin_check_all_baselines(
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> list[BaselineIntegrityReport]:
    """A quick integrity check of every baseline (no hashing). Read only."""
    require_permission(request, ctx, PERMISSION_BASELINES_ADMIN)
    return [BaselineIntegrityReport(**row) for row in ctx.baselines.integrity_all(db)]


@router.post("/api/baselines/{baseline_uuid}/integrity", response_model=BaselineIntegrityReport)
def admin_check_baseline(
    baseline_uuid: str,
    request: Request,
    deep: bool = False,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BaselineIntegrityReport:
    """Integrity of one baseline; ``deep=true`` also verifies every file's SHA-256."""
    require_permission(request, ctx, PERMISSION_BASELINES_ADMIN)
    baseline = ctx.baselines.get(db, baseline_uuid)
    product = db.get(Product, baseline.product_id)
    return BaselineIntegrityReport(**ctx.baselines.integrity(db, baseline, product, deep=deep))


@router.post("/api/baselines/{baseline_uuid}/archive", response_model=BaselineResponse)
def admin_archive_baseline(
    baseline_uuid: str,
    request: Request,
    payload: BaselineArchiveRequest | None = None,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BaselineResponse:
    """Archive a finalized baseline (hidden from everyday use, never deleted, restorable).

    Needs the signed-in user's password, like the other confirmed administration actions.
    """
    from creopdm.utils.danger_confirm import require_danger_password

    require_permission(request, ctx, PERMISSION_BASELINES_ADMIN)
    require_danger_password(
        ctx,
        db,
        payload.confirm_password if payload is not None else "",
        auth_user=getattr(request.state, "auth_user", None),
    )
    baseline = ctx.baselines.get(db, baseline_uuid)
    product = db.get(Product, baseline.product_id)
    baseline = ctx.baselines.archive(db, baseline, product)
    return baseline_to_response(baseline, product.uuid, product.name)


@router.post("/api/baselines/{baseline_uuid}/restore", response_model=BaselineResponse)
def admin_restore_baseline(
    baseline_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BaselineResponse:
    require_permission(request, ctx, PERMISSION_BASELINES_ADMIN)
    baseline = ctx.baselines.get(db, baseline_uuid)
    product = db.get(Product, baseline.product_id)
    baseline = ctx.baselines.restore(db, baseline, product)
    return baseline_to_response(baseline, product.uuid, product.name)


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


@router.get(
    "/api/baselines/{baseline_uuid}/workspace-manifest", response_model=BaselineWorkspaceManifest
)
def baseline_workspace_manifest(
    baseline_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> BaselineWorkspaceManifest:
    """The exact versions (and SHA-256s) to rebuild this baseline on a workstation. Refused, with
    every missing member named, when any exact content is unavailable: nothing is substituted."""
    from creopdm.product_state import ensure_product_content_accessible

    require_permission(request, ctx, PERMISSION_BASELINES_VIEW)
    baseline = ctx.baselines.get(db, baseline_uuid)
    product = db.get(Product, baseline.product_id)
    require_product_access(request, ctx, product)
    ensure_product_content_accessible(product, action="download files from this product")
    return BaselineWorkspaceManifest(**ctx.baselines.workspace_manifest(db, baseline, product))


@router.get("/api/baselines/{baseline_uuid}/versions/{version_uuid}/content")
def baseline_member_content(
    baseline_uuid: str,
    version_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> Response:
    """The exact bytes of one version captured by this baseline (hash-checked before sending)."""
    from creopdm.product_state import ensure_product_content_accessible

    require_permission(request, ctx, PERMISSION_BASELINES_VIEW)
    baseline = ctx.baselines.get(db, baseline_uuid)
    product = db.get(Product, baseline.product_id)
    require_product_access(request, ctx, product)
    ensure_product_content_accessible(product, action="download files from this product")
    data, filename, digest = ctx.baselines.member_content(db, baseline, product, version_uuid)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "X-Content-SHA256": digest,
            "Cache-Control": "no-store",
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        },
    )


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
    refuse_for_template(product, "baselines")
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
    from creopdm.api.watch_notify import notify_product_watchers

    # Watchers hear about a new baseline like they do about a check-in or a revision.
    notify_product_watchers(
        request,
        ctx,
        db,
        product,
        action="Baseline created",
        filenames=[],
        what=(
            f"{baseline.name} ({baseline.member_count} file"
            f"{'' if baseline.member_count == 1 else 's'})"
        ),
        what_label="Baseline",
        comment=(payload.description or "").strip() or None,
    )
    return baseline_to_response(baseline, product.uuid, product.name)
