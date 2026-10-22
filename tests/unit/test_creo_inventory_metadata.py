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


def test_pack_unpack_features_json_envelope():
    features = [{"id": 1, "name": "RIGHT", "type": "DATUM PLANE", "level": 1, "status": "ACTIVE"}]
    structure = [{"name": "shaft.prt", "id": 42, "type": "PART", "level": 2, "status": "ACTIVE"}]
    raw = pack_features_json(features, structure)
    assert isinstance(raw, dict)
    assert raw.get("v") == 1
    assert raw.get("features") == normalize_feature_rows(features)
    assert raw.get("structure") == structure

    round_features, round_structure, round_simp, round_cons, round_rels = (
        unpack_features_json(raw)
    )
    assert round_features == normalize_feature_rows(features)
    assert round_structure == structure
    assert round_simp is None
    assert round_cons is None
    assert round_rels is None


def test_unpack_legacy_features_list():
    legacy = [{"id": 3, "name": "HOLE", "type": "HOLE", "level": 2, "status": "SUPRESSED"}]
    feats, struct, simp, cons, rels = unpack_features_json(legacy)
    assert struct is None
    assert simp is None
    assert cons is None
    assert rels is None
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
    feats, struct, round_simp, round_cons, round_rels = unpack_features_json(raw)
    assert feats == normalize_feature_rows(features)
    assert struct == []
    assert round_simp == simp_reps
    assert round_cons is None
    assert round_rels is None


def test_pack_unpack_constraints_in_envelope():
    """Assembly constraints ride the features_json v1 envelope beside simp_reps."""
    features = [{"id": 1, "name": "RIGHT", "type": "DATUM PLANE"}]
    constraints = {
        "ok": True,
        "fileName": "top.asm",
        "components": [
            {
                "component_id": 41,
                "component_path": [41],
                "model_name": "bracket.prt",
                "capture_status": "ok",
                "placement": {
                    "placed": True,
                    "packaged": False,
                    "underconstrained": False,
                    "frozen": False,
                },
                "constraints": [
                    {
                        "type": "ASM_CONSTRAINT_MATE",
                        "offset": 5.0,
                        "offset_units": "mm",
                        "assembly_reference": {
                            "model": "top.asm",
                            "item_id": 1,
                            "item_type": "ITEM_SURFACE",
                            "item_name": "FRONT",
                        },
                        "component_reference": {
                            "model": "bracket.prt",
                            "item_id": 2,
                            "item_type": "ITEM_SURFACE",
                            "item_name": "TOP",
                        },
                        "attributes": {"ignore": False, "force": False},
                    }
                ],
            }
        ],
        "errors": [],
    }
    raw = pack_features_json(features, None, None, constraints)
    assert isinstance(raw, dict)
    assert raw.get("v") == 1
    assert raw.get("constraints") == constraints
    feats, struct, simp, round_cons, round_rels = unpack_features_json(raw)
    assert feats == normalize_feature_rows(features)
    assert struct == []
    assert simp is None
    assert round_cons == constraints
    assert round_rels is None


def test_pack_unpack_relations_in_envelope():
    """Model Relations ride the features_json v1 envelope."""
    features = [{"id": 1, "name": "RIGHT", "type": "DATUM PLANE"}]
    relations = {
        "ok": True,
        "fileName": "cover.prt",
        "normal": ["d1 = d2 * 2"],
        "post_regeneration": ["od = id + 1"],
        "features": [
            {
                "feature_id": 12,
                "feature_name": "EXTRUDE_1",
                "relations": ["width = height"],
            }
        ],
        "errors": [],
    }
    raw = pack_features_json(features, None, None, None, relations)
    assert isinstance(raw, dict)
    assert raw.get("v") == 1
    assert raw.get("relations") == relations
    feats, struct, simp, cons, round_rels = unpack_features_json(raw)
    assert feats == normalize_feature_rows(features)
    assert struct == []
    assert simp is None
    assert cons is None
    assert round_rels == relations


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


def test_object_detail_inventory_table_tolerates_missing_level():
    """Legacy features without level must not crash Details (Jinja Undefined)."""
    detail = (ROOT / "src" / "creopdm" / "templates" / "object_detail.html").read_text(
        encoding="utf-8"
    )
    assert "feat.level|default(1, true)|int" in detail
    assert "row.level|default(1, true)|int" in detail
    assert "feat.level|int if feat.level is not none" not in detail
    assert "{% if lvl < 1 %}" in detail


