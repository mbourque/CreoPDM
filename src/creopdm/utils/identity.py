"""Local user identity. Replaceable later with real authentication."""

from __future__ import annotations

import getpass
import platform
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class UserIdentity:
    user_name: str
    machine_name: str


class CurrentUserProvider:
    """v0.1 identity comes from the OS. Do not hard-code usernames."""

    def get_current_user(self) -> UserIdentity:
        user_name = getpass.getuser() or "unknown"
        machine_name = platform.node() or "unknown"
        return UserIdentity(user_name=user_name, machine_name=machine_name)


class StaticUserProvider(CurrentUserProvider):
    """Test/replaceable identity. Authentication can swap this later."""

    def __init__(self, user_name: str, machine_name: str) -> None:
        self._identity = UserIdentity(user_name=user_name, machine_name=machine_name)

    def become(self, user_name: str, machine_name: str) -> None:
        self._identity = UserIdentity(user_name=user_name, machine_name=machine_name)

    def get_current_user(self) -> UserIdentity:
        return self._identity
