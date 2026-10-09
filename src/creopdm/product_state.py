"""Product lifecycle state + read-only access checks.

UI capability flags and API ``ensure_*`` guards share the same rules here so
templates and services do not re-encode lifecycle / LOCKED / read_only logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from creopdm.constants import (
    PRODUCT_MUTABLE_STATES,
    PRODUCT_STATE_LABELS,
    PRODUCT_STATE_LEGACY_ALIASES,
    ProductState,
)
from creopdm.exceptions import ValidationAppError
from creopdm.models.product import Product


def product_state_value(product: Product | None) -> str:
    if product is None:
        return ProductState.IN_WORK.value
    raw = (getattr(product, "state", None) or ProductState.IN_WORK.value).strip().upper()
    return PRODUCT_STATE_LEGACY_ALIASES.get(raw, raw)


def product_state_label(state: str | None) -> str:
    raw = (state or ProductState.IN_WORK.value).strip().upper()
    key = PRODUCT_STATE_LEGACY_ALIASES.get(raw, raw)
    return PRODUCT_STATE_LABELS.get(key, key.replace("_", " ").title())


def product_is_archived(product: Product | None) -> bool:
    return product_state_value(product) == ProductState.ARCHIVED.value


def product_is_locked(product: Any) -> bool:
    """True for lifecycle state LOCKED (list-only; stricter than read-only)."""
    return product is not None and product_state_value(product) == ProductState.LOCKED.value


def product_allows_mutation(product: Any) -> bool:
    """True when engineering mutations (add/checkout/check-in/remove/…) are allowed.

    In Work and Under Change, and not read_only. Accepts a Product model or any
    object with ``state`` / ``read_only``.
    """
    if product is None:
        return True
    if bool(getattr(product, "read_only", False)):
        return False
    return product_state_value(product) in PRODUCT_MUTABLE_STATES


def product_allows_content_access(product: Any) -> bool:
    """True when open / download / export of vault tips is allowed.

    LOCKED is list-only (browse Files / Details metadata). Read-only and other
    non-mutable states still allow open and download.
    """
    if product is None:
        return True
    return not product_is_locked(product)


def product_allows_delete(product: Any) -> bool:
    """Product unregister is always allowed when the role can delete (password confirm).

    Lifecycle lock / read-only must not trap vaults or DB rows after Archive.
    """
    return product is not None


@dataclass(frozen=True)
class ProductUiCapabilities:
    """Role caps AND product lock — what Files/gear may show (API still uses ensure_*)."""

    allows_mutation: bool
    allows_content: bool
    show_access_banner: bool
    show_add: bool
    show_checkout: bool
    show_undo_checkout: bool
    show_force_undo_checkout: bool
    show_checkin: bool
    show_open: bool
    show_download: bool
    show_export_product: bool
    show_export_objects: bool
    show_copy_to_vault: bool
    show_remove: bool
    show_remove_vault: bool
    show_remove_product: bool
    show_rename: bool
    show_delete_product: bool
    show_metadata_tools: bool
    show_revert: bool


def product_ui_capabilities(
    product: Any | None,
    *,
    can_add_objects: bool = False,
    can_checkout: bool = False,
    can_force_undo_checkout: bool = False,
    can_checkin: bool = False,
    can_view_objects: bool = False,
    can_export_product: bool = False,
    can_export_objects: bool = False,
    can_copy_to_vault: bool = False,
    can_remove_objects: bool = False,
    can_edit_product: bool = False,
    can_delete_product: bool = False,
    can_update_metadata: bool = False,
    can_revert_objects: bool = False,
) -> ProductUiCapabilities:
    """Combine signed-in role permissions with product state / read_only.

    Checkout selected/product and Check In hide when not mutable (read-only /
    not In Work or Under Change). Undo Checkout stays when the role has
    ``objects.checkout``. Lifecycle LOCKED also hides open / download / export.
    """
    mutable = product_allows_mutation(product)
    content = product_allows_content_access(product)
    has_product = product is not None
    return ProductUiCapabilities(
        allows_mutation=mutable,
        allows_content=content,
        show_access_banner=has_product and (not mutable or not content),
        show_add=can_add_objects and mutable,
        show_checkout=can_checkout and mutable,
        show_undo_checkout=can_checkout,
        show_force_undo_checkout=can_force_undo_checkout,
        show_checkin=can_checkin and mutable,
        show_open=can_view_objects and content,
        show_download=can_view_objects and content,
        show_export_product=can_export_product and content,
        show_export_objects=can_export_objects and content,
        show_copy_to_vault=can_copy_to_vault and mutable,
        show_remove=can_remove_objects,
        show_remove_vault=can_remove_objects and mutable,
        show_remove_product=can_remove_objects and mutable,
        show_rename=has_product and can_edit_product and mutable,
        # Delete/unregister must stay available on locked / Archived products so
        # vaults are not trapped (password re-auth confirm is the safety gate).
        show_delete_product=has_product and can_delete_product,
        show_metadata_tools=has_product and can_update_metadata and mutable,
        show_revert=can_revert_objects and mutable,
    )


def ensure_product_mutable(product: Product, *, action: str = "modify this product") -> None:
    """Raise when the product is read-only or not In Work / Under Change."""
    if bool(getattr(product, "read_only", False)):
        raise ValidationAppError(
            f"Product is read-only and cannot {action}.",
            details={"product": product.uuid, "read_only": True},
        )
    state = product_state_value(product)
    if state not in PRODUCT_MUTABLE_STATES:
        raise ValidationAppError(
            f"Product is {product_state_label(state)} and cannot {action}.",
            details={"product": product.uuid, "state": state},
        )


def ensure_product_content_accessible(
    product: Product, *, action: str = "open or download files from this product"
) -> None:
    """Raise when the product lifecycle is LOCKED (list-only)."""
    if product_allows_content_access(product):
        return
    state = product_state_value(product)
    raise ValidationAppError(
        f"Product is {product_state_label(state)} and cannot {action}.",
        details={"product": product.uuid, "state": state},
    )


def ensure_product_deletable(product: Product, *, action: str = "delete this product") -> None:
    """Product delete/forget is not blocked by lifecycle or read-only.

    Kept as the API/service gate hook (contract tests require ``ensure_product_deletable``).
    Callers still require ``products.delete`` and password re-auth confirm.
    """
    if product is None:
        raise ValidationAppError(f"Cannot {action}: product is missing.")


def parse_product_state(raw: str | None) -> str:
    key = (raw or ProductState.IN_WORK.value).strip().upper()
    key = PRODUCT_STATE_LEGACY_ALIASES.get(key, key)
    try:
        return ProductState(key).value
    except ValueError as exc:
        allowed = ", ".join(s.value for s in ProductState)
        raise ValidationAppError(
            f"Unknown product state. Use one of: {allowed}.",
            details={"state": raw},
        ) from exc
