"""Repo-root pytest-tmp / pytest-tmp-* dirs are scrubbed before/after each pytest run."""

from __future__ import annotations

from pathlib import Path

from tests.pytest_basetemp import cleanup_stale_pytest_tmp


def test_cleanup_stale_pytest_tmp_removes_old_keeps_current(tmp_path: Path):
    old = tmp_path / "pytest-tmp-111-222"
    old.mkdir()
    (old / "junk.txt").write_text("x", encoding="utf-8")
    current = tmp_path / "pytest-tmp-333-444"
    current.mkdir()
    (current / "keep.txt").write_text("y", encoding="utf-8")

    removed = cleanup_stale_pytest_tmp(tmp_path, keep=current)
    assert removed == 1
    assert not old.exists()
    assert current.is_dir()
    assert (current / "keep.txt").read_text(encoding="utf-8") == "y"


def test_cleanup_stale_pytest_tmp_removes_plain_pytest_tmp(tmp_path: Path):
    """Legacy shared basetemp name ``pytest-tmp`` is also removed."""
    legacy = tmp_path / "pytest-tmp"
    legacy.mkdir()
    (legacy / "creopdm.db").write_bytes(b"x")
    assert cleanup_stale_pytest_tmp(tmp_path) == 1
    assert not legacy.exists()


def test_conftest_scrubs_before_and_after_session():
    """Any pytest invocation must hook cleanup in configure + sessionfinish."""
    root = Path(__file__).resolve().parents[2]
    conftest = (root / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "cleanup_stale_pytest_tmp(root)" in conftest
    assert "def pytest_configure" in conftest
    assert "def pytest_sessionfinish" in conftest
    assert conftest.index("cleanup_stale_pytest_tmp(root)") < conftest.index(
        'config.option.basetemp = str(base)'
    )
