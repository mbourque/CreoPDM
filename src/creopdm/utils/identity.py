"""Local user identity. Session auth replaces OS identity when enabled."""

from __future__ import annotations

import getpass
import platform
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserIdentity:
    user_name: str
    machine_name: str
    user_uuid: str | None = None
    display_name: str | None = None


_request_identity: ContextVar[UserIdentity | None] = ContextVar("creopdm_request_identity", default=None)


def set_request_identity(identity: UserIdentity | None) -> None:
    _request_identity.set(identity)


def get_request_identity() -> UserIdentity | None:
    return _request_identity.get()


class CurrentUserProvider:
    """Fallback OS identity when auth is disabled (tests / legacy)."""

    def get_current_user(self) -> UserIdentity:
        user_name = getpass.getuser() or "unknown"
        machine_name = platform.node() or "unknown"
        return UserIdentity(user_name=user_name, machine_name=machine_name)


class StaticUserProvider(CurrentUserProvider):
    """Test/replaceable identity."""

    def __init__(self, user_name: str, machine_name: str) -> None:
        self._identity = UserIdentity(user_name=user_name, machine_name=machine_name)

    def become(self, user_name: str, machine_name: str) -> None:
        self._identity = UserIdentity(user_name=user_name, machine_name=machine_name)

    def get_current_user(self) -> UserIdentity:
        return self._identity


class SessionAwareUserProvider(CurrentUserProvider):
    """Prefer per-request session identity."""

    def get_current_user(self) -> UserIdentity:
        current = get_request_identity()
        if current is not None:
            return current
        raise RuntimeError("No authenticated user for this request.")
