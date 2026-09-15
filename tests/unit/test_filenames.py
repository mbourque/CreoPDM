from creopdm.constants import APP_NAME, APP_VERSION
from creopdm.creo.file_manager import CreoFileManager


def test_normalize_creo_numbered_files():
    assert CreoFileManager.normalize_creo_filename("shaft.prt.1") == "shaft.prt"
    assert CreoFileManager.normalize_creo_filename("shaft.prt.25") == "shaft.prt"
    assert CreoFileManager.normalize_creo_filename("motor.asm.7") == "motor.asm"
    assert CreoFileManager.normalize_creo_filename("layout.drw.3") == "layout.drw"
    assert CreoFileManager.normalize_creo_filename("tool.mfg.12") == "tool.mfg"


def test_normalize_preserves_non_creo_numeric_suffixes():
    assert CreoFileManager.normalize_creo_filename("notes.txt.1") == "notes.txt.1"
    assert CreoFileManager.normalize_creo_filename("report.2024") == "report.2024"
    assert CreoFileManager.normalize_creo_filename("archive.tar.gz") == "archive.tar.gz"
    assert CreoFileManager.normalize_creo_filename("drawing.pdf.2") == "drawing.pdf.2"


def test_normalize_leaves_unversioned_creo_files():
    assert CreoFileManager.normalize_creo_filename("shaft.prt") == "shaft.prt"
    assert CreoFileManager.normalize_creo_filename("SHAFT.PRT.1") == "SHAFT.PRT"


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
