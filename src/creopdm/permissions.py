"""Request capability helpers for role-based access."""

from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request

from creopdm.auth_constants import (
    PERMISSION_EMAIL_MANAGE,
    PERMISSION_OBJECTS_ADD,
    PERMISSION_OBJECTS_CHECKIN,
    PERMISSION_OBJECTS_CHECKOUT,
    PERMISSION_OBJECTS_COPY_TO_VAULT,
    PERMISSION_OBJECTS_FORCE_UNDO_CHECKOUT,
    PERMISSION_OBJECTS_METADATA,
    PERMISSION_OBJECTS_REMOVE,
    PERMISSION_OBJECTS_REVERT,
    PERMISSION_OBJECTS_VIEW,
    PERMISSION_PRODUCTS_ASSIGN,
    PERMISSION_PRODUCTS_CREATE,
    PERMISSION_PRODUCTS_DELETE,
    PERMISSION_PRODUCTS_EDIT,
    PERMISSION_PRODUCTS_MANAGE,
    PERMISSION_ROLES_ASSIGN,
    PERMISSION_ROLES_MANAGE,
    PERMISSION_SETTINGS_MANAGE,
    PERMISSION_USERS_MANAGE,
    PERMISSION_USERS_PASSWORD,
    TEST_AUTH_PERMISSIONS,
)
from creopdm.models.user import User
from creopdm.services.user_service import UserService


@dataclass(frozen=True, slots=True)
class CapabilityFlags:
    permissions: frozenset[str]
    can_manage_users: bool
    can_set_passwords: bool
    can_assign_roles: bool
    can_assign_products: bool
    can_manage_roles: bool
    can_manage_settings: bool
    can_manage_products: bool
    can_manage_email: bool
    can_create_product: bool
    can_edit_product: bool
    can_delete_product: bool
    can_view_objects: bool
    can_add_objects: bool
    can_checkout: bool
    can_checkin: bool
    can_force_undo_checkout: bool
    can_remove_objects: bool
    can_revert_objects: bool
    can_update_metadata: bool
    can_copy_to_vault: bool


def caps_from_keys(keys: frozenset[str]) -> CapabilityFlags:
    return CapabilityFlags(
        permissions=keys,
        can_manage_users=PERMISSION_USERS_MANAGE in keys,
        can_set_passwords=PERMISSION_USERS_PASSWORD in keys,
        can_assign_roles=PERMISSION_ROLES_ASSIGN in keys,
        can_assign_products=PERMISSION_PRODUCTS_ASSIGN in keys,
        can_manage_roles=PERMISSION_ROLES_MANAGE in keys,
        can_manage_settings=PERMISSION_SETTINGS_MANAGE in keys,
        can_manage_products=PERMISSION_PRODUCTS_MANAGE in keys,
        can_manage_email=PERMISSION_EMAIL_MANAGE in keys,
        can_create_product=PERMISSION_PRODUCTS_CREATE in keys,
        can_edit_product=PERMISSION_PRODUCTS_EDIT in keys,
        can_delete_product=PERMISSION_PRODUCTS_DELETE in keys,
        can_view_objects=PERMISSION_OBJECTS_VIEW in keys,
        can_add_objects=PERMISSION_OBJECTS_ADD in keys,
        can_checkout=PERMISSION_OBJECTS_CHECKOUT in keys,
        can_checkin=PERMISSION_OBJECTS_CHECKIN in keys,
        can_force_undo_checkout=PERMISSION_OBJECTS_FORCE_UNDO_CHECKOUT in keys,
        can_remove_objects=PERMISSION_OBJECTS_REMOVE in keys,
        can_revert_objects=PERMISSION_OBJECTS_REVERT in keys,
        can_update_metadata=PERMISSION_OBJECTS_METADATA in keys,
        can_copy_to_vault=PERMISSION_OBJECTS_COPY_TO_VAULT in keys,
    )


def caps_for_user(accounts: UserService, user: User) -> CapabilityFlags:
    return caps_from_keys(accounts.permission_keys_for_user(user))


def test_auth_caps() -> CapabilityFlags:
    return caps_from_keys(TEST_AUTH_PERMISSIONS)


def empty_caps() -> CapabilityFlags:
    return caps_from_keys(frozenset())


