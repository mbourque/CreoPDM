"""BOM/structure name matching, including family-table generics."""

from creopdm.api.pages import _enrich_bom_tree, _enrich_structure_rows
from creopdm.utils.bom_match import (
    bom_generic_label,
    bom_lookup_keys,
    bom_where_used_keys,
    filenames_refer_to_same_model,
    format_bom_qty,
    normalize_bom_compare_filename,
)


def test_bom_lookup_keys_prefer_generic_inside_brackets():
    keys = bom_lookup_keys("INSTALLED<SPLIT-RIVET>.prt")
    assert keys[0] == "split-rivet.prt"
    assert "installed.prt" in keys
    assert "installed<split-rivet>.prt" in keys


def test_bom_lookup_keys_icrps_instance():
    keys = bom_lookup_keys("ICRPS0302<ICRPS03>.prt")
    assert keys[0] == "icrps03.prt"
    assert "icrps0302.prt" in keys


def test_bom_generic_label():
    assert bom_generic_label("INSTALLED<SPLIT-RIVET>.prt") == "SPLIT-RIVET.prt"
    assert bom_generic_label("TOP-BACK.prt") is None


def test_normalize_bom_compare_filename_strips_family_fullname_brackets():
    """Check In session FullName must match tip Structure for AI compare."""
    assert (
        normalize_bom_compare_filename("CONVEYOR_SKEL<<CONVEYOR>>.prt")
        == "CONVEYOR_SKEL.prt"
    )
    assert (
        normalize_bom_compare_filename("CONVEYOR_SKEL<<CONVEYOR>.prt")
        == "CONVEYOR_SKEL.prt"
    )
    assert normalize_bom_compare_filename("CONVEYOR_SKEL.prt") == "CONVEYOR_SKEL.prt"
    # Single-bracket form unchanged here (bom_lookup_keys handles generics).
    assert (
        normalize_bom_compare_filename("INSTALLED<SPLIT-RIVET>.prt")
        == "INSTALLED<SPLIT-RIVET>.prt"
    )


def test_bom_lookup_keys_extensionless_creo_descriptor():
    keys = bom_lookup_keys("CLASP-CLASP_MIR")
    assert "clasp-clasp_mir" in keys
    assert "clasp-clasp_mir.prt" in keys
    assert "clasp.prt" not in keys  # mirror alias only for where-used


def test_bom_lookup_keys_mirror_aliases_source_part():
    keys = bom_where_used_keys("clasp-clasp_mir.prt.1")
    assert "clasp-clasp_mir.prt" in keys
    assert "clasp-clasp_mir" in keys
    assert "clasp.prt" in keys
    assert filenames_refer_to_same_model("clasp-clasp_mir.prt.1", "CLASP.PRT")
    assert filenames_refer_to_same_model("clasp-clasp_mir.prt.1", "CLASP-CLASP_MIR")


def test_format_bom_qty_whole_numbers_not_floats():
    """BOM Qty must show 1 / 3, not 1.0 / 3.0 from float storage."""
    assert format_bom_qty(1.0) == "1"
    assert format_bom_qty(3) == "3"
    assert format_bom_qty("2.0") == "2"
    assert format_bom_qty(None) == "—"


def test_enrich_bom_links_instance_to_generic_uuid():
    by_logical = {"split-rivet.prt": [("uuid-generic", "split-rivet.prt")], "top-back.prt": [("uuid-top", "top-back.prt")]}
    tree = [
        {
            "filename": "TOP-BACK.prt",
            "quantity": 1,
            "children": [],
        },
        {
            "filename": "INSTALLED<SPLIT-RIVET>.prt",
            "quantity": 3,
            "children": [],
        },
    ]
    enriched = _enrich_bom_tree(tree, by_logical)
    assert enriched[0]["object_id"] == "uuid-top"
    assert "open_as" not in enriched[0]
    assert enriched[1]["object_id"] == "uuid-generic"
    assert enriched[1]["open_as"] == "SPLIT-RIVET.prt"


def test_enrich_structure_rows_links_tip_names():
    """Structure Component column must resolve product tips like BOM."""
    by_logical = {"shaft.prt": [("uuid-shaft", "shaft.prt")], "600640041454.prt": [("uuid-harness", "600640041454.prt")]}
    rows = _enrich_structure_rows(
        [
            {"name": "shaft.prt", "type": "PART", "level": 1},
            {"name": "600640041454.prt", "type": "HARNESS", "level": 1},
            {"name": "missing.prt", "type": "PART", "level": 2},
        ],
        by_logical,
    )
    assert rows[0]["object_id"] == "uuid-shaft"
    assert rows[1]["object_id"] == "uuid-harness"
    assert "object_id" not in rows[2]


def test_bom_link_picks_the_same_named_file_nearest_the_assembly():
    by_logical = {
        "plate.prt": [("uuid-lib", "lib/plate.prt"), ("uuid-asm", "asm/plate.prt")],
    }
    tree = [{"filename": "plate.prt", "children": []}]
    assert _enrich_bom_tree(tree, by_logical, "asm/top.asm")[0]["object_id"] == "uuid-asm"
    assert _enrich_bom_tree(tree, by_logical, "lib/other.asm")[0]["object_id"] == "uuid-lib"
    # equally near: no link rather than a wrong one
    assert "object_id" not in _enrich_bom_tree(tree, by_logical, "top.asm")[0]
    rows = _enrich_structure_rows([{"name": "plate.prt"}], by_logical, "asm/top.asm")
    assert rows[0]["object_id"] == "uuid-asm"


def test_a_sub_assembly_looks_for_its_components_next_to_itself():
    by_logical = {
        "sub.asm": [("uuid-sub", "lib/sub.asm")],
        "bolt.prt": [("uuid-bolt-lib", "lib/bolt.prt"), ("uuid-bolt-asm", "asm/bolt.prt")],
    }
    tree = [{"filename": "sub.asm", "children": [{"filename": "bolt.prt", "children": []}]}]
    child = _enrich_bom_tree(tree, by_logical, "asm/top.asm")[0]["children"][0]
    assert child["object_id"] == "uuid-bolt-lib"  # next to lib/sub.asm, not next to asm/top.asm
