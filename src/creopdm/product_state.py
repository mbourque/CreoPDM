"""Product lifecycle state + read-only access checks.

UI capability flags and API ``ensure_*`` guards share the same rules here so
templates and services do not re-encode ON_HOLD / read_only logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from creopdm.constants import PRODUCT_STATE_LABELS, ProductState
from creopdm.exceptions import ValidationAppError
from creopdm.models.product import Product


def product_state_value(product: Product | None) -> str:
    if product is None:
        return ProductState.IN_WORK.value
    return (getattr(product, "state", None) or ProductState.IN_WORK.value).strip().upper()


def product_state_label(state: str | None) -> str:
    key = (state or ProductState.IN_WORK.value).strip().upper()
    return PRODUCT_STATE_LABELS.get(key, key.replace("_", " ").title())


def product_is_archived(product: Product | None) -> bool:
    return product_state_value(product) == ProductState.ARCHIVED.value


def product_allows_mutation(product: Any) -> bool:
    """True when engineering mutations (add/checkout/check-in/remove/…) are allowed.

    Matches acceptance criteria: only IN_WORK and not read_only.
    Accepts a Product model or any object with ``state`` / ``read_only``.
    """
    if product is None:
        return True
    if bool(getattr(product, "read_only", False)):
        return False
    return product_state_value(product) == ProductState.IN_WORK.value


def product_allows_delete(product: Any) -> bool:
    """Product unregister / object remove — same gate as mutations (incl. read-only)."""
    return product_allows_mutation(product)


@dataclass(frozen=True)
class ProductUiCapabilities:
    """Role caps AND product lock — what Files/gear may show (API still uses ensure_*)."""

    allows_mutation: bool
    show_access_banner: bool
    show_add: bool
    show_checkout: bool
    show_force_undo_checkout: bool
    show_checkin: bool
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
    can_remove_objects: bool = False,
    can_edit_product: bool = False,
    can_delete_product: bool = False,
    can_update_metadata: bool = False,
    can_revert_objects: bool = False,
) -> ProductUiCapabilities:
    """Combine signed-in role permissions with product state / read_only.

    Checkout menu stays available when locked so Undo Checkout can appear (needs
    ``objects.checkout``); Force Undo Checkout is a separate flag. Add, check-in,
    vault/product remove, rename, delete, metadata, and revert hide when locked.
    Local workspace remove/purge stay under ``show_remove``.
    """
    mutable = product_allows_mutation(product)
    has_product = product is not None
    return ProductUiCapabilities(
        allows_mutation=mutable,
        show_access_banner=has_product and not mutable,
        show_add=can_add_objects and mutable,
        show_checkout=can_checkout,
        show_force_undo_checkout=can_force_undo_checkout,
        show_checkin=can_checkin and mutable,
        show_remove=can_remove_objects,
        show_remove_vault=can_remove_objects and mutable,
        show_remove_product=can_remove_objects and mutable,
        show_rename=has_product and can_edit_product and mutable,
        show_delete_product=has_product and can_delete_product and mutable,
        show_metadata_tools=has_product and can_update_metadata and mutable,
        show_revert=can_revert_objects and mutable,
    )


def ensure_product_mutable(product: Product, *, action: str = "modify this product") -> None:
    """Raise when the product is read-only or not IN_WORK."""
    if bool(getattr(product, "read_only", False)):
        raise ValidationAppError(
            f"Product is read-only and cannot {action}.",
            details={"product": product.uuid, "read_only": True},
        )
    state = product_state_value(product)
    if state != ProductState.IN_WORK.value:
        raise ValidationAppError(
            f"Product is {product_state_label(state)} and cannot {action}.",
            details={"product": product.uuid, "state": state},
        )


def ensure_product_deletable(product: Product, *, action: str = "delete this product") -> None:
    """Block product delete/forget when read-only or not In work."""
    ensure_product_mutable(product, action=action)


def parse_product_state(raw: str | None) -> str:
    key = (raw or ProductState.IN_WORK.value).strip().upper()
    try:
        return ProductState(key).value
    except ValueError as exc:
        allowed = ", ".join(s.value for s in ProductState)
        raise ValidationAppError(
            f"Unknown product state. Use one of: {allowed}.",
            details={"state": raw},
        ) from exc
