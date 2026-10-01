"""Regression: low-risk reliability fixes from the Astra review."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from creopdm_agent.config import AgentConfig
from creopdm_agent.server import (
    CachePlanItem,
    _find_planned_cache_file,
    _plan_cache_downloads,
    create_agent_app,
)
from creopdm.config import ConfigManager
from creopdm.exceptions import PathValidationError, RepositoryError
from creopdm.services.git_service import GitService, clear_stale_git_index_lock
from creopdm.services.workspace_service import WorkspaceService
from creopdm.utils.identity import UserIdentity
from tests.conftest import requires_git


def test_find_planned_cache_file_prefers_relative_folder(tmp_path: Path):
    cache = tmp_path / "prod"
    (cache / "lib" / "a").mkdir(parents=True)
    (cache / "lib" / "b").mkdir(parents=True)
    (cache / "lib" / "a" / "pin.prt.1").write_bytes(b"folder-a")
    (cache / "lib" / "b" / "pin.prt.2").write_bytes(b"folder-b-newer-number")
    found = _find_planned_cache_file(
        cache,
        CachePlanItem(
            object_id="x",
            filename="pin.prt",
            disk_name="pin.prt.1",
            relative_path="lib/a/pin.prt",
        ),
    )
    assert found is not None
    assert found.read_bytes() == b"folder-a"
    assert found.parent.name == "a"


def test_push_uses_relative_path_not_other_folder_duplicate(tmp_path: Path, monkeypatch):
    root = tmp_path / "agent"
    product_id = "prod-1"
    cache = root / product_id
    (cache / "lib" / "a").mkdir(parents=True)
    (cache / "lib" / "b").mkdir(parents=True)
    (cache / "lib" / "a" / "pin.prt.1").write_bytes(b"correct-model")
    (cache / "lib" / "b" / "pin.prt.9").write_bytes(b"wrong-model")
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(root))
    app = create_agent_app(settings)
    uploaded: list[bytes] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"path": "/vault/lib/a/pin.prt.1", "bytes_written": len(uploaded[-1])}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def put(self, url, headers=None, files=None):
            handle = files["file"][1]
            uploaded.append(handle.read())
            return FakeResponse()

    monkeypatch.setattr("httpx.Client", FakeClient)
    client = TestClient(app)
    response = client.post(
        "/push",
        json={
            "pdm_url": "http://pdm.test",
            "product_id": product_id,
            "items": [
                {
                    "object_id": "obj-a",
                    "filename": "pin.prt.1",
                    "relative_path": "lib/a/pin.prt",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"]
    assert not body["failed"]
    assert uploaded == [b"correct-model"]


def test_stage_new_rejects_reserved_git_path(tmp_path: Path):
    manager = ConfigManager(tmp_path / "data")
    manager.ensure_layout()
    workspaces = WorkspaceService(manager, GitService())
    product = SimpleNamespace(uuid="u1", vault_folder="u1")
    vault = workspaces.vault_for(product)
    vault.mkdir(parents=True, exist_ok=True)
    with pytest.raises(PathValidationError, match="reserved"):
        workspaces.stage_new_workspace_file(product, ".git/config", b"evil")


def test_plan_cache_does_not_skip_on_size_alone(tmp_path: Path):
    """Same byte length as vault must not skip when content_hash differs."""
    cache = tmp_path / "prod"
    cache.mkdir()
    local = b"AAAA"
    (cache / "pin.prt.1").write_bytes(local)
    wrong_hash = hashlib.sha256(b"BBBB").hexdigest()
    download_ids, skipped, kept = _plan_cache_downloads(
        cache,
        [
            CachePlanItem(
                object_id="same-size-diff-bytes",
                filename="pin.prt.1",
                disk_name="pin.prt.1",
                content_hash=wrong_hash,
                file_size=len(local),
            )
        ],
    )
    assert download_ids == ["same-size-diff-bytes"]
    assert skipped == 0
    assert kept == 0


def test_index_lock_retry_keeps_full_stale_window(tmp_path: Path, monkeypatch):
    """Later retries must not delete locks that are only a few seconds old."""
    ages: list[float] = []

    def capture_clear(repo, *, max_age_sec=20.0):
        ages.append(max_age_sec)
        return False

    monkeypatch.setattr(
        "creopdm.services.git_service.clear_stale_git_index_lock",
        capture_clear,
    )
    monkeypatch.setattr("creopdm.services.git_service.time.sleep", lambda *_a, **_k: None)
    git = GitService()
    calls = {"n": 0}

    def always_locked(args, cwd, check=True, quiet=False):
        calls["n"] += 1
        from creopdm.exceptions import RepositoryError

        raise RepositoryError(
            f"fatal: Unable to create '{cwd.as_posix()}/.git/index.lock': File exists."
        )

    monkeypatch.setattr(git, "_run", always_locked)
    with pytest.raises(Exception):
        git.run_with_index_lock_retry(["status"], cwd=tmp_path)
    assert ages
    assert all(age >= 20.0 for age in ages)


def test_clear_stale_git_index_lock_still_removes_old_file(tmp_path: Path):
    import os
    import time

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    lock = git_dir / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    old = time.time() - 120
    os.utime(lock, (old, old))
    assert clear_stale_git_index_lock(tmp_path, max_age_sec=20) is True
    assert not lock.exists()


@requires_git
def test_remove_product_folder_commits_before_disk_delete(tmp_path: Path):
    """Happy path: Git records the removal, then the folder leaves disk."""
    manager = ConfigManager(tmp_path / "data")
    manager.ensure_layout()
    git = GitService()
    workspaces = WorkspaceService(manager, git)
    product = SimpleNamespace(uuid="u-folder", vault_folder="u-folder")
    user = UserIdentity("tester", "test-pc")
    vault = workspaces.vault_for(product)
    git.init_repository(vault, "main")
    folder = vault / "Drawings"
    folder.mkdir()
    keep = folder / ".gitkeep"
    keep.write_text("", encoding="utf-8")
    git.stage_files(vault, ["Drawings/.gitkeep"])
    git.commit(vault, "add Drawings", user)

    workspaces.remove_product_folder(product, "Drawings", user)
    assert not folder.exists()
    status = git.status(vault)
    assert not status.staged
    assert not status.unstaged
    assert not status.untracked


@requires_git
def test_remove_product_folder_git_failure_leaves_disk(tmp_path: Path, monkeypatch):
    """Regression: do not delete disk when Git commit fails (no silent split)."""
    manager = ConfigManager(tmp_path / "data")
    manager.ensure_layout()
    git = GitService()
    workspaces = WorkspaceService(manager, git)
    product = SimpleNamespace(uuid="u-fail", vault_folder="u-fail")
    user = UserIdentity("tester", "test-pc")
    vault = workspaces.vault_for(product)
    git.init_repository(vault, "main")
    folder = vault / "Incoming"
    folder.mkdir()
    keep = folder / ".gitkeep"
    keep.write_bytes(b"")
    git.stage_files(vault, ["Incoming/.gitkeep"])
    git.commit(vault, "add Incoming", user)

    def boom(*_a, **_k):
        raise RepositoryError("simulated commit failure")

    monkeypatch.setattr(git, "commit", boom)
    with pytest.raises(RepositoryError, match="simulated commit failure"):
        workspaces.remove_product_folder(product, "Incoming", user)
    assert keep.is_file()
    assert folder.is_dir()
