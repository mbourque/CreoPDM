import os
import stat
from pathlib import Path

from creopdm.utils.files import set_file_readonly, set_file_writable


def test_readonly_and_writable_roundtrip(tmp_path: Path):
    path = tmp_path / "part.prt"
    path.write_text("solid", encoding="utf-8")
    set_file_readonly(path)
    readonly_bit_cleared = not (path.stat().st_mode & stat.S_IWRITE)
    readonly_attr = False
    if os.name == "nt" and hasattr(path.stat(), "st_file_attributes"):
        readonly_attr = bool(path.stat().st_file_attributes & 0x1)
    write_blocked = False
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write("x")
    except OSError:
        write_blocked = True
    assert readonly_bit_cleared or readonly_attr or write_blocked
    set_file_writable(path)
    path.write_text("changed", encoding="utf-8")
    assert path.read_text(encoding="utf-8") == "changed"


def test_copy_file_skips_same_path(tmp_path: Path):
    from creopdm.utils.files import copy_file

    path = tmp_path / "part.prt"
    path.write_bytes(b"same")
    assert copy_file(path, path) is False
    assert path.read_bytes() == b"same"


def test_copy_file_reports_new_file(tmp_path: Path):
    from creopdm.utils.files import copy_file

    source = tmp_path / "part.prt"
    dest = tmp_path / "CAD" / "part.prt"
    source.write_bytes(b"model")
    assert copy_file(source, dest) is True
    assert dest.read_bytes() == b"model"
    assert copy_file(source, dest) is False


def test_prune_empty_dirs_removes_nested_tree_not_root(tmp_path: Path):
    from creopdm.utils.files import prune_empty_dirs

    nested = tmp_path / "html_tutorials" / "css"
    nested.mkdir(parents=True)
    leftover = tmp_path / "keep" / "notes.txt"
    leftover.parent.mkdir()
    leftover.write_text("stay", encoding="utf-8")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    prune_empty_dirs(nested, tmp_path, reserved_names=frozenset({".git"}))
    assert not (tmp_path / "html_tutorials").exists()
    assert leftover.is_file()
    assert git_dir.is_dir()
    assert tmp_path.is_dir()


def test_prune_empty_dirs_stops_when_sibling_file_remains(tmp_path: Path):
    from creopdm.utils.files import prune_empty_dirs

    folder = tmp_path / "html_tutorials"
    nested = folder / "css"
    nested.mkdir(parents=True)
    (folder / "index.html").write_text("home", encoding="utf-8")
    prune_empty_dirs(nested, tmp_path)
    assert not nested.exists()
    assert (folder / "index.html").is_file()
