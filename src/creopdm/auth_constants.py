"""Auth-related constants (roles, user status, permission keys)."""

from __future__ import annotations

from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


# Starter role names seeded only when the roles table is empty.
class StarterRole(StrEnum):
    ADMINISTRATOR = "Administrator"
    PDM_MANAGER = "PDM Manager"
    ENGINEER = "Engineer"
    VIEWER = "Viewer"


# Back-compat alias for imports that still say BuiltinRole.
BuiltinRole = StarterRole


PERMISSION_USERS_MANAGE = "users.manage"
PERMISSION_USERS_PASSWORD = "users.password"
PERMISSION_ROLES_ASSIGN = "roles.assign"
PERMISSION_ROLES_MANAGE = "roles.manage"
PERMISSION_PRODUCTS_ASSIGN = "products.assign"
PERMISSION_PRODUCTS_MANAGE = "products.manage"
PERMISSION_SETTINGS_MANAGE = "settings.manage"
PERMISSION_EMAIL_MANAGE = "email.manage"
PERMISSION_PRODUCTS_VIEW = "products.view"
PERMISSION_PRODUCTS_CREATE = "products.create"
PERMISSION_PRODUCTS_EDIT = "products.edit"
PERMISSION_PRODUCTS_DELETE = "products.delete"
PERMISSION_OBJECTS_ADD = "objects.add"
PERMISSION_OBJECTS_VIEW = "objects.view"
PERMISSION_OBJECTS_CHECKOUT = "objects.checkout"
PERMISSION_OBJECTS_CHECKIN = "objects.checkin"
PERMISSION_OBJECTS_FORCE_UNDO_CHECKOUT = "objects.force_undo_checkout"
PERMISSION_OBJECTS_REMOVE = "objects.remove"
PERMISSION_OBJECTS_REVERT = "objects.revert"
PERMISSION_OBJECTS_METADATA = "objects.metadata"
PERMISSION_OBJECTS_COPY_TO_VAULT = "objects.copy_to_vault"
PERMISSION_PRODUCTS_EXPORT = "products.export"
PERMISSION_OBJECTS_EXPORT = "objects.export"

STARTER_ROLE_DESCRIPTIONS: dict[str, str] = {
    StarterRole.ADMINISTRATOR.value: "Full system administration access.",
    StarterRole.PDM_MANAGER.value: "Manage engineering data without full server administration.",
    StarterRole.ENGINEER.value: "Normal CAD/PDM authoring user.",
    StarterRole.VIEWER.value: "Read-only access to assigned products.",
}

# Back-compat alias.
BUILTIN_ROLE_DESCRIPTIONS = STARTER_ROLE_DESCRIPTIONS

BUILTIN_PERMISSIONS: tuple[tuple[str, str], ...] = (
    (PERMISSION_USERS_MANAGE, "Create, edit, and disable users"),
    (PERMISSION_USERS_PASSWORD, "Set or reset user passwords"),
    (PERMISSION_ROLES_ASSIGN, "Assign roles to users"),
    (PERMISSION_ROLES_MANAGE, "Create, edit, and delete roles"),
    (PERMISSION_PRODUCTS_ASSIGN, "Assign product membership (Administration → Membership)"),
    (PERMISSION_PRODUCTS_MANAGE, "Create, edit, and delete products in Administration"),
    (PERMISSION_SETTINGS_MANAGE, "Change global CreoPDM settings"),
    (PERMISSION_EMAIL_MANAGE, "Configure email and notifications in Administration"),
    (PERMISSION_PRODUCTS_VIEW, "View products"),
    (PERMISSION_PRODUCTS_CREATE, "Create products"),
    (PERMISSION_PRODUCTS_EDIT, "Edit product properties"),
    (PERMISSION_PRODUCTS_DELETE, "Delete or forget products"),
    (PERMISSION_OBJECTS_VIEW, "Browse file history and open or download files"),
    (PERMISSION_OBJECTS_ADD, "Add files and folders to products"),
    (PERMISSION_OBJECTS_CHECKOUT, "Check out objects and undo own checkout"),
    (PERMISSION_OBJECTS_CHECKIN, "Check in objects"),
    (
        PERMISSION_OBJECTS_FORCE_UNDO_CHECKOUT,
        "Force Undo Checkout — release another user's checkout without a new version",
    ),
    (PERMISSION_OBJECTS_REMOVE, "Remove objects from products"),
    (PERMISSION_OBJECTS_REVERT, "Restore an older version as the working version"),
    (PERMISSION_OBJECTS_METADATA, "Update Creo metadata on objects"),
    (PERMISSION_OBJECTS_COPY_TO_VAULT, "Copy selected files into the vault (Copy to Vault)"),
    (PERMISSION_PRODUCTS_EXPORT, "Export an entire product as a zip download"),
    (PERMISSION_OBJECTS_EXPORT, "Export selected files or folders as a zip download"),
)

