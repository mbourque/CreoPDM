"""Regression: vault import must survive transient .git/index.lock conflicts."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from creopdm.exceptions import RepositoryError
from creopdm.services.git_service import (
    GitService,
    clear_stale_git_index_lock,
    is_git_index_lock_error,
)
from creopdm.utils.identity import UserIdentity
from tests.conftest import requires_git


def test_is_git_index_lock_error_matches_known_messages():
    assert is_git_index_lock_error(
        "fatal: Unable to create '/vault/.git/index.lock': File exists."
    )
    assert is_git_index_lock_error(
        "fatal: sha1 file '/vault/.git/index.lock' write error. Out of diskspace"
    )
    assert not is_git_index_lock_error("fatal: pathspec 'missing' did not match")


def test_clear_stale_git_index_lock_removes_old_file(tmp_path: Path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    lock = git_dir / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    old = time.time() - 120
    # Touch mtime into the past so the lock counts as stale.
    import os

    os.utime(lock, (old, old))
    assert clear_stale_git_index_lock(tmp_path, max_age_sec=30) is True
    assert not lock.exists()


def test_clear_stale_git_index_lock_keeps_fresh_file(tmp_path: Path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    lock = git_dir / "index.lock"
    lock.write_text("live", encoding="utf-8")
    assert clear_stale_git_index_lock(tmp_path, max_age_sec=30) is False
    assert lock.exists()


def test_clear_stale_git_index_lock_keeps_lock_while_git_uses_repo(tmp_path: Path, monkeypatch):
    """A long-running git commit must not lose index.lock just because it is old."""
    import os
    import time

    from creopdm.services import git_service

    assert git_service._INDEX_LOCK_STALE_SEC >= 900
    assert 60 <= git_service._INDEX_LOCK_STALE_SEC_OTHER <= 120
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    lock = git_dir / "index.lock"
    lock.write_text("live", encoding="utf-8")
    old = time.time() - 3600
    os.utime(lock, (old, old))
    monkeypatch.setattr(git_service, "_git_process_uses_repo", lambda _repo: True)
    assert clear_stale_git_index_lock(tmp_path, max_age_sec=1) is False
    assert lock.exists()


def test_index_lock_age_is_long_only_when_git_processes_are_visible(tmp_path: Path, monkeypatch):
    """Without /proc, a dead lock is cleared after about a minute, not 15."""
    import os
    import time

    from creopdm.services import git_service

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    lock = git_dir / "index.lock"
    lock.write_text("dead", encoding="utf-8")
    three_minutes = time.time() - 180
    os.utime(lock, (three_minutes, three_minutes))
    monkeypatch.setattr(git_service, "_git_process_uses_repo", lambda _repo: False)

    monkeypatch.setattr(git_service, "_can_see_git_processes", lambda: True)
    assert git_service.index_lock_stale_sec() >= 900
    assert clear_stale_git_index_lock(tmp_path) is False
    assert lock.exists()

    monkeypatch.setattr(git_service, "_can_see_git_processes", lambda: False)
    assert git_service.index_lock_stale_sec() == git_service._INDEX_LOCK_STALE_SEC_OTHER
    assert clear_stale_git_index_lock(tmp_path) is True
    assert not lock.exists()


@requires_git
def test_commit_retries_after_index_lock_error(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    git = GitService()
    git.init_repository(repo, "main")
    (repo / "notes.txt").write_text("hello", encoding="utf-8")
    git.stage_files(repo, ["notes.txt"])
    author = UserIdentity(user_name="tester", machine_name="test-pc")

    calls = {"n": 0}
    real_run = git._run

    def flaky_run(args, cwd, check=True, extra_env=None, quiet=False):
        calls["n"] += 1
        # Fail the first commit attempt with the production error text.
        if args and args[0] == "-c" and "commit" in args and calls["n"] == 1:
            raise RepositoryError(
                "fatal: Unable to create "
                f"'{cwd.as_posix()}/.git/index.lock': File exists."
            )
        return real_run(args, cwd=cwd, check=check, extra_env=extra_env, quiet=quiet)

    monkeypatch.setattr(git, "_run", flaky_run)
    with patch("creopdm.services.git_service.time.sleep", return_value=None):
        commit = git.commit(repo, "Initial", author)
    assert len(commit) >= 7
    assert calls["n"] >= 2
