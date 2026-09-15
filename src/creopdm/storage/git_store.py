"""Git-backed VersionStore. Future stores can replace this without changing services."""

from __future__ import annotations

from pathlib import Path

from creopdm.services.git_service import GitService
from creopdm.storage.base import StoredVersion, VersionStore
from creopdm.utils.identity import UserIdentity


class GitVersionStore(VersionStore):
    def __init__(self, git: GitService) -> None:
        self._git = git

    def store_version(
        self,
        repository_path: Path,
        relative_paths: list[str],
        message: str,
        author: UserIdentity,
        allow_empty: bool = False,
        remove_relative_paths: list[str] | None = None,
    ) -> str:
        if remove_relative_paths:
            self._git.remove_files(repository_path, remove_relative_paths)
        self._git.stage_files(repository_path, relative_paths)
        return self._git.commit(
            repository_path,
            message,
            author,
            allow_empty=allow_empty,
        )

    def restore_version(
        self,
        repository_path: Path,
        relative_path: str,
        version_ref: str,
    ) -> None:
        self._git.restore_file(repository_path, relative_path, version_ref)

    def get_history(
        self,
        repository_path: Path,
        relative_path: str | None = None,
    ) -> list[StoredVersion]:
        entries = self._git.get_history(repository_path, relative_path)
        return [
            StoredVersion(
                version_ref=entry.commit_hash,
                message=entry.message,
                author=entry.author,
                timestamp=entry.timestamp,
            )
            for entry in entries
        ]

    def get_version(
        self,
        repository_path: Path,
        relative_path: str,
        version_ref: str,
    ) -> bytes:
        return self._git.show_file(repository_path, relative_path, version_ref)

    def capture_checkpoint(self, repository_path: Path) -> str | None:
        try:
            return self._git.get_head(repository_path)
        except Exception:
            return None

    def restore_checkpoint(self, repository_path: Path, checkpoint: str) -> None:
        self._git.reset_to(repository_path, checkpoint)

    def remove_files(
        self,
        repository_path: Path,
        relative_paths: list[str],
        message: str,
        author: UserIdentity,
    ) -> str:
        self._git.remove_files(repository_path, relative_paths)
        if not self._git.is_dirty(repository_path):
            return self._git.get_head(repository_path)
        return self._git.commit(repository_path, message, author)
