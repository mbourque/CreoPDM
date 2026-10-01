"""Unit tests for Add ▾ → Compressed data… zip extract / strip-root planning."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from creopdm.exceptions import PathValidationError, ValidationAppError
from creopdm.utils.zip_import import (
    MAX_ZIP_IMPORT_BYTES,
    assert_zip_filename,
    extract_zip_safely,
    extract_zip_to_temp,
    normalize_zip_parent_folder,
    plan_zip_import_jobs,
    strip_single_zip_root,
)


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def test_assert_zip_filename_requires_zip_suffix():
    assert assert_zip_filename("pack.ZIP") == "pack.ZIP"
    with pytest.raises(ValidationAppError, match="Only .zip"):
        assert_zip_filename("pack.rar")
    with pytest.raises(ValidationAppError, match="required"):
        assert_zip_filename("")


def test_strip_single_zip_root_when_one_folder(tmp_path: Path):
    root = tmp_path / "extracted"
    (root / "MyExport" / "lib").mkdir(parents=True)
    (root / "MyExport" / "a.prt").write_bytes(b"a")
    (root / "MyExport" / "lib" / "b.prt").write_bytes(b"b")
    assert strip_single_zip_root(root) == root / "MyExport"


def test_strip_single_zip_root_keeps_multi_root(tmp_path: Path):
    root = tmp_path / "extracted"
    root.mkdir()
    (root / "Alpha").mkdir()
    (root / "Beta").mkdir()
    (root / "Alpha" / "a.prt").write_bytes(b"a")
    (root / "Beta" / "b.prt").write_bytes(b"b")
    assert strip_single_zip_root(root) == root


def test_strip_single_zip_root_keeps_files_at_root(tmp_path: Path):
    root = tmp_path / "extracted"
    root.mkdir()
    (root / "a.prt").write_bytes(b"a")
    (root / "Nested").mkdir()
    (root / "Nested" / "b.prt").write_bytes(b"b")
    assert strip_single_zip_root(root) == root


def test_extract_skips_junk_and_preserves_tree(tmp_path: Path):
    zip_path = tmp_path / "pack.zip"
    _write_zip(
        zip_path,
        {
            "MyExport/part.prt": b"part",
            "MyExport/sub/assy.asm": b"assy",
            "MyExport/.DS_Store": b"junk",
            "__MACOSX/._part.prt": b"apple",
            "MyExport/Thumbs.db": b"thumbs",
            "MyExport/empty/": b"",
        },
    )
    parent, extract_dir = extract_zip_to_temp(zip_path)
    try:
        names = {p.relative_to(extract_dir).as_posix() for p in extract_dir.rglob("*") if p.is_file()}
        assert names == {"MyExport/part.prt", "MyExport/sub/assy.asm"}
        jobs = plan_zip_import_jobs(extract_dir, parent_folder="Drawings")
        rels = sorted(rel for _src, _name, rel in jobs)
        assert rels == ["Drawings/part.prt", "Drawings/sub/assy.asm"]
    finally:
        import shutil

        shutil.rmtree(parent, ignore_errors=True)


def test_extract_neutralizes_dotdot_zip_slip(tmp_path: Path):
    """``..`` segments are stripped so entries cannot escape the extract root."""
    zip_path = tmp_path / "evil.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("../outside.prt")
        zf.writestr(info, b"nope")
    zip_path.write_bytes(buf.getvalue())
    dest = tmp_path / "out"
    dest.mkdir()
    outside = tmp_path / "outside.prt"
    extract_zip_safely(zip_path, dest)
    assert not outside.exists()
    assert (dest / "outside.prt").is_file()
    assert (dest / "outside.prt").read_bytes() == b"nope"


def test_normalize_zip_parent_folder_rejects_traversal_and_reserved():
    assert normalize_zip_parent_folder("") == ""
    assert normalize_zip_parent_folder("Drawings/RevA") == "Drawings/RevA"
    with pytest.raises(PathValidationError, match="traversal|relative"):
        normalize_zip_parent_folder("../outside")
    with pytest.raises(PathValidationError, match="traversal|relative"):
        normalize_zip_parent_folder("CAD/../../etc")
    with pytest.raises(PathValidationError, match="reserved"):
        normalize_zip_parent_folder(".git/hooks")
    with pytest.raises(PathValidationError, match="reserved"):
        normalize_zip_parent_folder("lib/.creopdm")


def test_plan_zip_import_rejects_unsafe_parent_folder(tmp_path: Path):
    extract = tmp_path / "extracted"
    extract.mkdir()
    (extract / "pin.prt").write_bytes(b"pin")
    with pytest.raises(PathValidationError, match="traversal|relative"):
        plan_zip_import_jobs(extract, parent_folder="../../outside")
    with pytest.raises(PathValidationError, match="reserved"):
        plan_zip_import_jobs(extract, parent_folder=".git")


def test_extract_rejects_corrupt_zip(tmp_path: Path):
    zip_path = tmp_path / "bad.zip"
    zip_path.write_bytes(b"not-a-zip")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ValidationAppError, match="not a valid zip"):
        extract_zip_safely(zip_path, dest)


def test_max_zip_import_bytes_is_two_gb():
    assert MAX_ZIP_IMPORT_BYTES == 2 * 1024 * 1024 * 1024
