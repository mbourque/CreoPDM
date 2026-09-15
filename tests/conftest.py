from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.services.git_service import GitService
from creopdm.utils.identity import StaticUserProvider


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    root = tmp_path / "appdata"
    monkeypatch.setenv("CREOPDM_DATA_DIR", str(root))
    return root


@pytest.fixture()
def identity():
    return StaticUserProvider("Alice", "ENG-PC-17")


@pytest.fixture()
def app(data_dir, identity):
    return create_app(build_context(ConfigManager(), users=identity))


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def repo_parent(tmp_path):
    path = tmp_path / "repos"
    path.mkdir()
    return path


def git_available() -> bool:
    return GitService().is_available()


requires_git = pytest.mark.skipif(not git_available(), reason="Git is not available on PATH")
