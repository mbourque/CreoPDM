from creopdm.constants import APP_NAME, APP_VERSION
from creopdm.creo.file_manager import CreoFileManager, common_import_root
from creopdm.utils.native_dialog import (
    add_files_dialog_filter_pairs,
    cad_dialog_filter_patterns,
    creo_model_dialog_filter_patterns,
    document_dialog_filter_patterns,
)


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
    assert CreoFileManager.normalize_creo_filename("cutter.tmu.3") == "cutter.tmu"
    assert CreoFileManager.normalize_creo_filename("preview.pvz.4") == "preview.pvz"
    assert CreoFileManager.normalize_creo_filename("preview.4.pvz") == "preview.pvz"
    assert CreoFileManager.normalize_creo_filename("shaft.1.prt") == "shaft.prt"
    assert CreoFileManager.normalize_creo_filename("outline.4.dxf") == "outline.dxf"
    assert CreoFileManager.normalize_creo_filename("cutter.3.tmu") == "cutter.3.tmu"
    assert CreoFileManager.normalize_creo_filename("setup.1.inf") == "setup.1.inf"
    assert CreoFileManager.save_number("shaft.prt") == 0
    assert CreoFileManager.save_number("shaft.prt.4") == 4
    assert CreoFileManager.save_number("shaft.1.prt") == 1
    assert CreoFileManager.save_number("preview.2.pvz") == 2
    assert CreoFileManager.save_number("preview.pvz.3") == 3
    assert CreoFileManager.save_number("setup.inf.12") == 12
    assert CreoFileManager.save_number("setup.1.inf") == 0
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
    assert CreoFileManager.is_workspace_transient("std.err")
    assert CreoFileManager.is_workspace_transient("scratch.tst")
    assert CreoFileManager.is_workspace_transient("scratch.err")
    assert CreoFileManager.is_workspace_transient("lock.acl")
    assert CreoFileManager.is_workspace_transient("proimpex.errors")
    assert CreoFileManager.is_workspace_transient("regen_backup_model.mrd.1")
    assert CreoFileManager.is_workspace_transient("regen_backup_model-asm.mrd.12")
    assert CreoFileManager.is_workspace_transient("traceback.log")
    assert CreoFileManager.is_workspace_transient("mapkeys.pro")
    assert CreoFileManager.is_workspace_transient("config.pro")
    assert CreoFileManager.is_workspace_transient("config.sup")
    assert CreoFileManager.is_workspace_transient("creo_parametric_customization.ui")
    assert not CreoFileManager.is_workspace_transient("cnc-part.mrd.4")
    assert CreoFileManager.is_workspace_transient("747912f5-13ee-41f0-90d7-537c290.idx")
    assert not CreoFileManager.is_workspace_transient("tool.idx")
    assert not CreoFileManager.is_workspace_transient("parallels.prt.4")
    assert not CreoFileManager.is_workspace_transient("report.out")


def test_app_identity():
    assert APP_NAME == "CreoPDM"
    assert APP_VERSION == "0.2.0"


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


def test_latest_openable_dotted_save_in_directory(tmp_path):
    folder = tmp_path / "CAD"
    folder.mkdir()
    (folder / "preview.pvz").write_bytes(b"old")
    (folder / "preview.1.pvz").write_bytes(b"1")
    (folder / "preview.3.pvz").write_bytes(b"3")
    (folder / "preview.2.pvz").write_bytes(b"2")
    latest = CreoFileManager.latest_in_directory(folder, "preview.pvz")
    assert latest is not None
    assert latest.name == "preview.3.pvz"
    from_numbered = CreoFileManager.latest_in_directory(folder, "preview.1.pvz")
    assert from_numbered is not None
    assert from_numbered.name == "preview.3.pvz"


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
    (root / "proimpex.errors").write_bytes(b"err")
    (root / "scratch.tst").write_bytes(b"tst")
    (root / "regen_backup_model.mrd.2").write_bytes(b"bak")
    (root / "notes.bak").write_bytes(b"bak")
    (root / "op10.lst").write_bytes(b"post")
    (root / "cut.mbx").write_bytes(b"mbx")
    git = root / ".git"
    git.mkdir()
    (git / "config").write_bytes(b"git")
    chosen = {path.name for path in CreoFileManager.list_latest_in_folder(root)}
    assert chosen == {"parallels.prt.3", "bushing.prt.2", "op10.lst", "cut.mbx"}


def test_common_import_root_keeps_sibling_subfolders(tmp_path):
    kit = tmp_path / "Kit"
    lib = kit / "lib"
    asm = kit / "asm"
    lib.mkdir(parents=True)
    asm.mkdir(parents=True)
    pin = lib / "pin.prt"
    top = asm / "top.asm"
    pin.write_bytes(b"p")
    top.write_bytes(b"a")
    root = common_import_root([pin, top])
    assert root is not None
    assert root.resolve() == kit.resolve()
    assert (root / "lib" / "pin.prt").is_file()


