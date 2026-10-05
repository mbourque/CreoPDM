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


def test_open_dependency_walk_prefers_folder_scope_before_product():
    """Regression: product-first scans hung Finding dependencies on large vaults."""
    text = Path("src/creopdm/utils/creo_dependencies.py").read_text(encoding="utf-8")
    walk = text.split("while queue and len(out) < _MAX_OPEN_DEPENDENCIES_TOTAL:", 1)[1]
    walk = walk.split("return out, edges", 1)[0]
    assert 'scope="folder"' in walk
    assert 'scope="product"' in walk
    assert walk.index('scope="folder"') < walk.index('scope="product"')
    assert "_MAX_OPEN_DEPENDENCY_MATCHES" in text
    assert "include_stems=not strict" in text
    # 2500 open deps exhausted QueuePool and took the site down.
    assert "_MAX_OPEN_DEPENDENCIES_TOTAL = 150" in text
    assert "_WHERE_USED_SCAN_LIMIT" in text


def test_rebuild_reads_full_tip_for_where_used():
    text = Path("src/creopdm/services/metadata_service.py").read_text(encoding="utf-8")
    assert "max_bytes=_WHERE_USED_SCAN_LIMIT" in text
    assert "prune_assembly_name_magnets" in text


def test_where_used_magnet_parent_cap_constant():
    from creopdm.utils.creo_dependencies import _MAX_WHERE_USED_ASM_PARENTS

    assert _MAX_WHERE_USED_ASM_PARENTS == 40


def test_open_deps_do_not_materialize_during_find():
    """Finding dependencies must locate only — materialize is the agent's job."""
    text = Path("src/creopdm/services/creo_service.py").read_text(encoding="utf-8")
    body = text.split("def _dependencies_for(", 1)[1].split("def _open_resolved(", 1)[0]
    assert "locate_content" in body
    assert "materialize(" not in body
    assert "_MAX_OPEN_FROM_WHERE_USED" in body
    open_obj = text.split("def open_object(", 1)[1].split("def open_workspace_file(", 1)[0]
    assert "is_modified" not in open_obj


def test_select_dependency_objects_caps_large_flat_folder_matches(tmp_path: Path):
    """Flat folder with thousands of name.ext hits must not return the whole vault."""
    asm = tmp_path / "top.asm.1"
    # Many bounded name.ext tokens — like Creo string tables in a flat vault.
    blob = b"\x00".join(f"part{i}.prt".encode() for i in range(300))
    asm.write_bytes(blob)
    siblings = [_Obj("top.asm", "top.asm", object_type="CREO_ASSEMBLY")] + [
        _Obj(f"part{i}.prt", f"part{i}.prt") for i in range(300)
    ]
    chosen = select_dependency_objects(
        primary_relative="top.asm",
        primary_filename="top.asm",
        object_type="CREO_ASSEMBLY",
        siblings=siblings,
        model_path=asm,
        model_extensions=[".prt", ".asm", ".drw"],
        all_cad_extensions=[],
    )
    assert 0 < len(chosen) <= 200


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
