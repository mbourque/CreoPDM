from __future__ import annotations

from pathlib import Path

from creopdm_agent.trash import (
    clear_directory_contents,
    move_to_trash,
    prepare_path_for_delete,
)


def test_move_to_trash_removes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_move_to_trash_removes_file")
    target = tmp_path / "shaft.prt.1"
    target.write_bytes(b"1")
    move_to_trash(target)
    assert not target.exists()


def test_move_to_trash_prepares_hidden_before_delete(tmp_path, monkeypatch):
    """Remove-from-Product /delete-paths must clear Hidden like Clear workspace."""
    target = tmp_path / "shaft.prt.2"
    target.write_bytes(b"2")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_move_to_trash_prepares_hidden")
    prepared: list[Path] = []

    def fake_prepare(path):
        prepared.append(Path(path))

    monkeypatch.setattr("creopdm_agent.trash.prepare_path_for_delete", fake_prepare)
    move_to_trash(target)
    assert prepared == [target]
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


def test_clear_directory_contents_one_shot_recycle(tmp_path, monkeypatch):
    """Clear workspace must recycle all top-level children in one Shell call."""
    root = tmp_path / "cache"
    root.mkdir()
    (root / "a.prt").write_bytes(b"a")
    nested = root / "docs"
    nested.mkdir()
    (nested / "notes.txt").write_text("hi", encoding="utf-8")
    (root / "b.asm").write_bytes(b"b")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("creopdm_agent.trash.sys.platform", "win32")

    batches: list[list[Path]] = []

    def fake_many(paths: list[Path]) -> None:
        batches.append(list(paths))
        for path in paths:
            if path.is_dir():
                import shutil

                shutil.rmtree(path)
            else:
                path.unlink()

    monkeypatch.setattr("creopdm_agent.trash._windows_recycle_bin_many", fake_many)
    removed, failed = clear_directory_contents(root)
    assert failed == []
    assert removed == 3
    assert len(batches) == 1
    assert {p.name for p in batches[0]} == {"a.prt", "b.asm", "docs"}
    assert root.is_dir()
    assert list(root.iterdir()) == []


def test_clear_directory_contents_sweeps_nested_leftovers(tmp_path, monkeypatch):
    """Clear workspace must empty *everything* — cache index, nested junk, all types.

    Simulate a partial recycle that leaves some children; the hard-purge sweep
    must still leave the workspace folder empty.
    """
    root = tmp_path / "cache"
    root.mkdir()
    (root / "shaft.prt").write_bytes(b"prt")
    (root / "notes.txt").write_text("notes", encoding="utf-8")
    (root / ".creopdm_cache_index.json").write_text("{}", encoding="utf-8")
    nested = root / "sub"
    nested.mkdir()
    (nested / "extra.txt").write_text("extra", encoding="utf-8")
    (nested / "orphan.bin").write_bytes(b"x")
    # Dotfiles nested under a folder — pathlib rglob('*') historically skips these.
    (nested / ".hidden_meta").write_text("hidden", encoding="utf-8")
    deep = nested / ".secret_dir"
    deep.mkdir()
    (deep / "inside.bin").write_bytes(b"z")

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("creopdm_agent.trash.sys.platform", "win32")

    def fake_many(paths: list[Path]) -> None:
        # Recycle only the CAD tip — leave other files/nested behind.
        for path in paths:
            if path.name == "shaft.prt":
                path.unlink()

    monkeypatch.setattr("creopdm_agent.trash._windows_recycle_bin_many", fake_many)
    removed, failed = clear_directory_contents(root)
    assert failed == []
    assert removed >= 1
    assert root.is_dir()
    assert list(root.iterdir()) == []


def test_hard_purge_finds_dotfiles_rglob_skips(tmp_path, monkeypatch):
    """Regression: os.walk must see '.hidden' that Path.rglob('*') can miss."""
    from creopdm_agent.trash import _hard_purge_remaining, _iter_all_under

    root = tmp_path / "cache"
    root.mkdir()
    nested = root / "sub"
    nested.mkdir()
    hidden = nested / ".hidden"
    hidden.write_text("x", encoding="utf-8")
    assert any(p.name == ".hidden" for p in _iter_all_under(root))
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_hard_purge_finds_dotfiles")
    removed, failed = _hard_purge_remaining(root)
    assert failed == []
    assert removed >= 1
    assert list(root.iterdir()) == []


def test_prepare_path_for_delete_clears_nested_hidden(tmp_path, monkeypatch):
    """One prep helper walks folders so Clear and Remove share the same path."""
    root = tmp_path / "folder"
    root.mkdir()
    nested = root / "sub"
    nested.mkdir()
    tip = nested / "shaft.prt.1"
    tip.write_bytes(b"1")
    cleared: list[str] = []

    def fake_clear(path):
        cleared.append(Path(path).name)

    monkeypatch.setattr("creopdm_agent.trash.sys.platform", "win32")
    monkeypatch.setattr("creopdm_agent.trash._clear_windows_hidden_system", fake_clear)
    prepare_path_for_delete(root)
    assert "folder" in cleared
    assert "sub" in cleared
    assert "shaft.prt.1" in cleared


def test_clear_directory_contents_uses_prepare_path_for_delete(tmp_path, monkeypatch):
    """Clear workspace must go through the shared Hidden/System prep (DRY)."""
    root = tmp_path / "cache"
    root.mkdir()
    (root / "a.prt").write_bytes(b"a")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr("creopdm_agent.trash.sys.platform", "win32")
    prepared: list[str] = []

    def fake_prepare(path):
        prepared.append(Path(path).name)

    def fake_many(paths: list):
        for path in paths:
            Path(path).unlink()

    monkeypatch.setattr("creopdm_agent.trash.prepare_path_for_delete", fake_prepare)
    monkeypatch.setattr("creopdm_agent.trash._windows_recycle_bin_many", fake_many)
    clear_directory_contents(root)
    assert "a.prt" in prepared