def test_common_import_root_none_for_single_or_same_parent(tmp_path):
    """Single-file / same-folder adds stay flat — do not wrap in the parent dir name."""
    kit = tmp_path / "Kit"
    kit.mkdir()
    a = kit / "a.prt"
    b = kit / "b.prt"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    assert common_import_root([a]) is None
    assert common_import_root([a, b]) is None


def test_filter_to_latest_saves_uses_disk_siblings_when_only_old_selected(tmp_path):
    older = tmp_path / "shaft.prt"
    older.write_bytes(b"old")
    latest = tmp_path / "shaft.prt.4"
    latest.write_bytes(b"4")
    (tmp_path / "shaft.prt.2").write_bytes(b"2")
    chosen = CreoFileManager.filter_to_latest_saves([older])
    assert [path.name for path in chosen] == ["shaft.prt.4"]


def test_filter_to_latest_uses_purgeable_extensions_only(tmp_path):
    """Regression: older .ext.N omission follows Settings → Purgeable, not all CAD."""
    from creopdm.constants import DEFAULT_PURGEABLE_EXTENSIONS

    prt1 = tmp_path / "shaft.prt.1"
    prt3 = tmp_path / "shaft.prt.3"
    txt1 = tmp_path / "notes.txt.1"
    txt2 = tmp_path / "notes.txt.2"
    snag1 = tmp_path / "clip.snagx.1"
    snag2 = tmp_path / "clip.snagx.2"
    for path, payload in (
        (prt1, b"1"),
        (prt3, b"3"),
        (txt1, b"a"),
        (txt2, b"b"),
        (snag1, b"s1"),
        (snag2, b"s2"),
    ):
        path.write_bytes(payload)

    with_defaults = CreoFileManager.filter_to_latest_saves(
        [prt1, prt3, txt1, txt2, snag1, snag2],
        DEFAULT_PURGEABLE_EXTENSIONS,
        scan_disk_siblings=False,
    )
    assert {path.name for path in with_defaults} == {
        "shaft.prt.3",
        "notes.txt.2",
        "clip.snagx.1",
        "clip.snagx.2",
    }

    # Explicit list without .prt must not still collapse Creo cores via CREO_FILE_EXTENSIONS.
    txt_only = CreoFileManager.filter_to_latest_saves(
        [prt1, prt3, txt1, txt2],
        [".txt"],
        scan_disk_siblings=False,
    )
    assert {path.name for path in txt_only} == {
        "shaft.prt.1",
        "shaft.prt.3",
        "notes.txt.2",
    }


def test_filenames_older_than_floor_keeps_vault_and_newer():
    names = [
        "shaft.prt.10",
        "shaft.prt.2",
        "shaft.prt",
        "shaft.prt.1",
        "shaft.prt.3",
        "shaft.prt.5",
        "other.prt.1",
    ]
    obsolete = CreoFileManager.filenames_older_than_floor(
        names, min_keep=3, logical_name="shaft.prt"
    )
    assert obsolete == ["shaft.prt", "shaft.prt.1", "shaft.prt.2"]


def test_filenames_older_than_floor_skips_when_vault_unnumbered():
    names = ["shaft.prt", "shaft.prt.1", "shaft.prt.2"]
    assert CreoFileManager.filenames_older_than_floor(names, min_keep=0) == []
    assert CreoFileManager.filenames_older_than_floor(names, min_keep=-1) == []


def test_paths_older_than_vault_floors_respects_floor_and_ignores_untracked(tmp_path):
    root = tmp_path / "cache"
    nested = root / "sub"
    nested.mkdir(parents=True)
    (root / "shaft.prt").write_bytes(b"0")
    (root / "shaft.prt.1").write_bytes(b"1")
    (root / "shaft.prt.10").write_bytes(b"10")
    (root / "shaft.prt.2").write_bytes(b"2")
    (root / "shaft.prt.3").write_bytes(b"3")
    (root / "shaft.prt.4").write_bytes(b"4")
    (root / "orphan.prt.1").write_bytes(b"orphan")
    (nested / "pin.prt.1").write_bytes(b"1")
    (nested / "pin.prt.2").write_bytes(b"2")
    (nested / "notes.txt").write_bytes(b"txt")
    obsolete = CreoFileManager.paths_older_than_vault_floors(
        root,
        [
            ("shaft.prt", 3),
            ("sub/pin.prt", 2),
            ("missing.prt", 5),
            ("notes.txt", 1),
        ],
    )
    relative = [path.relative_to(root).as_posix() for path in obsolete]
    assert relative == ["shaft.prt", "shaft.prt.1", "shaft.prt.2", "sub/pin.prt.1"]


