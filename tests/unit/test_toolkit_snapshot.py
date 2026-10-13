"""Toolkit /collect → Creo.JS-gather-shaped snapshot mapping."""

from creopdm.services.metadata_service import filter_assembly_structure_rows
from creopdm.toolkit_snapshot import (
    domains_for_filename,
    map_toolkit_collect_to_snapshot,
    nest_drawing_inventory_by_sheet,
    normalize_toolkit_feature_rows,
    normalize_toolkit_mass,
    normalize_toolkit_structure_row,
    toolkit_snapshot_reject_reason,
)


def test_domains_for_filename_by_extension():
    assert "mass" in domains_for_filename("wedge.prt")
    assert "materials" in domains_for_filename("wedge.prt.3")
    assert "structure" in domains_for_filename("top.asm")
    assert "bom" in domains_for_filename("top.asm")
    assert "bom" in domains_for_filename("frame.asm.2")
    assert "bom" not in domains_for_filename("wedge.prt")
    assert "drawing" in domains_for_filename("wedge.drw")
    assert "mfg" in domains_for_filename("basic-milling1.mfg")
    assert "features" in domains_for_filename("notes.txt")


def test_map_assembly_collect_includes_nested_bom():
    """Toolkit bom domain → Creo.JS-shaped ASSEMBLY_ROOT tree on snapshot.bom."""
    snap = map_toolkit_collect_to_snapshot(
        {
            "ok": True,
            "fileName": "main.asm",
            "domains": {
                "identity": {
                    "ok": True,
                    "identity": {"file_name": "main.asm", "model_type": "ASSEMBLY"},
                },
                "parameters": {"ok": True, "parameters": []},
                "structure": {"ok": True, "features": []},
                "bom": {
                    "ok": True,
                    "partial": False,
                    "maxDepth": 6,
                    "bom": [
                        {
                            "filename": "main.asm",
                            "quantity": 1,
                            "dependency_type": "ASSEMBLY_ROOT",
                            "type": "ASSEMBLY",
                            "expanded": True,
                            "children": [
                                {
                                    "filename": "base-plate.prt",
                                    "quantity": 1,
                                    "dependency_type": "ASSEMBLY_MEMBER",
                                    "type": "PART",
                                    "children": [],
                                },
                                {
                                    "filename": "bracket.asm",
                                    "quantity": 2,
                                    "dependency_type": "ASSEMBLY_MEMBER",
                                    "type": "ASSEMBLY",
                                    "expanded": True,
                                    "children": [
                                        {
                                            "filename": "arm.prt",
                                            "quantity": 1,
                                            "dependency_type": "ASSEMBLY_MEMBER",
                                            "type": "PART",
                                            "children": [],
                                        }
                                    ],
                                },
                                {
                                    "filename": "skel.prt",
                                    "quantity": 1,
                                    "dependency_type": "ASSEMBLY_MEMBER",
                                    "type": "SKELETON",
                                    "children": [],
                                },
                                {
                                    "filename": "600640041454.prt",
                                    "quantity": 1,
                                    "dependency_type": "ASSEMBLY_MEMBER",
                                    "type": "HARNESS",
                                    "children": [],
                                },
                            ],
                        }
                    ],
                },
            },
        }
    )
    assert snap is not None
    bom = snap["bom"]
    assert isinstance(bom, list) and len(bom) == 1
    root = bom[0]
    assert root["filename"] == "main.asm"
    assert root["dependency_type"] == "ASSEMBLY_ROOT"
    assert root["quantity"] == 1.0
    names = {child["filename"]: child for child in root["children"]}
    assert names["base-plate.prt"]["quantity"] == 1.0
    assert names["bracket.asm"]["quantity"] == 2.0
    assert names["bracket.asm"]["children"][0]["filename"] == "arm.prt"
    assert names["skel.prt"]["type"] == "SKELETON"
    assert names["600640041454.prt"]["type"] == "HARNESS"
    assert snap["ai_snapshot"]["bom"][0]["filename"] == "main.asm"