def test_assembly_structure_excludes_datums_and_bare_feature_names():
    """Structure is real components/groups only — not datums, CSYS, or cross-sections."""
    from creopdm.services.metadata_service import (
        filter_assembly_structure_rows,
        is_assembly_structure_noise_row,
        pack_features_json,
        unpack_features_json,
    )

    assert is_assembly_structure_noise_row(
        {"name": "ASM_RIGHT", "type": "COMPONENT", "id": 1}
    )
    assert is_assembly_structure_noise_row(
        {"name": "ASM_DEF_CSYS", "type": "COMPONENT", "id": 7}
    )
    assert is_assembly_structure_noise_row(
        {"name": "A", "type": "COMPONENT", "id": 462}
    )
    assert not is_assembly_structure_noise_row(
        {"name": "BASE-PLATE.prt", "type": "PART", "id": 40}
    )
    assert is_assembly_structure_noise_row(
        {"name": "A", "type": "CROSS_SECTION", "id": 462}
    )
    assert is_assembly_structure_noise_row(
        {"name": "Model cross-sections", "type": "GROUP", "id": None, "subtype": "CROSS_SECTION"}
    )
    assert not is_assembly_structure_noise_row(
        {"name": "IFX_ID_1", "type": "GROUP", "id": 99}
    )

    cleaned = filter_assembly_structure_rows(
        [
            {"name": "ASM_RIGHT", "type": "COMPONENT", "id": 1},
            {"name": "shaft.prt", "type": "PART", "id": 10},
            {"name": "A", "type": "COMPONENT", "id": 462},
            {"name": "Model cross-sections", "type": "GROUP", "id": None},
            {"name": "A", "type": "CROSS_SECTION", "id": 462},
            {"name": "IFX_ID_1", "type": "GROUP", "id": 99},
        ]
    )
    assert [r["name"] for r in cleaned] == ["shaft.prt", "IFX_ID_1"]
    packed = pack_features_json([], cleaned)
    _, struct, _, _, _ = unpack_features_json(packed)
    assert [r["name"] for r in struct] == ["shaft.prt", "IFX_ID_1"]

    base = (
        ROOT / "src" / "creopdm" / "templates" / "base.html"
    ).read_text(encoding="utf-8")
    struct_fn = base.split("function creoInventoryStructureRows(", 1)[1].split(
        "\nfunction ", 1
    )[0]
    assert "tipRe" in struct_fn
    assert "COMPONENT" in struct_fn
    assert "model cross-sections" in struct_fn


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


def test_compare_outline_nests_views_under_correct_sheet():
    """Stored Toolkit snapshots list all sheets then all children — outline must re-nest."""
    text = format_snapshot_compare_text(
        {
            "identity": {"filename": "gorilla-cart.drw", "model_type": "DRAWING"},
            "features": [
                {"id": "sheet:1", "name": "Sheet 1", "type": "SHEET", "level": 1, "sheet": 1},
                {
                    "id": "sheet:2",
                    "name": "Sheet 2 (CURRENT)",
                    "type": "SHEET",
                    "level": 1,
                    "sheet": 2,
                },
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
            ],
            "capture": {"sheet_count": 2},
        }
    )
    inv = text.split("Drawing inventory:", 1)[1]
    # Sheet 1, then its view, then Sheet 2 — not both views under Sheet 2.
    assert inv.index("Sheet 1") < inv.index("new_view_1") < inv.index("Sheet 2")
    assert inv.index("Sheet 2") < inv.index("new_view_3")
    # View under Sheet 1 is indented; bare Sheet lines are not.
    view_line = [ln for ln in inv.splitlines() if "new_view_1" in ln][0]
    sheet1_line = [ln for ln in inv.splitlines() if ln.strip().startswith("- Sheet 1")][0]
    assert view_line.startswith("  -")
    assert sheet1_line.startswith("- Sheet 1")


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
    assert "Simplified representations added:" in diff
    assert "- NO_HARDWARE" in diff
    assert "- NO_PLATE" in diff
    assert "\n\nSimplified representations added:" in diff
    assert "Added simplified representations NO_HARDWARE" not in diff
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
    assert "Active simplified representation changed:" in diff
    assert "- MASTER → LIGHT" in diff
    assert "Simplified representations added" not in diff
    assert "Simplified representations removed" not in diff
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