# CreoPDM Administration caps. At least one ACTIVE user must keep all of them.
ADMINISTRATION_PERMISSION_KEYS: frozenset[str] = frozenset(
    (
        PERMISSION_USERS_MANAGE,
        PERMISSION_USERS_PASSWORD,
        PERMISSION_ROLES_ASSIGN,
        PERMISSION_ROLES_MANAGE,
        PERMISSION_PRODUCTS_ASSIGN,
        PERMISSION_PRODUCTS_MANAGE,
        PERMISSION_SETTINGS_MANAGE,
        PERMISSION_EMAIL_MANAGE,
    )
)

# Grouping for Roles admin checkboxes.
PERMISSION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "CreoPDM Administration",
        (
            PERMISSION_USERS_MANAGE,
            PERMISSION_USERS_PASSWORD,
            PERMISSION_ROLES_ASSIGN,
            PERMISSION_ROLES_MANAGE,
            PERMISSION_PRODUCTS_ASSIGN,
            PERMISSION_PRODUCTS_MANAGE,
            PERMISSION_SETTINGS_MANAGE,
            PERMISSION_EMAIL_MANAGE,
        ),
    ),
    (
        "Products",
        (
            PERMISSION_PRODUCTS_VIEW,
            PERMISSION_PRODUCTS_CREATE,
            PERMISSION_PRODUCTS_EDIT,
            PERMISSION_PRODUCTS_DELETE,
            PERMISSION_PRODUCTS_EXPORT,
        ),
    ),
    (
        "Objects",
        (
            PERMISSION_OBJECTS_VIEW,
            PERMISSION_OBJECTS_ADD,
            PERMISSION_OBJECTS_CHECKOUT,
            PERMISSION_OBJECTS_CHECKIN,
            PERMISSION_OBJECTS_FORCE_UNDO_CHECKOUT,
            PERMISSION_OBJECTS_REMOVE,
            PERMISSION_OBJECTS_REVERT,
            PERMISSION_OBJECTS_METADATA,
            PERMISSION_OBJECTS_COPY_TO_VAULT,
            PERMISSION_OBJECTS_EXPORT,
        ),
    ),
)

_AUTHORING = (
    PERMISSION_PRODUCTS_VIEW,
    PERMISSION_OBJECTS_VIEW,
    PERMISSION_OBJECTS_ADD,
    PERMISSION_OBJECTS_CHECKOUT,
    PERMISSION_OBJECTS_CHECKIN,
    PERMISSION_OBJECTS_REMOVE,
    PERMISSION_OBJECTS_REVERT,
    PERMISSION_OBJECTS_METADATA,
    PERMISSION_PRODUCTS_EXPORT,
    PERMISSION_OBJECTS_EXPORT,
)

# Seed-only templates when the roles table is empty. Runtime caps come from DB.
STARTER_ROLE_PERMISSION_KEYS: dict[str, tuple[str, ...]] = {
    StarterRole.ADMINISTRATOR.value: tuple(key for key, _ in BUILTIN_PERMISSIONS),
    StarterRole.PDM_MANAGER.value: (
        PERMISSION_PRODUCTS_CREATE,
        PERMISSION_PRODUCTS_EDIT,
        *_AUTHORING,
        PERMISSION_OBJECTS_FORCE_UNDO_CHECKOUT,
        PERMISSION_OBJECTS_COPY_TO_VAULT,
    ),
    StarterRole.ENGINEER.value: _AUTHORING,
    StarterRole.VIEWER.value: (PERMISSION_PRODUCTS_VIEW, PERMISSION_OBJECTS_VIEW),
}

# Back-compat alias (seed path only — do not overlay at runtime).
ROLE_PERMISSION_KEYS = STARTER_ROLE_PERMISSION_KEYS

# Caps granted when auth is disabled (unit/integration tests).
TEST_AUTH_PERMISSIONS: frozenset[str] = frozenset(key for key, _ in BUILTIN_PERMISSIONS)
