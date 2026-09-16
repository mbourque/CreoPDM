from pathlib import Path

from creopdm.utils.creo_header import (
    HEADER_LIMIT,
    creo_release_for,
    is_creo_native_model,
    parse_creo_release,
    read_ugc_header,
)

SAMPLE_HEADER = (
    "#UGC:2 ASSEMBLY 2784 2280 800 1 1 15 4400 2026163 000002d0 \\\n"
    "#- VERS 0 0                                                          \\\n"
    "#- HOST                                                              \\\n"
    "#- LINK                                                              \\\n"
    "#- DBID                                                              \\\n"
    "#- REVS 0,                                                           \\\n"
    "#- RELL 0,                                                           \\\n"
    "#- UOBJ_ID 1789580212 1245254992 376817700                           \\\n"
    "#- MACH _Windows                                                     \\\n"
    "#- CMNM 00ebridgeport.asm                                            \\\n"
    "#-END_OF_UGC_HEADER\n"
    "#Creo  TM  13  (c) 2026 by PTC Inc.  All Rights Reserved. 13.4.1.0\n"
    "#UGC_TOC 2 32 81 17#############################################################"
)


def _write_model(path: Path, extra: bytes = b"\x00binary-body") -> Path:
    path.write_bytes(SAMPLE_HEADER.encode("ascii") + extra)
    return path


def test_is_creo_native_model_only_prt_asm_drw():
    assert is_creo_native_model("bridgeport.asm")
    assert is_creo_native_model("shaft.prt.6")
    assert is_creo_native_model("sheet.1.drw")
    assert not is_creo_native_model("format.frm")
    assert not is_creo_native_model("op10.mfg.1")
    assert not is_creo_native_model("spec.pdf")
    assert not is_creo_native_model("outline.dxf")


WILDFIRE_HEADER = (
    "#UGC:2 ASSEMBLY 1474 880 800 1 1 15 3100 2010100 00000288 \\\n"
    "#- VERS 0 0                                                          \\\n"
    "#- HOST                                                              \\\n"
    "#- LINK                                                              \\\n"
    "#- DBID                                                              \\\n"
    "#- REVS 0,                                                           \\\n"
    "#- RELL 0,                                                           \\\n"
    "#- UOBJ_ID 1278438930 1193755978 -994361573                          \\\n"
    "#- MACH _Windows NT_5.1_2600                                         \\\n"
    "#-END_OF_UGC_HEADER\n"
    "#Pro/ENGINEER  TM  Wildfire 5.0  (c) 2010 by Parametric Technology Corporation  All Rights Reserved. M040\n"
    "#UGC_TOC 2 32 81 17#############################################################"
)


def test_parse_creo_release_from_ugc_header():
    assert parse_creo_release(SAMPLE_HEADER) == "13.4.1.0"
    assert parse_creo_release("#Creo  TM  11  (c) 2024 by PTC Inc.") == "11"
    assert parse_creo_release(WILDFIRE_HEADER) == "Wildfire 5.0"
    assert parse_creo_release(
        "#Pro/ENGINEER  TM  Wildfire 5.0  (c) 2010 by Parametric Technology Corporation  All Rights Reserved. M040"
    ) == "Wildfire 5.0"
    assert parse_creo_release("#Pro/ENGINEER  TM  2001  (c) 2001 by PTC") == "2001"
    assert parse_creo_release("#UGC:2 PART 1\nnot a creo file") is None


def test_creo_release_for_wildfire_header(tmp_path: Path):
    path = tmp_path / "legacy.asm.1"
    path.write_bytes(WILDFIRE_HEADER.encode("ascii") + b"\x00binary")
    assert creo_release_for(path) == "Wildfire 5.0"


def test_creo_release_for_native_models(tmp_path: Path):
    part = _write_model(tmp_path / "shaft.prt.3")
    asm = _write_model(tmp_path / "mill.asm")
    drw = _write_model(tmp_path / "sheet.drw.1")
    assert creo_release_for(part) == "13.4.1.0"
    assert creo_release_for(asm) == "13.4.1.0"
    assert creo_release_for(drw) == "13.4.1.0"


def test_creo_release_skips_other_extensions_even_with_header(tmp_path: Path):
    frm = _write_model(tmp_path / "format.frm")
    pdf = tmp_path / "spec.pdf"
    pdf.write_bytes(SAMPLE_HEADER.encode("ascii"))
    assert creo_release_for(frm) is None
    assert creo_release_for(pdf) is None
    assert creo_release_for(frm, "shaft.prt") == "13.4.1.0"


def test_creo_release_missing_header_is_none(tmp_path: Path):
    path = tmp_path / "blank.prt"
    path.write_bytes(b"FAKE CREO PART")
    assert creo_release_for(path) is None


def test_read_ugc_header_stops_at_toc_hash_run(tmp_path: Path):
    path = tmp_path / "mill.asm"
    decoy = b"\n#Creo  TM  9  (c) 2019 by PTC Inc.  All Rights Reserved. 9.0.0.0\n"
    _write_model(path, extra=decoy + (b"\xff" * 4096))
    header = read_ugc_header(path)
    assert "13.4.1.0" in header
    assert "9.0.0.0" not in header
    assert header.endswith("#")
    assert creo_release_for(path) == "13.4.1.0"


def test_read_ugc_header_does_not_scan_past_limit(tmp_path: Path):
    path = tmp_path / "late.prt"
    late = (
        b"x" * (HEADER_LIMIT + 8)
        + b"#Creo  TM  8  (c) 2018 by PTC Inc.  All Rights Reserved. 8.0.0.0\n"
        + b"#UGC_TOC 2 0 0 0#############################################################"
    )
    path.write_bytes(late)
    assert creo_release_for(path) is None
    assert "8.0.0.0" not in read_ugc_header(path)
