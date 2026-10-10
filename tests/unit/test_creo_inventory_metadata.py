"""Creo inventory metadata envelope (features_json v1) and HTML contracts."""

from __future__ import annotations

from pathlib import Path

from creopdm.ai_prompts import (
    format_snapshot_compare_diff_text,
    format_snapshot_compare_text,
)
from creopdm.services.metadata_service import (
    normalize_feature_rows,
    pack_features_json,
    unpack_features_json,
)

ROOT = Path(__file__).resolve().parents[2]
BASE_HTML = ROOT / "src" / "creopdm" / "templates" / "base.html"
INV_DIR = ROOT / "src" / "creopdm" / "static" / "creo_inventory"


def test_pack_unpack_features_json_envelope():
    features = [{"id": 1, "name": "RIGHT", "type": "DATUM PLANE", "level": 1, "status": "ACTIVE"}]
    structure = [{"name": "shaft.prt", "id": 42, "type": "PART", "level": 2, "status": "ACTIVE"}]
    raw = pack_features_json(features, structure)
    assert isinstance(raw, dict)
    assert raw.get("v") == 1
    assert raw.get("features") == normalize_feature_rows(features)
    assert raw.get("structure") == structure

    round_features, round_structure, round_simp = unpack_features_json(raw)
    assert round_features == normalize_feature_rows(features)
    assert round_structure == structure
    assert round_simp is None


def test_unpack_legacy_features_list():
    legacy = [{"id": 3, "name": "HOLE", "type": "HOLE", "level": 2, "status": "SUPRESSED"}]
    feats, struct, simp = unpack_features_json(legacy)
    assert struct is None
    assert simp is None
    assert feats == normalize_feature_rows(legacy)


def test_pack_unpack_simp_reps_in_envelope():
    """Assembly SimpRep definitions ride the features_json v1 envelope."""
    features = [{"id": 1, "name": "RIGHT", "type": "DATUM PLANE"}]
    simp_reps = {
        "active": {"id": None, "name": "MASTER", "is_master": True},
        "representations": [
            {
                "id": 12,
                "name": "GEOM_ONLY",
                "type": "SIMPREP_USER_DEFINED",
                "temporary": False,
                "default_action": "SIMPREP_EXCLUDE",
                "instructions_available": True,
                "items": [
                    {"path": [41], "path_kind": "component", "action": "SIMPREP_INCLUDE"}
                ],
            }
        ],
        "errors": [],
    }
    raw = pack_features_json(features, None, simp_reps)
    assert isinstance(raw, dict)
    assert raw.get("v") == 1
    assert raw.get("simp_reps") == simp_reps
    feats, struct, round_simp = unpack_features_json(raw)
    assert feats == normalize_feature_rows(features)
    assert struct == []
    assert round_simp == simp_reps


def test_assembly_inventory_gathers_simp_reps():
    """SimpRep capture lives in assembly inventory (probe + wrapped creojs)."""
    probe = (
        ROOT / "src" / "creopdm" / "static" / "assembly_probe" / "assembly_probe.creojs"
    ).read_text(encoding="utf-8")
    asm = (INV_DIR / "assembly.creojs").read_text(encoding="utf-8")
    for body, label in ((probe, "assembly_probe"), (asm, "creo_inventory/assembly")):
        assert "function listAssemblySimpRepsForModel(" in body, label
        assert "ITEM_SIMPREP" in body, label
        assert "GetActiveSimpRep" in body, label
        assert "GetInstructions" in body, label
        assert "isSimpRepAssembly" in body, label
    assert "function listAssemblySimpRepsForModel(" in asm
    assert "listAssemblySimpRepsForModel: listAssemblySimpRepsForModel" in asm
    text = BASE_HTML.read_text(encoding="utf-8")
    assert "listAssemblySimpRepsForModel" in text
    assert "simp_reps: simp_reps" in text
    assert "active_simp_rep" in text
    # Orchestration only — inventory owns the Toolkit walk.
    assert "function creoGatherSimpReps(" not in text


def test_normalize_feature_rows_keeps_inventory_fields():
    rows = normalize_feature_rows(
        [
            {
                "id": 10,
                "name": "Extrude 1",
                "type": "PROTRUSION",
                "subtype": "Extrude",
                "level": 3,
                "status": "ACTIVE",
                "suppressed": False,
                "sheet": 1,
            }
        ]
    )
    assert rows[0]["level"] == 3
    assert rows[0]["status"] == "ACTIVE"
    assert rows[0]["sheet"] == 1


