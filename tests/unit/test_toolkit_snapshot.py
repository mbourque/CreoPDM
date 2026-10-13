"""Toolkit /collect → Creo.JS-gather-shaped snapshot mapping."""

from creopdm.toolkit_snapshot import domains_for_filename, map_toolkit_collect_to_snapshot


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
