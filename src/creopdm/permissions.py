"""Request capability helpers for role-based access."""

from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request

from creopdm.auth_constants import (
    PERMISSION_OBJECTS_ADD,
    PERMISSION_OBJECTS_CHECKIN,
    PERMISSION_OBJECTS_CHECKOUT,
    PERMISSION_OBJECTS_METADATA,
    PERMISSION_OBJECTS_REMOVE,
    PERMISSION_OBJECTS_REVERT,
    PERMISSION_PROJECTS_CREATE,
    PERMISSION_PROJECTS_DELETE,
    PERMISSION_PROJECTS_EDIT,
    PERMISSION_SETTINGS_MANAGE,
    PERMISSION_USERS_MANAGE,
    TEST_AUTH_PERMISSIONS,
)
from creopdm.models.user import User
from creopdm.services.user_service import UserService


@dataclass(frozen=True, slots=True)
class CapabilityFlags:
    permissions: frozenset[str]
    can_manage_users: bool
    can_manage_settings: bool
    can_create_project: bool
    can_edit_project: bool
    can_delete_project: bool
    can_add_objects: bool
    can_checkout: bool
    can_checkin: bool
    can_remove_objects: bool
    can_revert_objects: bool
    can_update_metadata: bool


def caps_from_keys(keys: frozenset[str]) -> CapabilityFlags:
    return CapabilityFlags(
        permissions=keys,
        can_manage_users=PERMISSION_USERS_MANAGE in keys,
        can_manage_settings=PERMISSION_SETTINGS_MANAGE in keys,
        can_create_project=PERMISSION_PROJECTS_CREATE in keys,
        can_edit_project=PERMISSION_PROJECTS_EDIT in keys,
        can_delete_project=PERMISSION_PROJECTS_DELETE in keys,
        can_add_objects=PERMISSION_OBJECTS_ADD in keys,
        can_checkout=PERMISSION_OBJECTS_CHECKOUT in keys,
        can_checkin=PERMISSION_OBJECTS_CHECKIN in keys,
        can_remove_objects=PERMISSION_OBJECTS_REMOVE in keys,
        can_revert_objects=PERMISSION_OBJECTS_REVERT in keys,
        can_update_metadata=PERMISSION_OBJECTS_METADATA in keys,
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
    request.state.can_manage_settings = caps.can_manage_settings
    request.state.can_create_project = caps.can_create_project
    request.state.can_edit_project = caps.can_edit_project
    request.state.can_delete_project = caps.can_delete_project
    request.state.can_add_objects = caps.can_add_objects
    request.state.can_checkout = caps.can_checkout
    request.state.can_checkin = caps.can_checkin
    request.state.can_remove_objects = caps.can_remove_objects
    request.state.can_revert_objects = caps.can_revert_objects
    request.state.can_update_metadata = caps.can_update_metadata


def caps_dict(request: Request) -> dict:
    return {
        "can_manage_users": bool(getattr(request.state, "can_manage_users", False)),
        "can_manage_settings": bool(getattr(request.state, "can_manage_settings", False)),
        "can_create_project": bool(getattr(request.state, "can_create_project", False)),
        "can_edit_project": bool(getattr(request.state, "can_edit_project", False)),
        "can_delete_project": bool(getattr(request.state, "can_delete_project", False)),
        "can_add_objects": bool(getattr(request.state, "can_add_objects", False)),
        "can_checkout": bool(getattr(request.state, "can_checkout", False)),
        "can_checkin": bool(getattr(request.state, "can_checkin", False)),
        "can_remove_objects": bool(getattr(request.state, "can_remove_objects", False)),
        "can_revert_objects": bool(getattr(request.state, "can_revert_objects", False)),
        "can_update_metadata": bool(getattr(request.state, "can_update_metadata", False)),
    }
