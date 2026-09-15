"""Per-project application lock. Two mutations must not share a repository."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class ProjectLockManager:
    """Lock by project UUID around checkout, check-in, Git commit, and sync."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}

    def _lock_for(self, project_uuid: str) -> threading.RLock:
        with self._guard:
            if project_uuid not in self._locks:
                self._locks[project_uuid] = threading.RLock()
            return self._locks[project_uuid]

    @contextmanager
    def acquire(self, project_uuid: str) -> Iterator[None]:
        lock = self._lock_for(project_uuid)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def release(self, project_uuid: str) -> None:
        """Explicit release for non-context usage. Prefer acquire() as a context manager."""
        lock = self._lock_for(project_uuid)
        if lock._is_owned():  # type: ignore[attr-defined]
            lock.release()