def test_map_part_collect_identity_features_mass():
    snap = map_toolkit_collect_to_snapshot(
        {
            "ok": True,
            "fileName": "wedge.prt",
            "type": "PART",
            "domains": {
                "identity": {
                    "ok": True,
                    "identity": {"file_name": "wedge.prt", "model_type": "PART"},
                },
                "parameters": {"ok": True, "parameters": [{"name": "A", "value": "1"}]},
                "features": {
                    "ok": True,
                    "features": [{"id": "f:1", "name": "EXTRUDE_1", "type": "FEATURE"}],
                },
                "mass": {"ok": True, "mass": {"volume": 12.5}},
                "materials": {"ok": True, "materials": {"name": "STEEL"}},
            },
        }
    )
    assert snap is not None
    assert snap["identity"]["file_name"] == "wedge.prt"
    assert snap["parameters"][0]["name"] == "A"
    assert snap["features"][0]["name"] == "EXTRUDE_1"
    assert snap["mass"]["volume"] == 12.5
    assert snap["materials"]["name"] == "STEEL"
    assert snap["_pdm_source"] == "toolkit"
    assert snap["relations"] is None
    assert snap["ai_snapshot"]["identity"]["filename"] == "wedge.prt"
    assert snap["ai_snapshot"]["capture"]["source"] == "toolkit"
    assert snap["ai_snapshot"]["mass"]["volume"] == 12.5


def test_nest_drawing_inventory_puts_views_under_their_sheet():
    """Regression: Toolkit dumps all SHEETs then children → outline piles under last sheet."""
    flat = [
        {"id": "sheet:1", "name": "Sheet 1", "type": "SHEET", "level": 1, "sheet": 1},
        {"id": "sheet:2", "name": "Sheet 2 (CURRENT)", "type": "SHEET", "level": 1, "sheet": 2},
        {
            "id": "view:1",
            "name": "new_view_1",
            "type": "VIEW",
            "level": 2,
            "sheet": 1,
        },
        {
            "id": "view:3",
            "name": "new_view_3",
            "type": "VIEW",
            "level": 2,
            "sheet": 2,
        },
        {
            "id": "note:72",
            "name": "Note_72",
            "type": "NOTE",
            "level": 2,
            "sheet": 2,
            "status": "DISPLAYED",
        },
    ]
    nested = nest_drawing_inventory_by_sheet(flat)
    ids = [r["id"] for r in nested]
    assert ids == ["sheet:1", "view:1", "sheet:2", "view:3", "note:72"]
    assert nested[0]["level"] == 1 and nested[1]["level"] == 2
    assert nested[2]["level"] == 1 and nested[3]["level"] == 2

    # Collect path applies the same nest via normalize_toolkit_feature_rows.
    mapped = map_toolkit_collect_to_snapshot(
        {
            "ok": True,
            "fileName": "gorilla-cart.drw",
            "domains": {
                "identity": {
                    "ok": True,
                    "identity": {
                        "file_name": "gorilla-cart.drw",
                        "model_type": "DRAWING",
                    },
                },
                "parameters": {"ok": True, "parameters": []},
                "drawing": {"ok": True, "features": flat},
            },
        }
    )
    assert [r["id"] for r in mapped["features"]] == ids


def test_normalize_feature_rows_leaves_part_features_alone():
    rows = normalize_toolkit_feature_rows(
        [{"id": "95", "name": "CUT", "type": "CUT", "level": 0}]
    )
    assert rows == [{"id": "95", "name": "CUT", "type": "CUT", "level": 1}]


