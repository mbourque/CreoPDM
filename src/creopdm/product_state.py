"""Product lifecycle state + read-only access checks.

UI capability flags and API ``ensure_*`` guards share the same rules here so
templates and services do not re-encode lifecycle / Locked / read_only logic.
Permission matrix lives in settings (see ``lifecycle_policy``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from creopdm.constants import PRODUCT_STATE_LEGACY_ALIASES, ProductState
from creopdm.exceptions import ValidationAppError
from creopdm.lifecycle_policy import get_lifecycle_policy, normalize_lifecycle_key
from creopdm.models.product import Product


def product_state_value(product: Product | None) -> str:
    if product is None:
        return ProductState.IN_WORK.value
    raw = (getattr(product, "state", None) or ProductState.IN_WORK.value).strip().upper()
    return PRODUCT_STATE_LEGACY_ALIASES.get(raw, raw)


def product_state_label(state: str | None) -> str:
    return get_lifecycle_policy().label(state)


def product_is_archived(product: Product | None) -> bool:
    return product_state_value(product) == ProductState.ARCHIVED.value


def product_is_locked(product: Any) -> bool:
    """True when the state key is LOCKED (built-in list-only default)."""
    return product is not None and product_state_value(product) == ProductState.LOCKED.value


def product_allows_op(product: Any, op: str) -> bool:
    """Matrix permission for ``op``, with read_only blocking mutation ops."""
    if product is None:
        return True
    policy = get_lifecycle_policy()
    state = product_state_value(product)
    if op in {"checkout", "checkin", "remove", "edit_metadata", "rename"}:
        if bool(getattr(product, "read_only", False)):
            return False
    return policy.allows(state, op)


def product_allows_mutation(product: Any) -> bool:
    """True when any engineering mutation op is allowed (and not read_only)."""
    if product is None:
        return True
    if bool(getattr(product, "read_only", False)):
        return False
    return get_lifecycle_policy().allows_mutation(product_state_value(product))


def product_allows_content_access(product: Any) -> bool:
    """True when open / download / export of vault tips is allowed."""
    if product is None:
        return True
    return product_allows_op(product, "download")


def product_allows_delete(product: Any) -> bool:
    """Product unregister is always allowed when the role can delete (password confirm)."""
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
    """Combine signed-in role permissions with lifecycle matrix / read_only."""
    mutable = product_allows_mutation(product)
    content = product_allows_content_access(product)
    can_checkout_state = product_allows_op(product, "checkout")
    can_checkin_state = product_allows_op(product, "checkin")
    can_remove_state = product_allows_op(product, "remove")
    can_meta_state = product_allows_op(product, "edit_metadata")
    can_rename_state = product_allows_op(product, "rename")
    has_product = product is not None
    return ProductUiCapabilities(
        allows_mutation=mutable,
        allows_content=content,
        show_access_banner=has_product and (not mutable or not content),
        show_add=can_add_objects and can_checkin_state,
        show_checkout=can_checkout and can_checkout_state,
        # Undo / Force Undo follow the matrix Check Out column (Locked = no lock changes).
        show_undo_checkout=can_checkout and can_checkout_state,
        show_force_undo_checkout=can_force_undo_checkout and can_checkout_state,
        show_checkin=can_checkin and can_checkin_state,
        show_open=can_view_objects and content,
        show_download=can_view_objects and content,
        show_export_product=can_export_product and content,
        show_export_objects=can_export_objects and content,
        show_copy_to_vault=can_copy_to_vault and can_checkin_state,
        show_remove=can_remove_objects,
        show_remove_vault=can_remove_objects and can_remove_state,
        show_remove_product=can_remove_objects and can_remove_state,
        show_rename=has_product and can_edit_product and can_rename_state,
        show_delete_product=has_product and can_delete_product,
        show_metadata_tools=has_product and can_update_metadata and can_meta_state,
        show_revert=can_revert_objects and can_checkin_state,
    )


def ensure_product_allows(
    product: Product, op: str, *, action: str | None = None
) -> None:
    """Raise when the lifecycle matrix (or read_only) blocks ``op``."""
    verb = action or {
        "checkout": "check out files",
        "checkin": "check in or add files",
        "remove": "remove files",
        "edit_metadata": "update metadata",
        "rename": "rename this product",
        "download": "open or download files from this product",
        "change_state": "change lifecycle state",
    }.get(op, "modify this product")
    if op in {"checkout", "checkin", "remove", "edit_metadata", "rename"}:
        if bool(getattr(product, "read_only", False)):
            raise ValidationAppError(
                f"Product is read-only and cannot {verb}.",
                details={"product": product.uuid, "read_only": True},
            )
    if product_allows_op(product, op):
        return
    state = product_state_value(product)
    raise ValidationAppError(
        f"Product is {product_state_label(state)} and cannot {verb}.",
        details={"product": product.uuid, "state": state, "op": op},
    )


def ensure_product_mutable(product: Product, *, action: str = "modify this product") -> None:
    """Raise when no mutation ops are allowed (or product is read-only)."""
    if bool(getattr(product, "read_only", False)):
        raise ValidationAppError(
            f"Product is read-only and cannot {action}.",
            details={"product": product.uuid, "read_only": True},
        )
    if product_allows_mutation(product):
        return
    state = product_state_value(product)
    raise ValidationAppError(
        f"Product is {product_state_label(state)} and cannot {action}.",
        details={"product": product.uuid, "state": state},
    )


def ensure_product_content_accessible(
    product: Product, *, action: str = "open or download files from this product"
) -> None:
    """Raise when download/open/export is blocked for this lifecycle state."""
    ensure_product_allows(product, "download", action=action)


def ensure_product_deletable(product: Product, *, action: str = "delete this product") -> None:
    """Product delete/forget is not blocked by lifecycle or read-only."""
    if product is None:
        raise ValidationAppError(f"Cannot {action}: product is missing.")


def parse_product_state(raw: str | None) -> str:
    """Accept built-in or admin-defined lifecycle keys from the active policy."""
    key = normalize_lifecycle_key(raw)
    policy = get_lifecycle_policy()
    if key in policy.known_keys():
        return key
    allowed = ", ".join(s.key for s in policy.ordered())
    raise ValidationAppError(
        f"Unknown product state. Use one of: {allowed}.",
        details={"state": raw},
    )


def configured_product_states() -> list[str]:
    """Ordered state keys for Administration → Products dropdown."""
    return [s.key for s in get_lifecycle_policy().ordered()]


def configured_product_state_labels() -> dict[str, str]:
    return get_lifecycle_policy().labels_map()


def configured_product_state_descriptions() -> dict[str, str]:
    return get_lifecycle_policy().descriptions_map()