def _sample_constraints_envelope(*, offset=5.0, order_flip=False, duplicate=False):
    c1 = {
        "type": "ASM_CONSTRAINT_MATE_OFF",
        "offset": offset,
        "offset_units": "mm",
        "assembly_reference": {"model": "top.asm", "item_id": 1, "item_name": "FRONT"},
        "component_reference": {"model": "bracket.prt", "item_id": 2, "item_name": "TOP"},
        "attributes": {"ignore": False, "force": False},
    }
    c2 = {
        "type": "ASM_CONSTRAINT_ALIGN",
        "offset": None,
        "offset_units": None,
        "assembly_reference": {"model": "top.asm", "item_id": 3, "item_name": "RIGHT"},
        "component_reference": {"model": "bracket.prt", "item_id": 4, "item_name": "RIGHT"},
        "attributes": {"ignore": False, "force": False},
    }
    constraints = [c2, c1] if order_flip else [c1, c2]
    if duplicate:
        constraints = [c1, dict(c1)]
    return {
        "ok": True,
        "fileName": "top.asm",
        "components": [
            {
                "component_id": 41,
                "component_path": [40, 41],
                "model_name": "bracket.prt",
                "capture_status": "ok",
                "placement": {
                    "placed": True,
                    "packaged": False,
                    "underconstrained": False,
                    "frozen": False,
                },
                "constraints": constraints,
            }
        ],
        "errors": [],
    }


def test_compare_outline_includes_assembly_constraints():
    text = format_snapshot_compare_text(
        {
            "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
            "structure": [
                {"name": "bracket.prt", "type": "PART", "level": 1, "path": "40/41"},
            ],
            "features": [],
            "parameters": [{"name": "DESCRIPTION", "value": "x"}],
            "constraints": _sample_constraints_envelope(),
        }
    )
    assert "Assembly constraints:" in text
    assert "bracket.prt (40/41)" in text
    assert "Mate Off" in text
    assert "offset 5 mm" in text
    assert text.index("Parameters:") < text.index("Assembly constraints:")
    assert "\n\nAssembly constraints:" in text


def test_compare_outline_omits_offset_for_align_mate_coincident():
    """API Offset=0 on Align/Mate is Creo UI noise (grayed) — do not outline it."""
    text = format_snapshot_compare_text(
        {
            "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
            "features": [],
            "constraints": {
                "ok": True,
                "components": [
                    {
                        "component_id": 41,
                        "component_path": [41],
                        "model_name": "base-plate.prt",
                        "capture_status": "ok",
                        "constraints": [
                            {
                                "type": "ASM_CONSTRAINT_ALIGN",
                                "offset": 0,
                                "offset_units": "mm",
                            },
                            {
                                "type": "ASM_CONSTRAINT_MATE",
                                "offset": 0.0,
                                "offset_units": "mm",
                            },
                            {
                                "type": "ASM_CONSTRAINT_MATE_OFF",
                                "offset": 0.268,
                                "offset_units": "mm",
                            },
                            {
                                "type": "ASM_CONSTRAINT_MATE_OFF",
                                "offset": 0,
                                "offset_units": "mm",
                            },
                        ],
                    }
                ],
            },
        }
    )
    assert "Align" in text
    assert "Mate" in text
    assert "Mate Off · offset 0.268 mm" in text
    assert "Mate Off · offset 0 mm" in text
    # Coincident Align/Mate must not print offset 0.
    assert "Align · offset" not in text
    assert "Mate · offset" not in text


def test_computed_diff_ignores_align_offset_zero_noise():
    """Stored Align offset 0 vs null must not look like a constraint change."""
    older = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "features": [],
        "constraints": {
            "ok": True,
            "components": [
                {
                    "component_id": 1,
                    "component_path": [1],
                    "model_name": "a.prt",
                    "capture_status": "ok",
                    "constraints": [
                        {"type": "ASM_CONSTRAINT_ALIGN", "offset": 0, "offset_units": "mm"}
                    ],
                }
            ],
        },
    }
    newer = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "features": [],
        "constraints": {
            "ok": True,
            "components": [
                {
                    "component_id": 1,
                    "component_path": [1],
                    "model_name": "a.prt",
                    "capture_status": "ok",
                    "constraints": [
                        {"type": "ASM_CONSTRAINT_ALIGN", "offset": None, "offset_units": None}
                    ],
                }
            ],
        },
    }
    diff = format_snapshot_compare_diff_text(older, newer)
    assert "Assembly constraints" not in diff


