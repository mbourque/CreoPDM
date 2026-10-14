"""Compact embed surfaces (Creo navigator pane, etc.). Additive — leave full UI alone."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from creopdm.api.deps import (
    accessible_products,
    get_context,
    get_db,
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
from creopdm.permissions import caps_dict
from creopdm.product_state import (
    product_is_archived,
    product_state_label,
    product_state_value,
    product_ui_capabilities,
)
from creopdm.schemas.common import EmbedExplorerContextResponse
from creopdm.utils.folders import folder_of, normalize_folder_query

router = APIRouter()


def _explorer_context_payload(
    request: Request,
    product: Product | None,
    focus: EngineeringObject | None,
    *,
    file_q: str | None,
    folder_q: str | None,
) -> EmbedExplorerContextResponse:
    selected = product_to_response(product) if product is not None else None
    initial_folder = normalize_folder_query(folder_q)
    if not initial_folder and focus is not None:
        initial_folder = folder_of(str(focus.relative_path or ""))
    state_key = product_state_value(product) if product else ""
    caps = caps_dict(request)
    ui = product_ui_capabilities(
        product,
        can_add_objects=bool(caps.get("can_add_objects")),
        can_checkout=bool(caps.get("can_checkout")),
        can_force_undo_checkout=bool(caps.get("can_force_undo_checkout")),
        can_checkin=bool(caps.get("can_checkin")),
        can_view_objects=bool(caps.get("can_view_objects")),
        can_export_product=bool(caps.get("can_export_product")),
        can_export_objects=bool(caps.get("can_export_objects")),
        can_copy_to_vault=bool(caps.get("can_copy_to_vault")),
        can_remove_objects=bool(caps.get("can_remove_objects")),
        can_edit_product=bool(caps.get("can_edit_product")),
        can_delete_product=bool(caps.get("can_delete_product")),
        can_update_metadata=bool(caps.get("can_update_metadata")),
        can_revert_objects=bool(caps.get("can_revert_objects")),
    )
    return EmbedExplorerContextResponse(
        product=selected,
        product_state_key=state_key,
        product_state_label=product_state_label(state_key) if state_key else "",
        focus_uuid=focus.uuid if focus else "",
        focus_filename=(focus.filename if focus else "") or (file_q or ""),
        initial_folder=initial_folder,
        allows_content=bool(ui.allows_content),
        show_open=bool(ui.show_open),
        show_checkout=bool(ui.show_checkout),
        show_undo_checkout=bool(ui.show_undo_checkout),
        show_checkin=bool(ui.show_checkin),
        show_export_objects=bool(ui.show_export_objects),
    )


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

    # Same default as Files home: last used product, else first accessible.
    if chosen is None and products:
        last_uuid = (ctx.config.settings.ui.last_product_uuid or "").strip()
        if last_uuid:
            chosen = by_uuid.get(last_uuid.casefold())
        if chosen is None:
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


@router.get("/api/embed/explorer/context", response_model=EmbedExplorerContextResponse)
def embed_explorer_context(
    request: Request,
    db: Session = Depends(get_db),
    ctx: AppContext = Depends(get_context),
) -> EmbedExplorerContextResponse:
    """Resolve the product the navigator pane should show (last used / query / file).

    The embed page polls this (and on mouse/focus/Refresh) so switching products
    in Files is picked up while the Creo navigator pane stays loaded.
    """
    require_permission(request, ctx, PERMISSION_PRODUCTS_VIEW)
    require_permission(request, ctx, PERMISSION_OBJECTS_VIEW)
    product_q = request.query_params.get("product")
    file_q = request.query_params.get("file")
    folder_q = request.query_params.get("folder")
    product, focus = resolve_embed_product(
        request,
        ctx,
        db,
        product_q=product_q,
        file_q=file_q,
        folder_q=folder_q,
    )
    return _explorer_context_payload(
        request, product, focus, file_q=file_q, folder_q=folder_q
    )


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

    # File rows are loaded by the page via /api/products/…/objects (cache-bust) so
    # Creo's embedded browser does not stick on a stale empty SSR payload.
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
        # Only remember when the opener named a product/file — bare navigator
        # opens follow last-used and must not clobber it with a stale default.
        if (product_q or "").strip() or (file_q or "").strip() or (folder_q or "").strip():
            ctx.config.remember_product(product.uuid)

    ctx_payload = _explorer_context_payload(
        request, product, focus, file_q=file_q, folder_q=folder_q
    )
    selected = ctx_payload.product
    return render(
        request,
        "embed_explorer.html",
        {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            **_creo_page(ctx),
            "selected": selected,
            "product": selected,
            "focus_uuid": ctx_payload.focus_uuid,
            "focus_filename": ctx_payload.focus_filename,
            "initial_folder": ctx_payload.initial_folder,
            "product_state_key": ctx_payload.product_state_key,
            "product_state_label": ctx_payload.product_state_label,
            "query_product": (product_q or "").strip(),
            "query_file": (file_q or "").strip(),
            "query_folder": ctx_payload.initial_folder,
            "follow_active": not bool((product_q or "").strip()),
            "object_types": [item.value for item in ObjectType],
        },
    )