def apply_caps(request: Request, caps: CapabilityFlags) -> None:
    request.state.permissions = caps.permissions
    request.state.can_manage_users = caps.can_manage_users
    request.state.can_set_passwords = caps.can_set_passwords
    request.state.can_assign_roles = caps.can_assign_roles
    request.state.can_assign_products = caps.can_assign_products
    request.state.can_manage_roles = caps.can_manage_roles
    request.state.can_manage_settings = caps.can_manage_settings
    request.state.can_manage_products = caps.can_manage_products
    request.state.can_manage_email = caps.can_manage_email
    request.state.can_create_product = caps.can_create_product
    request.state.can_edit_product = caps.can_edit_product
    request.state.can_delete_product = caps.can_delete_product
    request.state.can_view_objects = caps.can_view_objects
    request.state.can_add_objects = caps.can_add_objects
    request.state.can_checkout = caps.can_checkout
    request.state.can_checkin = caps.can_checkin
    request.state.can_force_undo_checkout = caps.can_force_undo_checkout
    request.state.can_remove_objects = caps.can_remove_objects
    request.state.can_revert_objects = caps.can_revert_objects
    request.state.can_update_metadata = caps.can_update_metadata
    request.state.can_copy_to_vault = caps.can_copy_to_vault


def caps_dict(request: Request) -> dict:
    flags = {
        "can_manage_users": bool(getattr(request.state, "can_manage_users", False)),
        "can_set_passwords": bool(getattr(request.state, "can_set_passwords", False)),
        "can_assign_roles": bool(getattr(request.state, "can_assign_roles", False)),
        "can_assign_products": bool(getattr(request.state, "can_assign_products", False)),
        "can_manage_roles": bool(getattr(request.state, "can_manage_roles", False)),
        "can_manage_settings": bool(getattr(request.state, "can_manage_settings", False)),
        "can_manage_products": bool(getattr(request.state, "can_manage_products", False)),
        "can_manage_email": bool(getattr(request.state, "can_manage_email", False)),
        "can_create_product": bool(getattr(request.state, "can_create_product", False)),
        "can_edit_product": bool(getattr(request.state, "can_edit_product", False)),
        "can_delete_product": bool(getattr(request.state, "can_delete_product", False)),
        "can_view_objects": bool(getattr(request.state, "can_view_objects", False)),
        "can_add_objects": bool(getattr(request.state, "can_add_objects", False)),
        "can_checkout": bool(getattr(request.state, "can_checkout", False)),
        "can_checkin": bool(getattr(request.state, "can_checkin", False)),
        "can_force_undo_checkout": bool(getattr(request.state, "can_force_undo_checkout", False)),
        "can_remove_objects": bool(getattr(request.state, "can_remove_objects", False)),
        "can_revert_objects": bool(getattr(request.state, "can_revert_objects", False)),
        "can_update_metadata": bool(getattr(request.state, "can_update_metadata", False)),
        "can_copy_to_vault": bool(getattr(request.state, "can_copy_to_vault", False)),
    }
    flags["can_open_administration"] = (
        flags["can_manage_users"]
        or flags["can_set_passwords"]
        or flags["can_assign_roles"]
        or flags["can_assign_products"]
        or flags["can_manage_roles"]
        or flags["can_manage_settings"]
        or flags["can_manage_products"]
        or flags["can_manage_email"]
    )
    return flags


def can_open_administration(caps: CapabilityFlags) -> bool:
    return (
        caps.can_manage_users
        or caps.can_set_passwords
        or caps.can_assign_roles
        or caps.can_assign_products
        or caps.can_manage_roles
        or caps.can_manage_settings
        or caps.can_manage_products
        or caps.can_manage_email
    )

def default_app_path(caps: CapabilityFlags) -> str:
    """Where to send a signed-in user when they have no explicit destination."""
    if caps.can_view_objects:
        return "/"
    if can_open_administration(caps):
        return "/admin"
    return "/no-access"


def resolve_post_login_target(caps: CapabilityFlags, next_url: str | None) -> str:
    """Honor safe next= when set; otherwise land on Files, Administration, or no-access."""
    default = default_app_path(caps)
    nxt = (next_url or "").strip()
    if not nxt or nxt == "/":
        return default
    if nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return default