def test_map_drawing_and_mfg_use_domain_features():
    drw = map_toolkit_collect_to_snapshot(
        {
            "ok": True,
            "fileName": "wedge.drw",
            "domains": {
                "identity": {
                    "ok": True,
                    "identity": {"file_name": "wedge.drw", "model_type": "DRAWING"},
                },
                "parameters": {"ok": True, "parameters": []},
                "drawing": {
                    "ok": True,
                    "features": [{"id": "dim:1", "type": "DIMENSION", "subtype": "LINEAR"}],
                },
            },
        }
    )
    assert drw["features"][0]["id"] == "dim:1"

    mfg = map_toolkit_collect_to_snapshot(
        {
            "ok": True,
            "fileName": "basic-milling1.mfg",
            "domains": {
                "identity": {
                    "ok": True,
                    "identity": {"file_name": "basic-milling1.mfg", "model_type": "MFG"},
                },
                "parameters": {"ok": True, "parameters": []},
                "mfg": {
                    "ok": True,
                    "models": [{"id": "mfgmdl:16", "role": "REF_MODEL"}],
                    "features": [{"id": "mfgop:23", "type": "OPERATION"}],
                },
            },
        }
    )
    assert mfg["features"][0]["id"] == "mfgop:23"
    assert mfg["structure"][0]["role"] == "REF_MODEL"


def test_map_rejects_missing_identity():
    assert map_toolkit_collect_to_snapshot({"ok": True, "domains": {}}) is None
    assert map_toolkit_collect_to_snapshot({"ok": False}) is None


def test_toolkit_snapshot_reject_reason_surfaces_collect_error():
    """Busy overlay must not always say missing identity/file_name."""
    reason = toolkit_snapshot_reject_reason(
        {"ok": False, "error": "could not retrieve shaft.prt (not found)"},
        fallback_filename="shaft.prt",
    )
    assert reason.startswith("toolkit_collect_failed:")
    assert "could not retrieve" in reason


def test_map_harness_identity_only_sets_model_role():
    """Cabling harness: Toolkit identity stub → Files Type HARNESS without Retrieve."""
    from creopdm.utils.creo_model_class import files_list_type_from_identity_json
    import json

    snap = map_toolkit_collect_to_snapshot(
        {
            "ok": True,
            "fileName": "600640041454.prt",
            "type": "PART",
            "harness": True,
            "domains": {
                "identity": {
                    "ok": True,
                    "identity": {
                        "file_name": "600640041454.prt",
                        "model_type": "PART",
                        "model_role": "HARNESS",
                        "subtype": "HARNESS",
                        "identity_source": "file_header",
                    },
                },
                "parameters": {
                    "ok": False,
                    "error": "harness_not_openable_in_isolation: open the cabling assembly",
                },
                "features": {
                    "ok": False,
                    "error": "harness_not_openable_in_isolation: open the cabling assembly",
                },
            },
        },
        fallback_filename="600640041454.prt",
    )
    assert snap is not None
    assert snap["identity"]["model_role"] == "HARNESS"
    assert snap["identity"]["model_type"] == "PART"
    assert snap["features"] is None or snap["features"] == []
    assert (
        files_list_type_from_identity_json(json.dumps(snap["identity"])) == "HARNESS"
    )


def test_map_fills_file_name_from_filename_alias_and_fallback():
    """Regression: Collect skips when Toolkit identity uses filename / omits tip."""
    aliased = map_toolkit_collect_to_snapshot(
        {
            "ok": True,
            "fileName": "wedge.prt",
            "domains": {
                "identity": {
                    "ok": True,
                    "identity": {"filename": "wedge.prt", "model_type": "PART"},
                },
                "parameters": {"ok": True, "parameters": []},
            },
        }
    )
    assert aliased is not None
    assert aliased["identity"]["file_name"] == "wedge.prt"

    via_fallback = map_toolkit_collect_to_snapshot(
        {
            "ok": True,
            "domains": {
                "identity": {"ok": True, "identity": {"model_type": "PART"}},
                "parameters": {"ok": True, "parameters": []},
            },
        },
        fallback_filename="600640041454.prt",
    )
    assert via_fallback is not None
    assert via_fallback["identity"]["file_name"] == "600640041454.prt"

    synthesized = map_toolkit_collect_to_snapshot(
        {
            "ok": True,
            "domains": {
                "parameters": {"ok": True, "parameters": [{"name": "A", "value": "1"}]},
            },
        },
        fallback_filename="orphan.prt",
    )
    assert synthesized is not None
    assert synthesized["identity"]["file_name"] == "orphan.prt"
    assert synthesized["parameters"][0]["name"] == "A"