def test_computed_diff_reports_constraint_offset_change():
    older = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "bracket.prt", "type": "PART", "level": 1}],
        "features": [],
        "constraints": _sample_constraints_envelope(offset=5.0),
    }
    newer = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "bracket.prt", "type": "PART", "level": 1}],
        "features": [],
        "constraints": _sample_constraints_envelope(offset=10.0),
    }
    diff = format_snapshot_compare_diff_text(older, newer)
    assert "Assembly constraints changed (bracket.prt (40/41)):" in diff
    assert "offset 5 mm → 10 mm" in diff
    # Mate Off keeps a real offset; Align/Mate coincident zeros are stripped elsewhere.


def test_computed_diff_omits_constraints_on_reorder_only():
    older = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "bracket.prt", "type": "PART", "level": 1}],
        "features": [],
        "constraints": _sample_constraints_envelope(order_flip=False),
    }
    newer = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "bracket.prt", "type": "PART", "level": 1}],
        "features": [],
        "constraints": _sample_constraints_envelope(order_flip=True),
    }
    diff = format_snapshot_compare_diff_text(older, newer)
    assert "Assembly constraints" not in diff


def test_computed_diff_preserves_duplicate_constraints():
    """Two identical mates: removing one must show a removal (multiset)."""
    older = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "bracket.prt", "type": "PART", "level": 1}],
        "features": [],
        "constraints": _sample_constraints_envelope(duplicate=True),
    }
    newer = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "bracket.prt", "type": "PART", "level": 1}],
        "features": [],
        "constraints": _sample_constraints_envelope(duplicate=False),
    }
    # duplicate=False still has Mate+Align; duplicate=True has Mate+Mate — Align removed, one Mate removed conceptually
    # Build a clearer duplicate case:
    older["constraints"] = {
        "ok": True,
        "components": [
            {
                "component_id": 41,
                "component_path": [41],
                "model_name": "bracket.prt",
                "capture_status": "ok",
                "constraints": [
                    {"type": "ASM_CONSTRAINT_MATE", "offset": 1.0, "offset_units": "mm"},
                    {"type": "ASM_CONSTRAINT_MATE", "offset": 1.0, "offset_units": "mm"},
                ],
            }
        ],
    }
    newer["constraints"] = {
        "ok": True,
        "components": [
            {
                "component_id": 41,
                "component_path": [41],
                "model_name": "bracket.prt",
                "capture_status": "ok",
                "constraints": [
                    {"type": "ASM_CONSTRAINT_MATE", "offset": 1.0, "offset_units": "mm"},
                ],
            }
        ],
    }
    diff = format_snapshot_compare_diff_text(older, newer)
    assert "Assembly constraints removed" in diff
    assert "Mate" in diff


def test_computed_diff_not_captured_when_constraints_missing_on_old():
    """Missing envelope must not invent mass removals/adds."""
    older = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "bracket.prt", "type": "PART", "level": 1}],
        "features": [],
    }
    newer = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "bracket.prt", "type": "PART", "level": 1}],
        "features": [],
        "constraints": _sample_constraints_envelope(),
    }
    diff = format_snapshot_compare_diff_text(older, newer)
    assert "Not captured" in diff
    assert "Assembly constraints added" not in diff
    assert "Assembly constraints removed" not in diff


def _sample_relations_envelope(*, reorder=False):
    normal = ["d2 = d1", "od = id + 2"] if reorder else ["od = id + 2", "d2 = d1"]
    return {
        "ok": True,
        "fileName": "cover.prt",
        "normal": normal,
        "post_regeneration": ["clearance = 0.1"],
        "features": [
            {
                "feature_id": 12,
                "feature_name": "EXTRUDE_1",
                "relations": ["width = height"],
            }
        ],
        "errors": [],
    }


def test_compare_outline_includes_relations():
    text = format_snapshot_compare_text(
        {
            "identity": {"filename": "cover.prt", "model_type": "PART"},
            "features": [],
            "parameters": [{"name": "DESCRIPTION", "value": "x"}],
            "relations": _sample_relations_envelope(),
        }
    )
    assert "Relations:" in text
    assert "od = id + 2" in text
    assert "Post-regeneration relations:" in text
    assert "clearance = 0.1" in text
    assert "Feature relations:" in text
    assert "EXTRUDE_1 (12)" in text
    assert "width = height" in text
    assert text.index("Parameters:") < text.index("Relations:")
    assert "\n\nRelations:" in text


