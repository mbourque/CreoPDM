"""Toolkit /collect → Creo.JS-gather-shaped snapshot mapping."""

from creopdm.services.metadata_service import filter_assembly_structure_rows
from creopdm.toolkit_snapshot import (
    domains_for_filename,
    map_toolkit_collect_to_snapshot,
    normalize_toolkit_mass,
    normalize_toolkit_structure_row,
    toolkit_snapshot_reject_reason,
)


def test_domains_for_filename_by_extension():
    assert "mass" in domains_for_filename("wedge.prt")
    assert "materials" in domains_for_filename("wedge.prt.3")
    assert "structure" in domains_for_filename("top.asm")
    assert "drawing" in domains_for_filename("wedge.drw")
    assert "mfg" in domains_for_filename("basic-milling1.mfg")
    assert "features" in domains_for_filename("notes.txt")


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