def test_normalize_toolkit_mass_accepts_common_shapes():
    flat = normalize_toolkit_mass(
        {"ok": True, "fileName": "a.prt", "mass": 1.5, "volume": 2.0, "density": 0.1}
    )
    assert flat == {"mass": 1.5, "volume": 2.0, "density": 0.1}

    nested = normalize_toolkit_mass(
        {"ok": True, "mass": {"Volume": 9.0, "Density": 0.2, "Mass": 1.8}}
    )
    assert nested == {"volume": 9.0, "density": 0.2, "mass": 1.8}

    assert normalize_toolkit_mass({"ok": True, "fileName": "a.prt"}) is None


def test_toolkit_structure_component_tips_survive_noise_filter():
    """COMPONENT + tip name must become PART so Details Structure is not empty."""
    promoted = normalize_toolkit_structure_row(
        {"name": "shaft.prt", "type": "COMPONENT", "level": 2, "status": "ACTIVE"}
    )
    assert promoted["type"] == "PART"
    assert filter_assembly_structure_rows([promoted]) == [promoted]

    snap = map_toolkit_collect_to_snapshot(
        {
            "ok": True,
            "fileName": "top.asm",
            "domains": {
                "identity": {
                    "ok": True,
                    "identity": {"file_name": "top.asm", "model_type": "ASSEMBLY"},
                },
                "parameters": {"ok": True, "parameters": []},
                "structure": {
                    "ok": True,
                    "features": [
                        {"name": "shaft.prt", "type": "COMPONENT", "level": 2},
                        {"name": "ASM_RIGHT", "type": "COMPONENT", "level": 1},
                        {"name": "bracket.asm", "type": "COMPONENT", "level": 2},
                    ],
                },
            },
        }
    )
    assert snap is not None
    kept = filter_assembly_structure_rows(snap["structure"])
    assert kept is not None
    names = {row["name"] for row in kept}
    assert names == {"shaft.prt", "bracket.asm"}
    assert {row["type"] for row in kept} == {"PART", "ASSEMBLY"}


def test_toolkit_structure_preserves_skeleton_type_on_prt_tip():
    """Regression: .prt tip must not overwrite Toolkit SKELETON → PART."""
    by_type = normalize_toolkit_structure_row(
        {
            "name": "600610010001.prt",
            "type": "SKELETON",
            "subtype": "SKELETON",
            "is_skeleton": True,
            "level": 1,
        }
    )
    assert by_type["type"] == "SKELETON"
    assert by_type["subtype"] == "SKELETON"
    assert filter_assembly_structure_rows([by_type]) == [by_type]

    by_flag = normalize_toolkit_structure_row(
        {"name": "skel.prt", "type": "PART", "is_skeleton": True, "level": 1}
    )
    assert by_flag["type"] == "SKELETON"
    assert by_flag["subtype"] == "SKELETON"

    by_sub = normalize_toolkit_structure_row(
        {"name": "skel.prt", "type": "COMPONENT", "subtype": "SKELETON", "level": 1}
    )
    assert by_sub["type"] == "SKELETON"


def test_toolkit_structure_preserves_harness_type_on_prt_tip():
    """Cabling harness members must stay on Details Structure (not filtered as noise)."""
    row = normalize_toolkit_structure_row(
        {
            "name": "600640041454.prt",
            "type": "HARNESS",
            "subtype": "HARNESS",
            "is_harness": True,
            "level": 1,
        }
    )
    assert row["type"] == "HARNESS"
    assert filter_assembly_structure_rows([row]) == [row]

    as_part = normalize_toolkit_structure_row(
        {"name": "cable.prt", "type": "PART", "is_harness": True, "level": 2}
    )
    assert as_part["type"] == "HARNESS"
    assert filter_assembly_structure_rows([as_part]) == [as_part]
