"""Compact embed surfaces (Creo navigator pane, etc.). Additive — leave full UI alone."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from creopdm.api.checkout import present_objects
from creopdm.api.deps import (
    accessible_products,
    get_context,
    get_db,
    load_accessible_product,
    require_permission,
    require_product_access,
)
from creopdm.api.pages import _creo_page, render
from creopdm.api.serializers import product_to_response
from creopdm.auth_constants import PERMISSION_OBJECTS_VIEW, PERMISSION_PRODUCTS_VIEW
from creopdm.constants import APP_NAME, APP_VERSION, ObjectType
from creopdm.context import AppContext
from creopdm.exceptions import PermissionDeniedError, ProductNotFoundError, ValidationAppError
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product
from creopdm.product_state import (
    product_is_archived,
    product_state_label,
    product_state_value,
)
from creopdm.utils.folders import folder_of, normalize_folder_query

router = APIRouter()


def _norm_name(value: str | None) -> str:
    return str(value or "").strip().casefold()


def _basename(path: str) -> str:
    text = str(path or "").replace("\\", "/").strip().rstrip("/")
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def resolve_embed_product(
    request: Request,
    ctx: AppContext,
    db: Session,
    *,
    product_q: str | None,
    file_q: str | None,
    folder_q: str | None,
) -> tuple[Product | None, EngineeringObject | None]:
    """Pick product from ``product`` (uuid or name), else infer from ``file`` / ``folder``.

    Returns ``(product, focus_object)``. ``focus_object`` is set when ``file`` matches
    a row in the chosen product (used to seed folder + selection).
    """
    products = accessible_products(request, ctx, db)
    products = [p for p in products if not product_is_archived(p)]
    by_uuid = {p.uuid.casefold(): p for p in products}
    wanted_product = (product_q or "").strip()
    wanted_file = (file_q or "").strip()
    wanted_folder = normalize_folder_query(folder_q)
    focus: EngineeringObject | None = None

    chosen: Product | None = None
    if wanted_product:
        hit = by_uuid.get(wanted_product.casefold())
        if hit is not None:
            chosen = hit
        else:
            name_key = _norm_name(wanted_product)
            for product in products:
                if _norm_name(product.name) == name_key:
                    chosen = product
                    break
            if chosen is None:
                raise ValidationAppError(
                    f'No accessible product matches "{wanted_product}".',
                    details={"product": wanted_product},
                )

    if chosen is None and (wanted_file or wanted_folder):
        file_key = _norm_name(wanted_file) or _norm_name(_basename(wanted_file))
        folder_key = wanted_folder.casefold() if wanted_folder else ""
        scored: list[tuple[int, Product, EngineeringObject | None]] = []
        for product in products:
            objects = ctx.objects.list_objects(db, product.id)
            match_obj: EngineeringObject | None = None
            score = 0
            if wanted_file:
                for obj in objects:
                    rel = str(obj.relative_path or "").replace("\\", "/")
                    name = _norm_name(obj.filename) or _norm_name(_basename(rel))
                    if name != file_key and _norm_name(rel) != file_key:
                        continue
                    obj_folder = folder_of(rel).casefold()
                    if folder_key and obj_folder != folder_key:
                        continue
                    match_obj = obj
                    score = 3 if folder_key else 2
                    break
            elif wanted_folder:
                for obj in objects:
                    rel = str(obj.relative_path or "").replace("\\", "/")
                    if folder_of(rel).casefold() == folder_key or rel.casefold().startswith(
                        folder_key + "/"
                    ):
                        score = 1
                        break
            if score:
                scored.append((score, product, match_obj))
        scored.sort(key=lambda row: (-row[0], row[1].name.casefold()))
        if scored:
            chosen = scored[0][1]
            focus = scored[0][2]

    if chosen is None and products:
        chosen = products[0]

    if chosen is not None and wanted_file and focus is None:
        file_key = _norm_name(wanted_file) or _norm_name(_basename(wanted_file))
        folder_key = wanted_folder.casefold() if wanted_folder else ""
        for obj in ctx.objects.list_objects(db, chosen.id):
            rel = str(obj.relative_path or "").replace("\\", "/")
            name = _norm_name(obj.filename) or _norm_name(_basename(rel))
            if name != file_key and _norm_name(rel) != file_key:
                continue
            if folder_key and folder_of(rel).casefold() != folder_key:
                continue
            focus = obj
            break

    if chosen is not None:
        require_product_access(request, ctx, chosen)
    return chosen, focus


@router.get("/embed/explorer", response_class=HTMLResponse)
def embed_explorer(
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> HTMLResponse:
    """Narrow file explorer for Creo's navigator (~350–450 px). Does not alter Files UI."""
    require_permission(request, ctx, PERMISSION_PRODUCTS_VIEW)
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)

    product_q = request.query_params.get("product")
    file_q = request.query_params.get("file")
    folder_q = request.query_params.get("folder")

    try:
        product, focus = resolve_embed_product(
            request,
            ctx,
            db,
            product_q=product_q,
            file_q=file_q,
            folder_q=folder_q,
        )
    except (ValidationAppError, ProductNotFoundError, PermissionDeniedError):
        raise

    selected = product_to_response(product) if product is not None else None
    objects: list = []
    if product is not None:
        try:
            ctx.objects.migrate_numbered_vault_tips(
                db, product, vault=ctx.workspaces.ensure_vault(product)
            )
        except Exception:
            from creopdm.logging_setup import get_logger

            get_logger("embed").exception(
                "Vault-name migrate failed for product %s", product.uuid
            )
        objects = present_objects(ctx, db, ctx.objects.list_objects(db, product.id))

    initial_folder = normalize_folder_query(folder_q)
    if not initial_folder and focus is not None:
        initial_folder = folder_of(str(focus.relative_path or ""))

    objects_payload = [
        row.model_dump(mode="json") if hasattr(row, "model_dump") else row for row in objects
    ]

    state_key = product_state_value(product) if product else ""
    return render(
        request,
        "embed_explorer.html",
        {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            **_creo_page(ctx),
            "selected": selected,
            "product": selected,
            "objects": objects_payload,
            "focus_uuid": focus.uuid if focus else "",
            "focus_filename": (focus.filename if focus else "") or (file_q or ""),
            "initial_folder": initial_folder,
            "product_state_key": state_key,
            "product_state_label": product_state_label(state_key) if state_key else "",
            "query_product": (product_q or "").strip(),
            "query_file": (file_q or "").strip(),
            "query_folder": initial_folder,
            "object_types": [item.value for item in ObjectType],
        },
    )
