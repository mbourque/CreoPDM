from creopdm.constants import APP_NAME, APP_VERSION
from creopdm.creo.file_manager import CreoFileManager
from creopdm.utils.native_dialog import cad_dialog_filter_patterns


def test_normalize_creo_numbered_files():
    assert CreoFileManager.normalize_creo_filename("shaft.prt.1") == "shaft.prt"
    assert CreoFileManager.normalize_creo_filename("shaft.prt.25") == "shaft.prt"
    assert CreoFileManager.normalize_creo_filename("motor.asm.7") == "motor.asm"
    assert CreoFileManager.normalize_creo_filename("layout.drw.3") == "layout.drw"
    assert CreoFileManager.normalize_creo_filename("tool.mfg.12") == "tool.mfg"
    assert CreoFileManager.normalize_creo_filename("setup.inf.1") == "setup.inf"
    assert CreoFileManager.normalize_creo_filename("outline.dxf.4") == "outline.dxf"
    assert CreoFileManager.normalize_creo_filename("params.m_p.1") == "params.m_p"
    assert CreoFileManager.normalize_creo_filename("format.frm.2") == "format.frm"
    assert CreoFileManager.normalize_creo_filename("sheet.tbl.8") == "sheet.tbl"
    assert CreoFileManager.normalize_creo_filename("cnc-part.mrd.4") == "cnc-part.mrd"
    assert CreoFileManager.normalize_creo_filename("150-inch.xpr.1") == "150-inch.xpr"
    assert CreoFileManager.normalize_creo_filename("op10.bin.2") == "op10.bin"
    assert CreoFileManager.normalize_creo_filename("blank.stk.3") == "blank.stk"


def test_normalize_preserves_non_creo_numeric_suffixes():
    assert CreoFileManager.normalize_creo_filename("notes.txt.1") == "notes.txt.1"
    assert CreoFileManager.normalize_creo_filename("report.2024") == "report.2024"
    assert CreoFileManager.normalize_creo_filename("archive.tar.gz") == "archive.tar.gz"
    assert CreoFileManager.normalize_creo_filename("drawing.pdf.2") == "drawing.pdf.2"


def test_normalize_leaves_unversioned_creo_files():
    assert CreoFileManager.normalize_creo_filename("shaft.prt") == "shaft.prt"
    assert CreoFileManager.normalize_creo_filename("SHAFT.PRT.1") == "SHAFT.PRT"


def test_workspace_transients_are_ignored():
    assert CreoFileManager.is_workspace_transient("trail.txt")
    assert CreoFileManager.is_workspace_transient("trail.txt.5")
    assert CreoFileManager.is_workspace_transient("std.out")
    assert CreoFileManager.is_workspace_transient("747912f5-13ee-41f0-90d7-537c290.idx")
    assert not CreoFileManager.is_workspace_transient("tool.idx")
    assert not CreoFileManager.is_workspace_transient("parallels.prt.4")


def test_app_identity():
    assert APP_NAME == "CreoPDM"
    assert APP_VERSION == "0.1.0"


def test_canonical_name_keeps_creo_save_numbers():
    assert CreoFileManager.canonical_repository_name("shaft.prt.3") == "shaft.prt.3"
    assert CreoFileManager.canonical_repository_name("motor.asm.7") == "motor.asm.7"
    assert CreoFileManager.canonical_repository_name("shaft.prt") == "shaft.prt"


def test_latest_creo_version_in_directory(tmp_path):
    folder = tmp_path / "CAD"
    folder.mkdir()
    (folder / "shaft.prt.12").write_bytes(b"12")
    (folder / "shaft.prt.14").write_bytes(b"14")
    (folder / "shaft.prt.13").write_bytes(b"13")
    latest = CreoFileManager.latest_in_directory(folder, "shaft.prt")
    assert latest is not None
    assert latest.name == "shaft.prt.14"
    numbered = CreoFileManager.latest_in_directory(folder, "shaft.prt.3")
    assert numbered is not None
    assert numbered.name == "shaft.prt.14"


