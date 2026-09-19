import os
import stat
from pathlib import Path

from creopdm.utils.files import format_byte_size, set_file_readonly, set_file_writable


def test_format_byte_size():
    assert format_byte_size(0) == "0 B"
    assert format_byte_size(873) == "873 B"
    assert format_byte_size(1024) == "1 KB"
    assert format_byte_size(275543) == "269 KB"
    assert format_byte_size(164362) == "161 KB"
    assert format_byte_size(5 * 1024 * 1024) == "5 MB"
    assert format_byte_size(1536 * 1024) == "1.5 MB"
    assert format_byte_size(None) == "—"


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


def test_copy_file_hashed_matches_sha256(tmp_path: Path):
    from creopdm.utils.files import copy_file_hashed
    from creopdm.utils.hashing import calculate_sha256

    source = tmp_path / "part.prt.3"
    dest = tmp_path / "CAD" / "part.prt.3"
    source.write_bytes(b"creo-model-bytes")
    created, digest, size = copy_file_hashed(source, dest)
    assert created is True
    assert dest.read_bytes() == b"creo-model-bytes"
    assert size == len(b"creo-model-bytes")
    assert digest == calculate_sha256(dest)
    created_again, digest_again, size_again = copy_file_hashed(source, dest)
    assert created_again is False
    assert digest_again == digest
    assert size_again == size


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


def test_set_hidden_roundtrip(tmp_path: Path):
    from creopdm.utils.files import is_hidden, set_hidden

    folder = tmp_path / ".creopdm"
    folder.mkdir()
    ignore = tmp_path / ".gitignore"
    ignore.write_text("*.tst\n", encoding="utf-8")
    set_hidden(folder)
    set_hidden(ignore)
    if os.name == "nt":
        assert is_hidden(folder)
        assert is_hidden(ignore)
        set_hidden(ignore, False)
        assert not is_hidden(ignore)
    else:
        assert is_hidden(folder)
        assert is_hidden(ignore)
