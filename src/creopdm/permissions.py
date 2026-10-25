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
    PERMISSION_OBJECTS_EXPORT,
    PERMISSION_OBJECTS_FORCE_UNDO_CHECKOUT,
    PERMISSION_OBJECTS_METADATA,
    PERMISSION_OBJECTS_REMOVE,
    PERMISSION_OBJECTS_REVERT,
    PERMISSION_OBJECTS_REVISE,
    PERMISSION_BASELINES_ADMIN,
    PERMISSION_BASELINES_CREATE,
    PERMISSION_BASELINES_VIEW,
    PERMISSION_COMMENTS_ADD,
    PERMISSION_COMMENTS_ADMIN,
    PERMISSION_COMMENTS_RESOLVE,
    PERMISSION_COMMENTS_VIEW,
    PERMISSION_OBJECTS_VIEW,
    PERMISSION_PRODUCTS_ASSIGN,
    PERMISSION_PRODUCTS_CREATE,
    PERMISSION_PRODUCTS_DELETE,
    PERMISSION_PRODUCTS_EDIT,
    PERMISSION_PRODUCTS_EXPORT,
    PERMISSION_LIFECYCLE_STATES_MANAGE,
    PERMISSION_PRODUCTS_MANAGE,
    PERMISSION_PRODUCTS_VIEW,
    PERMISSION_ROLES_ASSIGN,
    PERMISSION_ROLES_MANAGE,
    PERMISSION_SETTINGS_AI,
    PERMISSION_SETTINGS_MANAGE,
    PERMISSION_TEMPLATES_CREATE,
    PERMISSION_TEMPLATES_DELETE,
    PERMISSION_TEMPLATES_EDIT,
    PERMISSION_TEMPLATES_VIEW,
    PERMISSION_USERS_MANAGE,
    PERMISSION_USERS_PASSWORD,
    PERMISSION_UTILITIES_AUDIT,
    PERMISSION_UTILITIES_AVAILABILITY,
    PERMISSION_UTILITIES_COMPACT_PRODUCT,
    PERMISSION_UTILITIES_DELETE_PRODUCT,
    PERMISSION_UTILITIES_EMAIL_USERS,
    PERMISSION_UTILITIES_HEALTH,
    PERMISSION_UTILITIES_LOGS,
    PERMISSION_UTILITIES_REBUILD_PRODUCT,
    TEST_AUTH_PERMISSIONS,
    UTILITIES_PERMISSION_KEYS,
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
    can_manage_ai: bool
    can_manage_products: bool
    can_manage_lifecycle_states: bool
    can_manage_email: bool
    can_access_utilities: bool
    can_utilities_availability: bool
    can_utilities_email_users: bool
    can_utilities_compact_product: bool
    can_utilities_rebuild_product: bool
    can_utilities_delete_product: bool
    can_utilities_audit: bool
    can_utilities_health: bool
    can_utilities_logs: bool
    can_create_product: bool
    can_edit_product: bool
    can_delete_product: bool
    can_view_products: bool
    can_view_objects: bool
    can_add_objects: bool
    can_checkout: bool
    can_checkin: bool
    can_force_undo_checkout: bool
    can_remove_objects: bool
    can_revert_objects: bool
    can_revise_objects: bool
    can_view_baselines: bool
    can_create_baselines: bool
    can_admin_baselines: bool
    can_view_comments: bool
    can_add_comments: bool
    can_resolve_comments: bool
    can_admin_comments: bool
    can_update_metadata: bool
    can_copy_to_vault: bool
    can_export_product: bool
    can_export_objects: bool
    can_view_templates: bool
    can_create_templates: bool
    can_edit_templates: bool
    can_delete_templates: bool


