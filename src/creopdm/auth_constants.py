"""Auth-related constants (roles, user status, permission keys)."""

from __future__ import annotations

from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class BuiltinRole(StrEnum):
    ADMINISTRATOR = "Administrator"
    PDM_MANAGER = "PDM Manager"
    ENGINEER = "Engineer"
    VIEWER = "Viewer"


PERMISSION_USERS_MANAGE = "users.manage"
PERMISSION_SETTINGS_MANAGE = "settings.manage"
PERMISSION_PROJECTS_CREATE = "projects.create"
PERMISSION_PROJECTS_EDIT = "projects.edit"
PERMISSION_PROJECTS_DELETE = "projects.delete"
PERMISSION_OBJECTS_ADD = "objects.add"
PERMISSION_OBJECTS_CHECKOUT = "objects.checkout"
PERMISSION_OBJECTS_CHECKIN = "objects.checkin"
PERMISSION_OBJECTS_REMOVE = "objects.remove"
PERMISSION_OBJECTS_REVERT = "objects.revert"
PERMISSION_OBJECTS_METADATA = "objects.metadata"

BUILTIN_ROLE_DESCRIPTIONS: dict[str, str] = {
    BuiltinRole.ADMINISTRATOR.value: "Full system administration access.",
    BuiltinRole.PDM_MANAGER.value: "Manage engineering data without full server administration.",
    BuiltinRole.ENGINEER.value: "Normal CAD/PDM authoring user.",
    BuiltinRole.VIEWER.value: "Read-only access to assigned projects.",
}

BUILTIN_PERMISSIONS: tuple[tuple[str, str], ...] = (
    (PERMISSION_USERS_MANAGE, "Create, edit, and disable users"),
    (PERMISSION_SETTINGS_MANAGE, "Change global CreoPDM settings"),
    (PERMISSION_PROJECTS_CREATE, "Create projects"),
    (PERMISSION_PROJECTS_EDIT, "Edit project properties"),
    (PERMISSION_PROJECTS_DELETE, "Delete or forget projects"),
    (PERMISSION_OBJECTS_ADD, "Add files and folders to projects"),
    (PERMISSION_OBJECTS_CHECKOUT, "Check out objects and undo own checkout"),
    (PERMISSION_OBJECTS_CHECKIN, "Check in objects"),
    (PERMISSION_OBJECTS_REMOVE, "Remove objects from projects"),
    (PERMISSION_OBJECTS_REVERT, "Restore an older version as the working version"),
    (PERMISSION_OBJECTS_METADATA, "Update Creo metadata on objects"),
)

# Role → permission keys (Administrator gets all via short-circuit + explicit seed).
_AUTHORING = (
    PERMISSION_OBJECTS_ADD,
    PERMISSION_OBJECTS_CHECKOUT,
    PERMISSION_OBJECTS_CHECKIN,
    PERMISSION_OBJECTS_REMOVE,
    PERMISSION_OBJECTS_REVERT,
    PERMISSION_OBJECTS_METADATA,
)

ROLE_PERMISSION_KEYS: dict[str, tuple[str, ...]] = {
    BuiltinRole.ADMINISTRATOR.value: tuple(key for key, _ in BUILTIN_PERMISSIONS),
    BuiltinRole.PDM_MANAGER.value: (
        PERMISSION_PROJECTS_CREATE,
        PERMISSION_PROJECTS_EDIT,
        *_AUTHORING,
    ),
    BuiltinRole.ENGINEER.value: _AUTHORING,
    BuiltinRole.VIEWER.value: (),
}

# Caps granted when auth is disabled (unit/integration tests).
TEST_AUTH_PERMISSIONS: frozenset[str] = frozenset(key for key, _ in BUILTIN_PERMISSIONS)
