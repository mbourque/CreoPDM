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

BUILTIN_ROLE_DESCRIPTIONS: dict[str, str] = {
    BuiltinRole.ADMINISTRATOR.value: "Full system administration access.",
    BuiltinRole.PDM_MANAGER.value: "Manage engineering data without full server administration.",
    BuiltinRole.ENGINEER.value: "Normal CAD/PDM authoring user.",
    BuiltinRole.VIEWER.value: "Read-only access to assigned projects.",
}

BUILTIN_PERMISSIONS: tuple[tuple[str, str], ...] = (
    (PERMISSION_USERS_MANAGE, "Create, edit, and disable users"),
    (PERMISSION_SETTINGS_MANAGE, "Change global CreoPDM settings"),
)