def caps_from_keys(keys: frozenset[str]) -> CapabilityFlags:
    return CapabilityFlags(
        permissions=keys,
        can_manage_users=PERMISSION_USERS_MANAGE in keys,
        can_set_passwords=PERMISSION_USERS_PASSWORD in keys,
        can_assign_roles=PERMISSION_ROLES_ASSIGN in keys,
        can_assign_products=PERMISSION_PRODUCTS_ASSIGN in keys,
        can_manage_roles=PERMISSION_ROLES_MANAGE in keys,
        can_manage_settings=PERMISSION_SETTINGS_MANAGE in keys,
        can_manage_ai=PERMISSION_SETTINGS_AI in keys,
        can_manage_products=PERMISSION_PRODUCTS_MANAGE in keys,
        can_manage_lifecycle_states=PERMISSION_LIFECYCLE_STATES_MANAGE in keys,
        can_manage_email=PERMISSION_EMAIL_MANAGE in keys,
        can_access_utilities=bool(keys & UTILITIES_PERMISSION_KEYS),
        can_utilities_availability=PERMISSION_UTILITIES_AVAILABILITY in keys,
        can_utilities_email_users=PERMISSION_UTILITIES_EMAIL_USERS in keys,
        can_utilities_compact_product=PERMISSION_UTILITIES_COMPACT_PRODUCT in keys,
        can_utilities_rebuild_product=PERMISSION_UTILITIES_REBUILD_PRODUCT in keys,
        can_utilities_delete_product=PERMISSION_UTILITIES_DELETE_PRODUCT in keys,
        can_utilities_audit=PERMISSION_UTILITIES_AUDIT in keys,
        can_utilities_health=PERMISSION_UTILITIES_HEALTH in keys,
        can_utilities_logs=PERMISSION_UTILITIES_LOGS in keys,
        can_create_product=PERMISSION_PRODUCTS_CREATE in keys,
        can_edit_product=PERMISSION_PRODUCTS_EDIT in keys,
        can_delete_product=PERMISSION_PRODUCTS_DELETE in keys,
        can_view_products=PERMISSION_PRODUCTS_VIEW in keys,
        can_view_objects=PERMISSION_OBJECTS_VIEW in keys,
        can_add_objects=PERMISSION_OBJECTS_ADD in keys,
        can_checkout=PERMISSION_OBJECTS_CHECKOUT in keys,
        can_checkin=PERMISSION_OBJECTS_CHECKIN in keys,
        can_force_undo_checkout=PERMISSION_OBJECTS_FORCE_UNDO_CHECKOUT in keys,
        can_remove_objects=PERMISSION_OBJECTS_REMOVE in keys,
        can_revert_objects=PERMISSION_OBJECTS_REVERT in keys,
        can_revise_objects=PERMISSION_OBJECTS_REVISE in keys,
        can_view_baselines=PERMISSION_BASELINES_VIEW in keys,
        can_create_baselines=PERMISSION_BASELINES_CREATE in keys,
        can_admin_baselines=PERMISSION_BASELINES_ADMIN in keys,
        can_view_comments=PERMISSION_COMMENTS_VIEW in keys,
        can_add_comments=PERMISSION_COMMENTS_ADD in keys,
        can_resolve_comments=PERMISSION_COMMENTS_RESOLVE in keys,
        can_admin_comments=PERMISSION_COMMENTS_ADMIN in keys,
        can_update_metadata=PERMISSION_OBJECTS_METADATA in keys,
        can_copy_to_vault=PERMISSION_OBJECTS_COPY_TO_VAULT in keys,
        can_export_product=PERMISSION_PRODUCTS_EXPORT in keys,
        can_export_objects=PERMISSION_OBJECTS_EXPORT in keys,
        can_view_templates=PERMISSION_TEMPLATES_VIEW in keys,
        can_create_templates=PERMISSION_TEMPLATES_CREATE in keys,
        can_edit_templates=PERMISSION_TEMPLATES_EDIT in keys,
        can_delete_templates=PERMISSION_TEMPLATES_DELETE in keys,
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
    request.state.can_manage_ai = caps.can_manage_ai
    request.state.can_manage_products = caps.can_manage_products
    request.state.can_manage_lifecycle_states = caps.can_manage_lifecycle_states
    request.state.can_manage_email = caps.can_manage_email
    request.state.can_access_utilities = caps.can_access_utilities
    request.state.can_utilities_availability = caps.can_utilities_availability
    request.state.can_utilities_email_users = caps.can_utilities_email_users
    request.state.can_utilities_compact_product = caps.can_utilities_compact_product
    request.state.can_utilities_rebuild_product = caps.can_utilities_rebuild_product
    request.state.can_utilities_delete_product = caps.can_utilities_delete_product
    request.state.can_utilities_audit = caps.can_utilities_audit
    request.state.can_utilities_health = caps.can_utilities_health
    request.state.can_utilities_logs = caps.can_utilities_logs
    request.state.can_create_product = caps.can_create_product
    request.state.can_edit_product = caps.can_edit_product
    request.state.can_delete_product = caps.can_delete_product
    request.state.can_view_products = caps.can_view_products
    request.state.can_view_objects = caps.can_view_objects
    request.state.can_add_objects = caps.can_add_objects
    request.state.can_checkout = caps.can_checkout
    request.state.can_checkin = caps.can_checkin
    request.state.can_force_undo_checkout = caps.can_force_undo_checkout
    request.state.can_remove_objects = caps.can_remove_objects
    request.state.can_revert_objects = caps.can_revert_objects
    request.state.can_revise_objects = caps.can_revise_objects
    request.state.can_view_baselines = caps.can_view_baselines
    request.state.can_create_baselines = caps.can_create_baselines
    request.state.can_admin_baselines = caps.can_admin_baselines
    request.state.can_view_comments = caps.can_view_comments
    request.state.can_add_comments = caps.can_add_comments
    request.state.can_resolve_comments = caps.can_resolve_comments
    request.state.can_admin_comments = caps.can_admin_comments
    request.state.can_update_metadata = caps.can_update_metadata
    request.state.can_copy_to_vault = caps.can_copy_to_vault
    request.state.can_export_product = caps.can_export_product
    request.state.can_export_objects = caps.can_export_objects
    request.state.can_view_templates = caps.can_view_templates
    request.state.can_create_templates = caps.can_create_templates
    request.state.can_edit_templates = caps.can_edit_templates
    request.state.can_delete_templates = caps.can_delete_templates


def caps_dict(request: Request) -> dict:
    flags = {
        "can_manage_users": bool(getattr(request.state, "can_manage_users", False)),
        "can_set_passwords": bool(getattr(request.state, "can_set_passwords", False)),
        "can_assign_roles": bool(getattr(request.state, "can_assign_roles", False)),
        "can_assign_products": bool(getattr(request.state, "can_assign_products", False)),
        "can_manage_roles": bool(getattr(request.state, "can_manage_roles", False)),
        "can_manage_settings": bool(getattr(request.state, "can_manage_settings", False)),
        "can_manage_ai": bool(getattr(request.state, "can_manage_ai", False)),
        "can_manage_products": bool(getattr(request.state, "can_manage_products", False)),
        "can_manage_lifecycle_states": bool(
            getattr(request.state, "can_manage_lifecycle_states", False)
        ),
        "can_manage_email": bool(getattr(request.state, "can_manage_email", False)),
        "can_access_utilities": bool(getattr(request.state, "can_access_utilities", False)),
        "can_utilities_availability": bool(
            getattr(request.state, "can_utilities_availability", False)
        ),
        "can_utilities_email_users": bool(
            getattr(request.state, "can_utilities_email_users", False)
        ),
        "can_utilities_compact_product": bool(
            getattr(request.state, "can_utilities_compact_product", False)
        ),
        "can_utilities_rebuild_product": bool(
            getattr(request.state, "can_utilities_rebuild_product", False)
        ),
        "can_utilities_delete_product": bool(
            getattr(request.state, "can_utilities_delete_product", False)
        ),
        "can_utilities_audit": bool(getattr(request.state, "can_utilities_audit", False)),
        "can_utilities_health": bool(getattr(request.state, "can_utilities_health", False)),
        "can_utilities_logs": bool(getattr(request.state, "can_utilities_logs", False)),
        "can_create_product": bool(getattr(request.state, "can_create_product", False)),
        "can_edit_product": bool(getattr(request.state, "can_edit_product", False)),
        "can_delete_product": bool(getattr(request.state, "can_delete_product", False)),
        "can_view_products": bool(getattr(request.state, "can_view_products", False)),
        "can_view_objects": bool(getattr(request.state, "can_view_objects", False)),
        "can_add_objects": bool(getattr(request.state, "can_add_objects", False)),
        "can_checkout": bool(getattr(request.state, "can_checkout", False)),
        "can_checkin": bool(getattr(request.state, "can_checkin", False)),
        "can_force_undo_checkout": bool(getattr(request.state, "can_force_undo_checkout", False)),
        "can_remove_objects": bool(getattr(request.state, "can_remove_objects", False)),
        "can_revert_objects": bool(getattr(request.state, "can_revert_objects", False)),
        "can_revise_objects": bool(getattr(request.state, "can_revise_objects", False)),
        "can_view_baselines": bool(getattr(request.state, "can_view_baselines", False)),
        "can_create_baselines": bool(getattr(request.state, "can_create_baselines", False)),
        "can_admin_baselines": bool(getattr(request.state, "can_admin_baselines", False)),
        "can_view_comments": bool(getattr(request.state, "can_view_comments", False)),
        "can_add_comments": bool(getattr(request.state, "can_add_comments", False)),
        "can_resolve_comments": bool(getattr(request.state, "can_resolve_comments", False)),
        "can_admin_comments": bool(getattr(request.state, "can_admin_comments", False)),
        "can_update_metadata": bool(getattr(request.state, "can_update_metadata", False)),
        "can_copy_to_vault": bool(getattr(request.state, "can_copy_to_vault", False)),
        "can_export_product": bool(getattr(request.state, "can_export_product", False)),
        "can_export_objects": bool(getattr(request.state, "can_export_objects", False)),
        "can_view_templates": bool(getattr(request.state, "can_view_templates", False)),
        "can_create_templates": bool(getattr(request.state, "can_create_templates", False)),
        "can_edit_templates": bool(getattr(request.state, "can_edit_templates", False)),
        "can_delete_templates": bool(getattr(request.state, "can_delete_templates", False)),
    }
    flags["can_open_administration"] = (
        flags["can_manage_users"]
        or flags["can_set_passwords"]
        or flags["can_assign_roles"]
        or flags["can_assign_products"]
        or flags["can_manage_roles"]
        or flags["can_manage_settings"]
        or flags["can_manage_ai"]
        or flags["can_manage_products"]
        or flags["can_manage_lifecycle_states"]
        or flags["can_manage_email"]
        or flags["can_access_utilities"]
        or flags["can_admin_baselines"]
        or flags["can_create_templates"]
        or flags["can_delete_templates"]
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
        or caps.can_manage_ai
        or caps.can_manage_products
        or caps.can_manage_lifecycle_states
        or caps.can_manage_email
        or caps.can_access_utilities
        or caps.can_admin_baselines
        or caps.can_create_templates
        or caps.can_delete_templates
    )


def default_app_path(caps: CapabilityFlags) -> str:
    """Where to send a signed-in user when they have no explicit destination."""
    if caps.can_view_products:
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
