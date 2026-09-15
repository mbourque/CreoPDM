"""Version storage abstraction. Git is one implementation, not the user model."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from creopdm.utils.identity import UserIdentity


@dataclass(frozen=True, slots=True)
class StoredVersion:
    version_ref: str
    message: str
    author: str
    timestamp: str


class VersionStore(ABC):
    """Content-addressed version storage used by PDM services."""

    @abstractmethod
    def store_version(
        self,
        repository_path: Path,
        relative_paths: list[str],
        message: str,
        author: UserIdentity,
        allow_empty: bool = False,
        remove_relative_paths: list[str] | None = None,
    ) -> str:
        """Persist files and return a storage version reference (commit hash for Git)."""

    @abstractmethod
    def restore_version(
        self,
        repository_path: Path,
        relative_path: str,
        version_ref: str,
    ) -> None:
        """Materialize a historical version into the repository working tree."""

    @abstractmethod
    def get_history(
        self,
        repository_path: Path,
        relative_path: str | None = None,
    ) -> list[StoredVersion]:
        """Return storage-level history. UI should prefer object_versions."""

    @abstractmethod
    def get_version(
        self,
        repository_path: Path,
        relative_path: str,
        version_ref: str,
    ) -> bytes:
        """Read a blob for a stored version without changing the working tree."""

    @abstractmethod
    def capture_checkpoint(self, repository_path: Path) -> str | None:
        """Capture storage state so a failed metadata write can be compensated."""

    @abstractmethod
    def restore_checkpoint(self, repository_path: Path, checkpoint: str) -> None:
        """Restore storage to a captured checkpoint. Never used as a user-facing undo."""

    @abstractmethod
    def remove_files(
        self,
        repository_path: Path,
        relative_paths: list[str],
        message: str,
        author: UserIdentity,
    ) -> str:
        """Remove files from storage and return the new version reference."""