def test_base_html_loads_creo_inventory_and_list_features_for_model():
    text = BASE_HTML.read_text(encoding="utf-8")
    assert "/static/creo_inventory/features.creojs" in text
    assert "/static/creo_inventory/assembly.creojs" in text
    assert "/static/creo_inventory/drawing.creojs" in text
    assert "function creoInventoryFeatureRows(" in text
    assert "listFeaturesForModel" in text
    assert "listAssemblyStructureForModel" in text
    assert "listDrawingStructureForModel" in text
    assert "structure: structure || null" in text


def test_object_detail_inventory_table_tolerates_missing_level():
    """Legacy features without level must not crash Details (Jinja Undefined)."""
    detail = (ROOT / "src" / "creopdm" / "templates" / "object_detail.html").read_text(
        encoding="utf-8"
    )
    assert "feat.level|default(1)|int" in detail
    assert "row.level|default(1)|int" in detail
    assert "feat.level|int if feat.level is not none" not in detail


def test_creo_inventory_wrapped_files_exist():
    """Generated by scripts/wrap_creo_inventory.py (also pytest_configure when missing)."""
    for name in ("features.creojs", "assembly.creojs", "drawing.creojs"):
        path = INV_DIR / name
        assert path.is_file(), f"missing {path} — run: python scripts/wrap_creo_inventory.py"
        body = path.read_text(encoding="utf-8")
        assert "listForModel" in body
        assert "__creoInv" in body
    feat = (INV_DIR / "features.creojs").read_text(encoding="utf-8")
    assert "function listFeaturesForModel(" in feat
    assert "function listSessionFeatures(" in feat
    asm = (INV_DIR / "assembly.creojs").read_text(encoding="utf-8")
    assert "function listAssemblyStructureForModel(" in asm
    assert "function listAssemblySimpRepsForModel(" in asm
    assert "function listSessionAssemblySimpReps(" in asm
    drw = (INV_DIR / "drawing.creojs").read_text(encoding="utf-8")
    assert "function listDrawingStructureForModel(" in drw
    # Public globals must not collide (each file exports unique names only).
    for name in (
        "listFeaturesForModel",
        "listAssemblyStructureForModel",
        "listDrawingStructureForModel",
    ):
        assert name in feat or name in asm or name in drw
    assert "function listFeaturesForModel(" in feat
    assert "function listAssemblyStructureForModel(" in asm
    assert "function listDrawingStructureForModel(" in drw


def test_feature_probe_and_inventory_omit_pattern_members():
    """Probe + app inventory stay in sync: no IFX staircase, no pattern copies.

    plate_3.prt: contiguous group fallback must not nest GROUP→GROUP; pattern
    IFX/HOLE copies are omitted (skippedPatternMemberCount), not listed.
    """
    probe = (
        ROOT / "src" / "creopdm" / "static" / "feature_probe" / "feature_probe.creojs"
    ).read_text(encoding="utf-8")
    feat = (INV_DIR / "features.creojs").read_text(encoding="utf-8")
    for body, label in ((probe, "feature_probe"), (feat, "creo_inventory/features")):
        assert "staircase" in body, label
        assert "function endsPatternMemberRun(" in body, label
        assert "drop the whole member run" in body, label
        assert "No ListChildren" in body, label
        assert "Pattern members are omitted from the list" in body, label
        assert "Unnamed GROUP_HEAD shells are IFX UDF" in body, label
        assert 'typeName === "HOLE"' in body, label
        claim_break = (
            "if (isGroupHeadFeature(next.feat)) {\n"
            "        claimGroupMember(gsid2, next, gorder2);\n"
            "        break;\n"
            "      }"
        )
        assert claim_break not in body, label
        assert "if (isGroupHeadFeature(next.feat)) {\n        break;\n      }" in body, label
        # Must not re-emit pattern children under the PATTERN head.
        assert "emitEntry(pcs[pi], level + 1)" not in body, label


def test_assembly_probe_and_inventory_prefer_ref_model_over_no_name():
    """Probe + app inventory stay in sync: never label structure rows no_name.

    IFX assemble COMPONENTs often GetName() === 'no_name'; labels must prefer
    ModelDescr/GetModel tip, and unclaimed IFX assemble siblings nest under IFX_*.
    """
    probe = (
        ROOT / "src" / "creopdm" / "static" / "assembly_probe" / "assembly_probe.creojs"
    ).read_text(encoding="utf-8")
    asm = (INV_DIR / "assembly.creojs").read_text(encoding="utf-8")
    for body, label in ((probe, "assembly_probe"), (asm, "creo_inventory/assembly")):
        assert "function usableComponentLabel(" in body, label
        assert 'lower === "no_name"' in body, label
        assert "function descrFileName(" in body, label
        assert "GetModelDescr" in body, label
        assert "never surface the literal placeholder" in body, label
        assert "leave Assemble COMPONENT" in body, label
        assert 'if (!/^IFX_/.test(gstored)) continue;' in body, label
        # Must resolve child tip even when componentModelName was empty.
        assert "if (!name && childModel)" in body, label
        assert "usableComponentLabel(feat.GetName())" in body, label


