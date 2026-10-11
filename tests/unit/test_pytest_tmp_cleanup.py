"""Repo-root pytest-tmp / pytest-tmp-* dirs are scrubbed before/after each pytest run."""

from __future__ import annotations

import stat
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


def test_cleanup_stale_pytest_tmp_removes_readonly_tree(tmp_path: Path):
    """Windows often leaves read-only files; cleanup must still wipe the tree."""
    tree = tmp_path / "pytest-tmp-readonly"
    nested = tree / "a" / "b"
    nested.mkdir(parents=True)
    locked = nested / "creopdm.db"
    locked.write_bytes(b"x")
    locked.chmod(stat.S_IREAD)
    tree.chmod(stat.S_IREAD)
    assert cleanup_stale_pytest_tmp(tmp_path, retries=2, retry_delay_s=0.01) == 1
    assert not tree.exists()


def test_cleanup_after_session_removes_all_without_keep():
    """sessionfinish must scrub every pytest-tmp* (no keep of the current run)."""
    root = Path(__file__).resolve().parents[2]
    conftest = (root / "tests" / "conftest.py").read_text(encoding="utf-8")
    finish = conftest.split("def pytest_sessionfinish", 1)[1].split(
        "@pytest.fixture", 1
    )[0]
    assert "cleanup_stale_pytest_tmp(root" in finish
    assert "keep=" not in finish
    assert "retries=" in finish
    assert "shutil.rmtree" not in finish


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
    helper = (root / "tests" / "pytest_basetemp.py").read_text(encoding="utf-8")
    assert "def _rmtree_force(" in helper
    assert "gc.collect()" in helper
