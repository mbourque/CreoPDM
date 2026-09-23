from pathlib import Path

from creopdm.utils.creo_companions import (
    names_referenced_in_model,
    needs_open_companions,
    select_companion_objects,
)


class _Obj:
    def __init__(self, relative_path: str, filename: str):
        self.relative_path = relative_path
        self.filename = filename


def test_needs_companions_for_asm_and_drw_only():
    assert needs_open_companions("CREO_ASSEMBLY", "top.asm") is True
    assert needs_open_companions("CREO_DRAWING", "top.drw") is True
    assert needs_open_companions("CREO_PART", "pin.prt") is False


def test_names_referenced_in_model(tmp_path: Path):
    asm = tmp_path / "top.asm.1"
    asm.write_bytes(b".... PIN.PRT .... bracket ....")
    found = names_referenced_in_model(asm, ["pin.prt", "bracket.prt", "other.prt"])
    assert "pin.prt" in {item.lower() for item in found}
    assert "bracket.prt" in {item.lower() for item in found}
    assert "other.prt" not in {item.lower() for item in found}


def test_model_references_filename_matches_stem_and_logical(tmp_path: Path):
    from creopdm.utils.creo_companions import model_references_filename

    asm = tmp_path / "top.asm.1"
    asm.write_bytes(b"header ... CLASP-CLASP_MIR.PRT ... footer")
    assert model_references_filename(asm, "clasp-clasp_mir.prt.3") is True
    assert model_references_filename(asm, "missing.prt.1") is False


def test_select_companion_objects_prefers_referenced(tmp_path: Path):
    asm = tmp_path / "top.asm.1"
    asm.write_bytes(b"assembly uses PIN.PRT only")
    siblings = [
        _Obj("CAD/top.asm", "top.asm"),
        _Obj("CAD/pin.prt", "pin.prt"),
        _Obj("CAD/unused.prt", "unused.prt"),
    ]
    chosen = select_companion_objects(
        primary_relative="CAD/top.asm",
        primary_filename="top.asm",
        object_type="CREO_ASSEMBLY",
        siblings=siblings,
        model_path=asm,
        model_extensions=[".prt", ".asm", ".drw"],
        all_cad_extensions=[],
    )
    names = {obj.filename for obj in chosen}
    assert names == {"pin.prt"}


def test_select_companion_objects_skips_huge_unreferenced_pool(tmp_path: Path):
    asm = tmp_path / "top.asm.1"
    asm.write_bytes(b"no matching names here")
    siblings = [_Obj("CAD/top.asm", "top.asm")] + [
        _Obj(f"CAD/part{i}.prt", f"part{i}.prt") for i in range(80)
    ]
    chosen = select_companion_objects(
        primary_relative="CAD/top.asm",
        primary_filename="top.asm",
        object_type="CREO_ASSEMBLY",
        siblings=siblings,
        model_path=asm,
        model_extensions=[".prt", ".asm", ".drw"],
        all_cad_extensions=[],
    )
    assert chosen == []