def test_paths_older_than_vault_floors_flat_cache_for_nested_vault_path(tmp_path):
    """Regression: vault Documents/shaft.prt.3, agent cache has flat shaft.prt.1/.2/.3."""
    root = tmp_path / "cache"
    root.mkdir()
    (root / "shaft.prt.1").write_bytes(b"1")
    (root / "shaft.prt.2").write_bytes(b"2")
    (root / "shaft.prt.3").write_bytes(b"3")
    (root / "shaft.prt.4").write_bytes(b"4")
    (root / "other.prt.1").write_bytes(b"other")
    obsolete = CreoFileManager.paths_older_than_vault_floors(
        root,
        [("Documents/shaft.prt", 3)],
    )
    relative = [path.relative_to(root).as_posix() for path in obsolete]
    assert relative == ["shaft.prt.1", "shaft.prt.2"]
    assert (root / "shaft.prt.3").is_file()
    assert (root / "shaft.prt.4").is_file()
    assert (root / "other.prt.1").is_file()


def test_paths_older_than_vault_floors_skips_flat_fallback_when_basename_ambiguous(tmp_path):
    """Two nested vault objects share a basename — do not purge a flat root sibling."""
    root = tmp_path / "cache"
    root.mkdir()
    (root / "pin.prt.1").write_bytes(b"flat")
    obsolete = CreoFileManager.paths_older_than_vault_floors(
        root,
        [
            ("Incoming/pin.prt", 2),
            ("Library/pin.prt", 5),
        ],
    )
    assert obsolete == []


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
    assert "*.prt;*.prt.*;*.*.prt" in patterns
    assert "*.inf;*.inf.*" in patterns
    assert "*.ncl;*.ncl.*" in patterns
    assert "*.log;*.log.*" in patterns
    assert "*.*.ncl" not in patterns
    assert "*.*.inf" not in patterns
    assert "*.m_p;*.m_p.*" in patterns
    assert "*.frm;*.frm.*;*.*.frm" in patterns
    assert "*.sym;*.sym.*" in patterns
    assert "*.bin;*.bin.*" in patterns
    assert "*.mrd;*.mrd.*" in patterns
    assert "*.xpr;*.xpr.*" in patterns
    assert "*.mtl;*.mtl.*" in patterns
    assert "*.rcp;*.rcp.*" in patterns
    assert "*.mbx;*.mbx.*" in patterns
    assert "*.aux;*.aux.*" in patterns
    assert "*.smt;*.smt.*" in patterns
    assert "*.ptd;*.ptd.*" in patterns
    assert "*.lst;*.lst.*" in patterns
    assert "*.sldprt;*.sldprt.*;*.*.sldprt" in patterns
    assert "*.catpart;*.catpart.*;*.*.catpart" in patterns
    assert "*.tmu;*.tmu.*" in patterns
    assert "*.tmz;*.tmz.*" in patterns
    assert "*.*.tmu" not in patterns
    assert "*.*.tmz" not in patterns
    assert "*.pvz;*.pvz.*;*.*.pvz" in patterns
    assert "*.wrl;*.wrl.*;*.*.wrl" in patterns
    assert "*.idx;*.idx.*" in patterns
    assert "*.*.idx" not in patterns
    assert "*.3mf;*.3mf.*;*.*.3mf" in patterns
    assert "*.x_t;*.x_t.*;*.*.x_t" in patterns


def test_creo_model_dialog_filter_is_numbered_prt_asm_drw():
    assert creo_model_dialog_filter_patterns() == "*.prt.*;*.asm.*;*.drw.*"


def test_add_files_dialog_puts_creo_models_before_all_files():
    pairs = add_files_dialog_filter_pairs()
    assert pairs[0][1] == "*.prt.*;*.asm.*;*.drw.*"
    assert pairs[1][1] == "*.*"
    assert "CAD files" in pairs[2][0]
    assert "Documents" in pairs[3][0]


def test_document_dialog_filter_includes_known_documents():
    patterns = document_dialog_filter_patterns()
    assert "*.pdf" in patterns
    assert "*.docx" in patterns
    assert "*.xlsx" in patterns
    assert "*.odt" in patterns
    assert "*.vsdx" in patterns
    assert "*.msg" in patterns
    assert "*.psd" in patterns
    assert "*.md" not in patterns
    assert "*.png" not in patterns


def test_sync_gitignore_rewrites_managed_block(tmp_path):
    from creopdm.utils.ignore import gitignore_section, sync_gitignore

    path = tmp_path / ".gitignore"
    sync_gitignore(path)
    text = path.read_text(encoding="utf-8")
    assert "trail.txt*" in text
    assert "proimpex.errors" in text
    assert "traceback.log" in text
    assert "config.pro" in text
    path.write_text(text + "custom.keep\n", encoding="utf-8")
    sync_gitignore(path, ["*.tst", "std.out"])
    updated = path.read_text(encoding="utf-8")
    assert "std.out" in updated
    assert "proimpex.errors" not in updated
    assert "custom.keep" in updated
    assert gitignore_section(["*.tst"]).count("*.tst") == 1


def test_sync_gitignore_skips_write_when_unchanged(tmp_path):
    from creopdm.utils.ignore import sync_gitignore

    path = tmp_path / ".gitignore"
    sync_gitignore(path)
    first = path.stat().st_mtime_ns
    sync_gitignore(path)
    assert path.stat().st_mtime_ns == first