def test_compare_outline_uses_drawing_inventory():
    text = format_snapshot_compare_text(
        {
            "identity": {"filename": "plate.drw", "model_type": "DRAWING"},
            "features": [
                {"id": "sheet:1", "name": "Sheet 1", "type": "SHEET", "level": 1},
                {
                    "id": "view:FRONT",
                    "name": "FRONT",
                    "type": "VIEW",
                    "level": 2,
                    "sheet": 1,
                    "status": "ACTIVE",
                },
                {
                    "id": "note:12",
                    "name": "NOTE (12)",
                    "type": "NOTE",
                    "level": 2,
                    "sheet": 1,
                    "detail": "REV A",
                },
                {
                    "id": "table:3",
                    "name": "TABLE (3)",
                    "type": "TABLE",
                    "level": 2,
                    "sheet": 1,
                },
            ],
            "capture": {"sheet_count": 1},
        }
    )
    assert "Drawing inventory:" in text
    assert "Sheet 1" in text
    assert "FRONT" in text
    assert "NOTE (12)" in text
    assert "TABLE (3)" in text
    assert "View count:" in text


def test_compare_outline_uses_assembly_structure_inventory():
    text = format_snapshot_compare_text(
        {
            "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
            "structure": [
                {"name": "bracket.prt", "type": "PART", "level": 1, "status": "ACTIVE", "path": "40"},
                {"name": "LOCAL_GROUP", "type": "GROUP", "level": 1, "status": "ACTIVE", "path": "55"},
                {"name": "pin.prt", "type": "PART", "level": 2, "status": "ACTIVE", "path": "55/60"},
            ],
            "features": [
                {"id": 1, "name": "DEFAULT_CS", "type": "COORDINATE SYSTEM", "level": 1},
            ],
            "bom": [],
        }
    )
    assert "Structure:" in text
    assert "bracket.prt" in text
    assert "LOCAL_GROUP" in text
    assert "pin.prt" in text
    assert "Assembly features (non-component):" in text
    assert "DEFAULT_CS" in text


def test_compare_outline_includes_assembly_simp_reps():
    """SimpRep exclude rules appear as representation context, not Structure deletes."""
    text = format_snapshot_compare_text(
        {
            "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
            "structure": [
                {
                    "name": "bracket.prt",
                    "type": "PART",
                    "level": 1,
                    "status": "SIMP_REP_SUPPRESSED",
                },
            ],
            "features": [],
            "parameters": [{"name": "DESCRIPTION", "value": "x"}],
            "simp_reps": {
                "active": {"id": 12, "name": "GEOM_ONLY", "is_master": False},
                "representations": [
                    {
                        "id": 12,
                        "name": "GEOM_ONLY",
                        "default_action": "SIMPREP_EXCLUDE",
                        "instructions_available": True,
                        "items": [
                            {
                                "path": [41],
                                "path_kind": "component",
                                "action": "SIMPREP_INCLUDE",
                            }
                        ],
                    }
                ],
            },
        }
    )
    assert "Simplified representations (active: GEOM_ONLY):" in text
    assert "GEOM_ONLY" in text
    assert "default SIMPREP_EXCLUDE" in text
    assert "1 item rule(s)" in text
    # Keep at end of outline (after Parameters), not buried under Structure.
    assert text.index("Parameters:") < text.index("Simplified representations")
    assert text.index("Structure:") < text.index("Simplified representations")
    # Blank line between major outline sections (readable in Modifications / Ask AI).
    assert "\n\nAssembly features (non-component):" in text
    assert "\n\nParameters:" in text
    assert "\n\nSimplified representations" in text
    # Never put SIMP_REP_* on Structure lines (Ask AI invents removals/adds).
    assert "SIMP_REP_SUPPRESSED" not in text
    assert "bracket.prt (PART)" in text
    # Must not invent a Structure delete from exclude rules.
    assert "Features removed" not in text
    assert "deleted" not in text.lower()


