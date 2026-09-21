from __future__ import annotations

from pathlib import Path

from creopdm_agent.trash import move_to_trash


def test_move_to_trash_removes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_move_to_trash_removes_file")
    target = tmp_path / "shaft.prt.1"
    target.write_bytes(b"1")
    move_to_trash(target)
    assert not target.exists()


def test_move_to_trash_missing_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_move_to_trash_missing_is_noop")
    missing = tmp_path / "gone.prt.1"
    move_to_trash(missing)
    assert not missing.exists()


def test_move_to_trash_uses_windows_recycle_outside_pytest(tmp_path, monkeypatch):
    target = tmp_path / "shaft.prt.2"
    target.write_bytes(b"2")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("creopdm_agent.trash.sys.platform", "win32")

    calls: list[Path] = []

    def fake_recycle(path: Path) -> None:
        calls.append(path)
        path.unlink()

    monkeypatch.setattr("creopdm_agent.trash._windows_recycle_bin", fake_recycle)
    move_to_trash(target)
    assert calls == [target]
    assert not target.exists()
