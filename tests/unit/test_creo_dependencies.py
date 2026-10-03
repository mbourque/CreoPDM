from pathlib import Path

from creopdm.utils.creo_dependencies import (
    collect_open_dependency_objects,
    names_referenced_in_model,
    needs_open_dependencies,
    select_dependency_objects,
)


class _Obj:
    def __init__(
        self,
        relative_path: str,
        filename: str,
        *,
        object_type: str = "CREO_PART",
        obj_id: int | None = None,
    ):
        self.relative_path = relative_path
        self.filename = filename
        self.object_type = object_type
        self.id = obj_id if obj_id is not None else hash(relative_path) % 10_000_000


def test_needs_dependencies_for_asm_and_drw_only():
    assert needs_open_dependencies("CREO_ASSEMBLY", "top.asm") is True
    assert needs_open_dependencies("CREO_DRAWING", "top.drw") is True
    assert needs_open_dependencies("CREO_PART", "pin.prt") is False


def test_names_referenced_in_model(tmp_path: Path):
    asm = tmp_path / "top.asm.1"
    asm.write_bytes(b".... PIN.PRT .... bracket ....")
    found = names_referenced_in_model(asm, ["pin.prt", "bracket.prt", "other.prt"])
    assert "pin.prt" in {item.lower() for item in found}
    assert "bracket.prt" in {item.lower() for item in found}
    assert "other.prt" not in {item.lower() for item in found}


def test_model_references_filename_matches_stem_and_logical(tmp_path: Path):
    from creopdm.utils.creo_dependencies import model_references_filename

    asm = tmp_path / "top.asm.1"
    asm.write_bytes(b"header ... CLASP-CLASP_MIR.PRT ... footer")
    assert model_references_filename(asm, "clasp-clasp_mir.prt.3") is True
    assert model_references_filename(asm, "missing.prt.1") is False


def test_select_dependency_objects_prefers_referenced(tmp_path: Path):
    asm = tmp_path / "top.asm.1"
    asm.write_bytes(b"assembly uses PIN.PRT only")
    siblings = [
        _Obj("CAD/top.asm", "top.asm"),
        _Obj("CAD/pin.prt", "pin.prt"),
        _Obj("CAD/unused.prt", "unused.prt"),
    ]
    chosen = select_dependency_objects(
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
    # Product scope still finds a part in another folder when the asm bytes name it.
    cross = select_dependency_objects(
        primary_relative="CAD/top.asm",
        primary_filename="top.asm",
        object_type="CREO_ASSEMBLY",
        siblings=siblings
        + [_Obj("Other/pin.prt", "pin.prt"), _Obj("Other/spare.prt", "spare.prt")],
        model_path=asm,
        model_extensions=[".prt", ".asm", ".drw"],
        all_cad_extensions=[],
        scope="product",
    )
    assert {obj.filename for obj in cross} == {"pin.prt"}


def test_select_dependency_objects_skips_huge_unreferenced_pool(tmp_path: Path):
    asm = tmp_path / "top.asm.1"
    asm.write_bytes(b"no matching names here")
    siblings = [_Obj("CAD/top.asm", "top.asm", object_type="CREO_ASSEMBLY")] + [
        _Obj(f"CAD/part{i}.prt", f"part{i}.prt") for i in range(80)
    ]
    chosen = select_dependency_objects(
        primary_relative="CAD/top.asm",
        primary_filename="top.asm",
        object_type="CREO_ASSEMBLY",
        siblings=siblings,
        model_path=asm,
        model_extensions=[".prt", ".asm", ".drw"],
        all_cad_extensions=[],
    )
    assert chosen == []


def test_collect_open_dependencies_walks_subassembly_tree(tmp_path: Path):
    """Top asm → sub asm → part via vault bytes only (no Where Used index)."""
    top = tmp_path / "top.asm.1"
    sub = tmp_path / "sub.asm.1"
    top.write_bytes(b"uses SUB.ASM")
    sub.write_bytes(b"uses PIN.PRT")
    paths = {
        "CAD/top.asm": top,
        "CAD/sub.asm": sub,
        "Parts/pin.prt": tmp_path / "pin.prt.1",
    }
    paths["Parts/pin.prt"].write_bytes(b"part")
    siblings = [
        _Obj("CAD/top.asm", "top.asm", object_type="CREO_ASSEMBLY", obj_id=1),
        _Obj("CAD/sub.asm", "sub.asm", object_type="CREO_ASSEMBLY", obj_id=2),
        _Obj("Parts/pin.prt", "pin.prt", object_type="CREO_PART", obj_id=3),
        _Obj("Parts/other.prt", "other.prt", object_type="CREO_PART", obj_id=4),
    ]

    def resolve(obj):
        return paths.get(obj.relative_path)

    from creopdm.constants import DependencyType
    from creopdm.utils.creo_dependencies import collect_open_dependency_walk

    chosen = collect_open_dependency_objects(
        primary_relative="CAD/top.asm",
        primary_filename="top.asm",
        object_type="CREO_ASSEMBLY",
        siblings=siblings,
        model_path=top,
        model_extensions=[".prt", ".asm", ".drw"],
        all_cad_extensions=[],
        resolve_path=resolve,
        skip_object_id=1,
    )
    names = {obj.filename for obj in chosen}
    assert names == {"sub.asm", "pin.prt"}

    _objs, edges = collect_open_dependency_walk(
        primary_relative="CAD/top.asm",
        primary_filename="top.asm",
        object_type="CREO_ASSEMBLY",
        siblings=siblings,
        model_path=top,
        model_extensions=[".prt", ".asm", ".drw"],
        all_cad_extensions=[],
        resolve_path=resolve,
        skip_object_id=1,
    )
    edge_set = set(edges)
    member = DependencyType.ASSEMBLY_MEMBER.value
    assert (1, 2, member) in edge_set  # top → sub
    assert (2, 3, member) in edge_set  # sub → pin