def test_compare_outline_blank_divides_part_and_drawing_sections():
    part = format_snapshot_compare_text(
        {
            "identity": {"filename": "pin.prt", "model_type": "PART"},
            "features": [{"name": "EXTRUDE_1", "type": "SOLID", "id": 5}],
            "dimensions": [{"symbol": "d0", "value": 1.0, "units": "in"}],
            "parameters": [{"name": "DESCRIPTION", "value": "pin"}],
        }
    )
    assert "\n\nFeatures:" in part
    assert "\n\nDimensions:" in part
    assert "\n\nParameters:" in part

    drawing = format_snapshot_compare_text(
        {
            "identity": {"filename": "pin.drw", "model_type": "DRAWING"},
            "capture": {
                "sheet_count": 1,
                "drawing_models": [{"filename": "pin.prt", "model_type": "PART"}],
            },
            "features": [
                {"name": "FRONT", "type": "VIEW", "sheet": 1},
                {"name": "NOTE (1)", "type": "NOTE", "sheet": 1, "detail": "A"},
            ],
            "parameters": [{"name": "TITLE", "value": "PIN"}],
        }
    )
    assert "\n\nReferenced models:" in drawing or "\n\nDrawing inventory:" in drawing
    assert "\n\nParameters:" in drawing

def test_computed_diff_reports_simp_reps_added_when_only_on_new():
    """Ask AI must see SimpRep defs in Computed differences (not buried in Structure)."""
    older = {
        "identity": {"filename": "conveyor.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "tube.prt", "type": "PART", "level": 1}],
        "features": [],
    }
    newer = {
        "identity": {"filename": "conveyor.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "tube.prt", "type": "PART", "level": 1}],
        "features": [],
        "simp_reps": {
            "active": {"id": None, "name": "MASTER", "is_master": True},
            "representations": [
                {
                    "name": "NO_HARDWARE",
                    "default_action": "SIMPREP_EXCLUDE",
                    "items": [{"path": [1]}],
                },
                {
                    "name": "NO_PLATE",
                    "default_action": "SIMPREP_EXCLUDE",
                    "items": [{"path": [2]}],
                },
            ],
        },
    }
    diff = format_snapshot_compare_diff_text(older, newer)
    assert (
        "Added simplified representations NO_HARDWARE and NO_PLATE." in diff
    )
    assert "now include" not in diff.lower()
    assert "include/exclude" not in diff.lower()
    assert "active: MASTER" not in diff
    assert "Components removed: (none)" in diff or "Components removed" in diff

def test_computed_diff_reports_simp_rep_active_change():
    older = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "a.prt", "type": "PART", "level": 1}],
        "features": [],
        "simp_reps": {
            "active": {"name": "MASTER", "is_master": True},
            "representations": [
                {"name": "LIGHT", "default_action": "SIMPREP_INCLUDE", "items": []},
            ],
        },
    }
    newer = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "a.prt", "type": "PART", "level": 1}],
        "features": [],
        "simp_reps": {
            "active": {"id": 12, "name": "LIGHT", "is_master": False},
            "representations": [
                {"name": "LIGHT", "default_action": "SIMPREP_INCLUDE", "items": []},
            ],
        },
    }
    diff = format_snapshot_compare_diff_text(older, newer)
    assert (
        "Switched the active simplified representation from MASTER to LIGHT."
        in diff
    )
    assert "Added simplified representations" not in diff
    assert "Removed simplified representations" not in diff
def test_computed_diff_omits_simp_reps_when_unchanged():
    simp = {
        "active": {"name": "MASTER", "is_master": True},
        "representations": [
            {
                "name": "NO_HARDWARE",
                "default_action": "SIMPREP_EXCLUDE",
                "items": [{"path": [1]}],
            },
        ],
    }
    older = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "a.prt", "type": "PART", "level": 1}],
        "features": [],
        "simp_reps": simp,
    }
    newer = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "a.prt", "type": "PART", "level": 1}],
        "features": [],
        "simp_reps": simp,
    }
    diff = format_snapshot_compare_diff_text(older, newer)
    assert "Simplified representations" not in diff


def test_compare_diff_detects_drawing_note_change():
    older = {
        "identity": {"filename": "plate.drw", "model_type": "DRAWING"},
        "features": [
            {"name": "FRONT", "type": "VIEW", "sheet": 1},
            {"name": "NOTE (12)", "type": "NOTE", "sheet": 1, "detail": "REV A"},
        ],
    }
    newer = {
        "identity": {"filename": "plate.drw", "model_type": "DRAWING"},
        "features": [
            {"name": "FRONT", "type": "VIEW", "sheet": 1},
            {"name": "NOTE (12)", "type": "NOTE", "sheet": 1, "detail": "REV B"},
            {"name": "NOTE (99)", "type": "NOTE", "sheet": 1, "detail": "NEW"},
        ],
    }
    diff = format_snapshot_compare_diff_text(older, newer)
    assert "Features removed" in diff
    assert "REV A" in diff
    assert "Features added" in diff
    assert "REV B" in diff
    assert "NOTE (99)" in diff
