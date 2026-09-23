"""BOM/structure name matching, including family-table generics."""

from creopdm.api.pages import _enrich_bom_tree
from creopdm.utils.bom_match import (
    bom_generic_label,
    bom_lookup_keys,
    bom_where_used_keys,
    filenames_refer_to_same_model,
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


def test_enrich_bom_links_instance_to_generic_uuid():
    by_logical = {"split-rivet.prt": "uuid-generic", "top-back.prt": "uuid-top"}
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