def test_select_latest_prefers_numbered_over_unnumbered(tmp_path):
    older = tmp_path / "parallels.prt"
    older.write_bytes(b"old")
    v1 = tmp_path / "parallels.prt.1"
    v1.write_bytes(b"1")
    v3 = tmp_path / "parallels.prt.3"
    v3.write_bytes(b"3")
    chosen = CreoFileManager.select_latest_creo_version([older, v1, v3])
    assert chosen is not None
    assert chosen.name == "parallels.prt.3"


def test_filter_to_latest_saves_skips_older_and_unnumbered(tmp_path):
    older = tmp_path / "parallels.prt"
    older.write_bytes(b"old")
    v1 = tmp_path / "parallels.prt.1"
    v1.write_bytes(b"1")
    v3 = tmp_path / "parallels.prt.3"
    v3.write_bytes(b"3")
    notes = tmp_path / "notes.pdf"
    notes.write_bytes(b"%PDF")
    inf = tmp_path / "setup.inf"
    inf.write_bytes(b"old-inf")
    inf2 = tmp_path / "setup.inf.2"
    inf2.write_bytes(b"new-inf")
    chosen = CreoFileManager.filter_to_latest_saves([older, v1, v3, notes, inf, inf2])
    names = {path.name for path in chosen}
    assert names == {"parallels.prt.3", "notes.pdf", "setup.inf.2"}
    assert older.is_file() and v1.is_file() and inf.is_file()


def test_list_latest_in_folder_skips_older_transients_and_git(tmp_path):
    root = tmp_path / "models"
    nested = root / "sub"
    nested.mkdir(parents=True)
    (root / "parallels.prt").write_bytes(b"old")
    (root / "parallels.prt.1").write_bytes(b"1")
    (root / "parallels.prt.3").write_bytes(b"3")
    (nested / "bushing.prt.2").write_bytes(b"bush")
    (root / "trail.txt").write_bytes(b"junk")
    (root / "notes.bak").write_bytes(b"bak")
    git = root / ".git"
    git.mkdir()
    (git / "config").write_bytes(b"git")
    chosen = {path.name for path in CreoFileManager.list_latest_in_folder(root)}
    assert chosen == {"parallels.prt.3", "bushing.prt.2"}


def test_filter_to_latest_saves_uses_disk_siblings_when_only_old_selected(tmp_path):
    older = tmp_path / "shaft.prt"
    older.write_bytes(b"old")
    latest = tmp_path / "shaft.prt.4"
    latest.write_bytes(b"4")
    (tmp_path / "shaft.prt.2").write_bytes(b"2")
    chosen = CreoFileManager.filter_to_latest_saves([older])
    assert [path.name for path in chosen] == ["shaft.prt.4"]


def test_latest_numbered_extra_cad_in_directory(tmp_path):
    folder = tmp_path / "CAD"
    folder.mkdir()
    (folder / "setup.inf.1").write_bytes(b"1")
    (folder / "setup.inf.3").write_bytes(b"3")
    (folder / "setup.inf.2").write_bytes(b"2")
    latest = CreoFileManager.latest_in_directory(folder, "setup.inf")
    assert latest is not None
    assert latest.name == "setup.inf.3"


def test_cad_dialog_filter_includes_numbered_defaults():
    patterns = cad_dialog_filter_patterns()
    assert "*.prt;*.prt.*" in patterns
    assert "*.inf;*.inf.*" in patterns
    assert "*.m_p;*.m_p.*" in patterns
    assert "*.frm;*.frm.*" in patterns
    assert "*.sym;*.sym.*" in patterns
    assert "*.bin;*.bin.*" in patterns
    assert "*.mrd;*.mrd.*" in patterns
    assert "*.xpr;*.xpr.*" in patterns
