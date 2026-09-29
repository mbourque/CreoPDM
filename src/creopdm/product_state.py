"""Product lifecycle state + read-only access checks."""

from __future__ import annotations

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


def product_allows_mutation(product: Product) -> bool:
    """True when engineering mutations (add/checkout/check-in/remove/…) are allowed.

    Matches acceptance criteria: only IN_WORK and not read_only.
    """
    if bool(getattr(product, "read_only", False)):
        return False
    return product_state_value(product) == ProductState.IN_WORK.value


def product_allows_delete(product: Product) -> bool:
    """Product unregister / object remove — same gate as mutations (incl. read-only)."""
    return product_allows_mutation(product)


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
