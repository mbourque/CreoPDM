import subprocess
from pathlib import Path

from creopdm.services.git_service import GitService


def test_git_run_decodes_output_as_utf8(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args[0], 0, stdout="ok", stderr="")

    monkeypatch.setattr("creopdm.services.git_service.subprocess.run", fake_run)
    GitService()._run(["status"], tmp_path, check=False)
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert "text" not in captured


def test_git_is_available_decodes_output_as_utf8(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args[0], 0, stdout="git version 2.0", stderr="")

    monkeypatch.setattr("creopdm.services.git_service.subprocess.run", fake_run)
    assert GitService().is_available() is True
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
