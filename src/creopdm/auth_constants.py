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
PERMISSION_ROLES_ASSIGN = "roles.assign"
PERMISSION_ROLES_MANAGE = "roles.manage"
PERMISSION_SETTINGS_MANAGE = "settings.manage"
PERMISSION_PROJECTS_CREATE = "projects.create"
PERMISSION_PROJECTS_EDIT = "projects.edit"
PERMISSION_PROJECTS_DELETE = "projects.delete"
PERMISSION_OBJECTS_ADD = "objects.add"
PERMISSION_OBJECTS_VIEW = "objects.view"
PERMISSION_OBJECTS_CHECKOUT = "objects.checkout"
PERMISSION_OBJECTS_CHECKIN = "objects.checkin"
PERMISSION_OBJECTS_REMOVE = "objects.remove"
PERMISSION_OBJECTS_REVERT = "objects.revert"
PERMISSION_OBJECTS_METADATA = "objects.metadata"
PERMISSION_OBJECTS_COPY_TO_VAULT = "objects.copy_to_vault"

STARTER_ROLE_DESCRIPTIONS: dict[str, str] = {
    StarterRole.ADMINISTRATOR.value: "Full system administration access.",
    StarterRole.PDM_MANAGER.value: "Manage engineering data without full server administration.",
    StarterRole.ENGINEER.value: "Normal CAD/PDM authoring user.",
    StarterRole.VIEWER.value: "Read-only access to assigned projects.",
}

# Back-compat alias.
BUILTIN_ROLE_DESCRIPTIONS = STARTER_ROLE_DESCRIPTIONS

BUILTIN_PERMISSIONS: tuple[tuple[str, str], ...] = (
    (PERMISSION_USERS_MANAGE, "Create, edit, and disable users"),
    (PERMISSION_ROLES_ASSIGN, "Assign roles to users"),
    (PERMISSION_ROLES_MANAGE, "Create, edit, and delete roles"),
    (PERMISSION_SETTINGS_MANAGE, "Change global CreoPDM settings"),
    (PERMISSION_PROJECTS_CREATE, "Create projects"),
    (PERMISSION_PROJECTS_EDIT, "Edit project properties"),
    (PERMISSION_PROJECTS_DELETE, "Delete or forget projects"),
    (PERMISSION_OBJECTS_VIEW, "Browse projects and open or download files"),
    (PERMISSION_OBJECTS_ADD, "Add files and folders to projects"),
    (PERMISSION_OBJECTS_CHECKOUT, "Check out objects and undo own checkout"),
    (PERMISSION_OBJECTS_CHECKIN, "Check in objects"),
    (PERMISSION_OBJECTS_REMOVE, "Remove objects from projects"),
    (PERMISSION_OBJECTS_REVERT, "Restore an older version as the working version"),
    (PERMISSION_OBJECTS_METADATA, "Update Creo metadata on objects"),
    (PERMISSION_OBJECTS_COPY_TO_VAULT, "Copy selected files into the vault (Copy to Vault)"),
)

# CreoPDM Administration caps. At least one ACTIVE user must keep all of them
# so the system cannot be locked out of Users / role assignment / Roles / Settings.
ADMINISTRATION_PERMISSION_KEYS: frozenset[str] = frozenset(
    (
        PERMISSION_USERS_MANAGE,
        PERMISSION_ROLES_ASSIGN,
        PERMISSION_ROLES_MANAGE,
        PERMISSION_SETTINGS_MANAGE,
    )
)

# Grouping for Roles admin checkboxes.
PERMISSION_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "CreoPDM Administration",
        (
            PERMISSION_USERS_MANAGE,
            PERMISSION_ROLES_ASSIGN,
            PERMISSION_ROLES_MANAGE,
            PERMISSION_SETTINGS_MANAGE,
        ),
    ),
    (
        "Projects",
        (PERMISSION_PROJECTS_CREATE, PERMISSION_PROJECTS_EDIT, PERMISSION_PROJECTS_DELETE),
    ),
    (
        "Objects",
        (
            PERMISSION_OBJECTS_VIEW,
            PERMISSION_OBJECTS_ADD,
            PERMISSION_OBJECTS_CHECKOUT,
            PERMISSION_OBJECTS_CHECKIN,
            PERMISSION_OBJECTS_REMOVE,
            PERMISSION_OBJECTS_REVERT,
            PERMISSION_OBJECTS_METADATA,
            PERMISSION_OBJECTS_COPY_TO_VAULT,
        ),
    ),
)

_AUTHORING = (
    PERMISSION_OBJECTS_VIEW,
    PERMISSION_OBJECTS_ADD,
    PERMISSION_OBJECTS_CHECKOUT,
    PERMISSION_OBJECTS_CHECKIN,
    PERMISSION_OBJECTS_REMOVE,
    PERMISSION_OBJECTS_REVERT,
    PERMISSION_OBJECTS_METADATA,
)

# Seed-only templates when the roles table is empty. Runtime caps come from DB.
STARTER_ROLE_PERMISSION_KEYS: dict[str, tuple[str, ...]] = {
    StarterRole.ADMINISTRATOR.value: tuple(key for key, _ in BUILTIN_PERMISSIONS),
    StarterRole.PDM_MANAGER.value: (
        PERMISSION_PROJECTS_CREATE,
        PERMISSION_PROJECTS_EDIT,
        *_AUTHORING,
        PERMISSION_OBJECTS_COPY_TO_VAULT,
    ),
    StarterRole.ENGINEER.value: _AUTHORING,
    StarterRole.VIEWER.value: (PERMISSION_OBJECTS_VIEW,),
}

# Back-compat alias (seed path only — do not overlay at runtime).
ROLE_PERMISSION_KEYS = STARTER_ROLE_PERMISSION_KEYS

# Caps granted when auth is disabled (unit/integration tests).
TEST_AUTH_PERMISSIONS: frozenset[str] = frozenset(key for key, _ in BUILTIN_PERMISSIONS)