def test_computed_diff_reports_relation_line_added():
    older = {
        "identity": {"filename": "cover.prt", "model_type": "PART"},
        "features": [],
        "relations": {
            "ok": True,
            "normal": ["od = id + 2"],
            "post_regeneration": [],
            "features": [],
        },
    }
    newer = {
        "identity": {"filename": "cover.prt", "model_type": "PART"},
        "features": [],
        "relations": {
            "ok": True,
            "normal": ["od = id + 2", "d2 = d1"],
            "post_regeneration": [],
            "features": [],
        },
    }
    diff = format_snapshot_compare_diff_text(older, newer)
    assert "Relations added:" in diff
    assert "- d2 = d1" in diff


def test_computed_diff_omits_relations_on_reorder_only():
    older = {
        "identity": {"filename": "cover.prt", "model_type": "PART"},
        "features": [],
        "relations": _sample_relations_envelope(reorder=False),
    }
    newer = {
        "identity": {"filename": "cover.prt", "model_type": "PART"},
        "features": [],
        "relations": _sample_relations_envelope(reorder=True),
    }
    diff = format_snapshot_compare_diff_text(older, newer)
    assert "Relations" not in diff


def test_computed_diff_not_captured_when_relations_missing_on_old():
    older = {
        "identity": {"filename": "cover.prt", "model_type": "PART"},
        "features": [],
    }
    newer = {
        "identity": {"filename": "cover.prt", "model_type": "PART"},
        "features": [],
        "relations": _sample_relations_envelope(),
    }
    diff = format_snapshot_compare_diff_text(older, newer)
    assert "Not captured" in diff
    assert "Relations added" not in diff


def test_computed_diff_feature_relations_bucket():
    older = {
        "identity": {"filename": "cover.prt", "model_type": "PART"},
        "features": [],
        "relations": {
            "ok": True,
            "normal": [],
            "post_regeneration": [],
            "features": [
                {
                    "feature_id": 12,
                    "feature_name": "EXTRUDE_1",
                    "relations": ["width = height"],
                }
            ],
        },
    }
    newer = {
        "identity": {"filename": "cover.prt", "model_type": "PART"},
        "features": [],
        "relations": {
            "ok": True,
            "normal": [],
            "post_regeneration": [],
            "features": [
                {
                    "feature_id": 12,
                    "feature_name": "EXTRUDE_1",
                    "relations": ["width = height * 2"],
                }
            ],
        },
    }
    diff = format_snapshot_compare_diff_text(older, newer)
    assert "Feature relations removed (EXTRUDE_1 (12)):" in diff
    assert "- width = height" in diff
    assert "Feature relations added (EXTRUDE_1 (12)):" in diff
    assert "- width = height * 2" in diff


def test_computed_diff_null_offset_not_equal_to_zero():
    """On Mate Offset, null vs numeric 0 is a real change (Offset UI enabled)."""
    older = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "a.prt", "type": "PART", "level": 1}],
        "features": [],
        "constraints": {
            "ok": True,
            "components": [
                {
                    "component_id": 1,
                    "component_path": [1],
                    "model_name": "a.prt",
                    "capture_status": "ok",
                    "constraints": [
                        {
                            "type": "ASM_CONSTRAINT_MATE_OFF",
                            "offset": None,
                            "offset_units": None,
                        }
                    ],
                }
            ],
        },
    }
    newer = {
        "identity": {"filename": "top.asm", "model_type": "ASSEMBLY"},
        "structure": [{"name": "a.prt", "type": "PART", "level": 1}],
        "features": [],
        "constraints": {
            "ok": True,
            "components": [
                {
                    "component_id": 1,
                    "component_path": [1],
                    "model_name": "a.prt",
                    "capture_status": "ok",
                    "constraints": [
                        {
                            "type": "ASM_CONSTRAINT_MATE_OFF",
                            "offset": 0.0,
                            "offset_units": "mm",
                        }
                    ],
                }
            ],
        },
    }
    diff = format_snapshot_compare_diff_text(older, newer)
    assert "Assembly constraints changed" in diff
    assert "offset" in diff


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
