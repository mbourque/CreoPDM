"""Revision compare: each feature's status / suppressed state, and Insert mode on / off / moved."""

from __future__ import annotations

from creopdm.ai_prompts import format_snapshot_compare_diff_text, prepare_snapshot_for_compare
from creopdm.toolkit_snapshot import map_toolkit_collect_to_snapshot, normalize_toolkit_insert_mode


def _feat(fid, name, ftype="PROTRUSION", **extra):
    return {"id": fid, "name": name, "type": ftype, "status": "ACTIVE", "suppressed": False, **extra}


def _part(features, insert_mode=None, model="PART", bom=None):
    snap = {"identity": {"model_type": model, "filename": "bracket.prt"}, "features": features}
    if insert_mode is not None:
        snap["insert_mode"] = insert_mode
    if bom is not None:
        snap["bom"] = bom
    return snap


def _diff(older, newer):
    return format_snapshot_compare_diff_text(prepare_snapshot_for_compare(older), prepare_snapshot_for_compare(newer))


BASE = [_feat(10, "BASE_EXTRUDE"), _feat(20, "HOLE_1", "HOLE"), _feat(30, "ROUND_1", "ROUND"), _feat(40, "SHELL_1", "SHELL")]


def test_a_feature_the_user_suppressed_is_reported_with_both_states():
    newer = [dict(f) for f in BASE]
    newer[1]["status"], newer[1]["suppressed"] = "SUPPRESSED", True
    text = _diff(_part(BASE), _part(newer))
    assert "Features status changed:" in text
    assert "- HOLE_1 (20): active → suppressed" in text
    # nothing was added or removed: ids and names alone saw no change before
    assert "Features added: (none)" in text and "Features removed: (none)" in text


def test_the_suppressed_flag_alone_counts_and_resuming_is_reported():
    older = [dict(f) for f in BASE]
    older[2]["suppressed"] = True  # flag only, status text still ACTIVE
    text = _diff(_part(older), _part(BASE))
    assert "- ROUND_1 (30): suppressed → active" in text


def test_other_statuses_are_compared_too():
    newer = [dict(f) for f in BASE]
    newer[3]["status"] = "FAILED"
    assert "- SHELL_1 (40): active → failed" in _diff(_part(BASE), _part(newer))


def test_an_unchanged_status_says_nothing():
    text = _diff(_part(BASE), _part([dict(f) for f in BASE]))
    assert "Features status changed" not in text and "Insert mode" not in text


def test_insert_mode_turned_on_lists_what_it_suppressed_and_is_not_a_user_suppress():
    newer = [dict(f) for f in BASE]
    for row in newer[2:]:  # after HOLE_1: suppressed BY INSERT MODE, not by the user
        row["status"], row["suppressed"], row["after_insert"] = "SUPPRESSED", True, True
    mode = {"active": True, "after_feature_id": 20, "after_feature_name": "HOLE_1"}
    text = _diff(_part(BASE), _part(newer, mode))
    assert "- Insert mode on: after HOLE_1 (20)" in text
    block = text.split("Features suppressed by insert mode (", 1)[1]
    assert "- ROUND_1 (30)" in block and "- SHELL_1 (40)" in block
    # those rows are NOT reported as the user suppressing them
    assert "Features status changed" not in text


def test_insert_mode_moved_and_off():
    mode_a = {"active": True, "after_feature_id": 20, "after_feature_name": "HOLE_1"}
    mode_b = {"active": True, "after_feature_id": 10, "after_feature_name": "BASE_EXTRUDE"}
    after_hole = [dict(f) for f in BASE]
    for row in after_hole[2:]:
        row.update(status="SUPPRESSED", suppressed=True, after_insert=True)
    after_base = [dict(f) for f in BASE]
    for row in after_base[1:]:
        row.update(status="SUPPRESSED", suppressed=True, after_insert=True)

    moved = _diff(_part(after_hole, mode_a), _part(after_base, mode_b))
    assert "- Insert mode moved: after BASE_EXTRUDE (10) (was after HOLE_1 (20))" in moved
    # only the feature that was not already suppressed by insert mode became suppressed
    block = moved.split("Features suppressed by insert mode (", 1)[1]
    assert "- HOLE_1 (20)" in block and "ROUND_1" not in block

    off = _diff(_part(after_hole, mode_a), _part(BASE))
    assert "- Insert mode off (was after HOLE_1 (20))" in off
    assert "Features suppressed by insert mode" not in off


def test_the_insert_point_name_comes_from_the_feature_when_the_toolkit_gave_only_an_id():
    newer = [dict(f) for f in BASE]
    newer[3].update(status="SUPPRESSED", suppressed=True, after_insert=True)
    text = _diff(_part(BASE), _part(newer, {"active": True, "after_feature_id": 30}))
    assert "- Insert mode on: after ROUND_1 (30)" in text


def test_an_unchanged_insert_point_is_silent():
    mode = {"active": True, "after_feature_id": 20, "after_feature_name": "HOLE_1"}
    rows = [dict(f) for f in BASE]
    for row in rows[2:]:
        row.update(status="SUPPRESSED", suppressed=True, after_insert=True)
    assert "Insert mode" not in _diff(_part(rows, mode), _part([dict(r) for r in rows], dict(mode)))


def test_assemblies_get_both_even_though_their_structure_decides_adds_and_removes():
    bom = [{"filename": "pin.prt", "quantity": 1, "dependency_type": "ASSEMBLY_MEMBER", "children": []}]
    newer = [dict(f) for f in BASE]
    newer[1].update(status="SUPPRESSED", suppressed=True)
    newer_asm = _part(newer, {"active": True, "after_feature_id": 10, "after_feature_name": "BASE_EXTRUDE"},
                      model="ASSEMBLY", bom=bom)
    for row in newer_asm["features"][2:]:
        row.update(status="SUPPRESSED", suppressed=True, after_insert=True)
    text = _diff(_part(BASE, model="ASSEMBLY", bom=bom), newer_asm)
    assert "- Insert mode on: after BASE_EXTRUDE (10)" in text
    assert "- HOLE_1 (20): active → suppressed" in text


def test_drawings_are_left_alone():
    drawing = {"identity": {"model_type": "DRAWING", "filename": "a.drw"}, "features": [_feat(1, "VIEW_1", "VIEW")]}
    changed = {"identity": {"model_type": "DRAWING", "filename": "a.drw"},
               "features": [_feat(1, "VIEW_1", "VIEW", status="SUPPRESSED", suppressed=True)]}
    assert "Features status changed" not in _diff(drawing, changed)


# ---- the Toolkit payload carries insert_mode into the snapshot ---------------------------------


def _payload(insert_mode):
    block = {"ok": True, "features": [_feat(10, "BASE_EXTRUDE")]}
    if insert_mode is not None:
        block["insert_mode"] = insert_mode
    return {"ok": True, "fileName": "bracket.prt",
            "domains": {"identity": {"ok": True, "identity": {"file_name": "bracket.prt", "model_type": "PART"}},
                        "features": block}}


def test_the_toolkit_snapshot_keeps_insert_mode():
    mode = {"active": True, "after_feature_id": 20, "after_feature_name": "HOLE_1"}
    snap = map_toolkit_collect_to_snapshot(_payload(mode), fallback_filename="bracket.prt")
    assert snap["insert_mode"] == mode and snap["ai_snapshot"]["insert_mode"] == mode
    off = map_toolkit_collect_to_snapshot(_payload({"active": False}), fallback_filename="bracket.prt")
    assert off["insert_mode"] == {"active": False}
    none = map_toolkit_collect_to_snapshot(_payload(None), fallback_filename="bracket.prt")
    assert "insert_mode" not in none and "insert_mode" not in none["ai_snapshot"]


def test_insert_mode_normalising():
    assert normalize_toolkit_insert_mode("nope") is None and normalize_toolkit_insert_mode(None) is None
    assert normalize_toolkit_insert_mode({"active": True, "after_feature_id": "", "after_feature_name": " X "}) == {
        "active": True, "after_feature_id": None, "after_feature_name": "X"}
    # when off nothing else is kept
    assert normalize_toolkit_insert_mode({"active": False, "after_feature_id": 3}) == {"active": False}


def test_the_page_sends_insert_mode_with_the_snapshot():
    from pathlib import Path

    app = (Path(__file__).resolve().parents[2] / "src" / "creopdm" / "static" / "js" / "app.js").read_text(
        encoding="utf-8"
    )
    body = app.split("function aiSnapshotBodyFromGather", 1)[1].split("function objectAiSnapshotTipIsStale", 1)[0]
    assert "...(insertMode ? { insert_mode: insertMode } : {})," in body
    assert "gatherSnapshot?.insert_mode" in body and "ai.insert_mode" in body


def test_the_header_prints_the_exact_count_of_features_insert_mode_suppressed():
    newer = [dict(f) for f in BASE]
    for row in newer[1:]:
        row.update(status="SUPPRESSED", suppressed=True, after_insert=True)
    text = _diff(_part(BASE), _part(newer, {"active": True, "after_feature_id": 10, "after_feature_name": "BASE_EXTRUDE"}))
    assert "Features suppressed by insert mode (3):" in text
    assert text.split("Features suppressed by insert mode (3):", 1)[1].count("\n- ") >= 3


def test_the_mass_tab_and_the_comparison_print_the_same_digits():
    from creopdm.utils.mass_format import format_mass_value

    # the values from the wedge.prt revision that looked like a mismatch
    assert format_mass_value(0.000262950643831) == "0.000262951"
    assert format_mass_value(196231.823755) == "196232"
    assert format_mass_value(38929.9590464) == "38930"
    assert format_mass_value(1.34e-09) == "1.34e-09"
    assert format_mass_value(0) == "0"
    assert format_mass_value([0, 17.1781988664, -13.8974935639]) == "[0, 17.1782, -13.8975]"
    older = {"identity": {"model_type": "PART", "filename": "wedge.prt"}, "mass": {"mass": 0.000224892431, "volume": 167830.172}}
    newer = {"identity": {"model_type": "PART", "filename": "wedge.prt"}, "mass": {"mass": 0.000262950643831, "volume": 196231.823755}}
    text = _diff(older, newer)
    assert "- mass: 0.000224892 → 0.000262951" in text and "- volume: 167830 → 196232" in text


def test_the_details_page_uses_the_same_formatter_for_every_mass_value():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    page = (root / "src" / "creopdm" / "templates" / "object_detail.html").read_text(encoding="utf-8")
    panel = page.split('id="panel-mass"', 1)[1].split("</section>", 1)[0]
    for field in ("mass.mass", "mass.volume", "mass.surface_area", "mass.density",
                  "mass.gravity_center[0]", "mass.principal_moments[2]"):
        assert field + "|mass_num" in panel, field
    pages = (root / "src" / "creopdm" / "api" / "pages.py").read_text(encoding="utf-8")
    assert 'templates.env.filters["mass_num"] = format_mass_value' in pages


# ---- removed components: their constraints are implied, every part is named ------------------------


def _asm(parts, constraints):
    """An assembly snapshot: a BOM of (name, qty) and a constraints envelope of (name, id, [types])."""
    return {
        "identity": {"model_type": "ASSEMBLY", "filename": "conveyor.asm"},
        "bom": [
            {"filename": "conveyor.asm", "quantity": 1, "dependency_type": "ASSEMBLY_ROOT", "children": [
                {"filename": name, "quantity": qty, "dependency_type": "ASSEMBLY_MEMBER", "children": []}
                for name, qty in parts
            ]}
        ],
        "constraints": {
            "components": [
                {"model_name": name, "component_id": cid, "component_path": [cid],
                 "constraints": [{"type": kind} for kind in kinds]}
                for name, cid, kinds in constraints
            ]
        },
    }


def test_constraints_of_removed_components_are_not_repeated_but_changes_on_kept_ones_are():
    older = _asm(
        [("square_tube_4.prt", 1), ("plate_3.prt", 1), ("hexbolt-1-8x6_75.prt", 50)],
        [("square_tube_4.prt", 357, ["CSYS"]), ("plate_3.prt", 783, ["ALIGN", "ALIGN", "ALIGN"]),
         ("hexbolt-1-8x6_75.prt", 3439, ["ALIGN", "MATE_OFFSET"])],
    )
    newer = _asm([("square_tube_4.prt", 1)], [("square_tube_4.prt", 357, ["ALIGN", "ALIGN", "MATE"])])
    text = _diff(older, newer)
    # the components that left are named, with the quantity when there is one
    assert "Components removed:" in text
    removed = text.split("Components removed:", 1)[1].split("Components added", 1)[0]
    assert "- plate_3.prt" in removed and "hexbolt-1-8x6_75.prt" in removed
    # ... and their constraints are not listed again (the component change implies them)
    assert "Assembly constraints removed (plate_3.prt" not in text
    assert "Assembly constraints removed (hexbolt" not in text
    # a component that stays and whose constraints changed is still reported
    assert "square_tube_4.prt" in text.split("Assembly constraints", 1)[1]


def test_without_a_components_list_the_constraint_blocks_still_show_removals():
    """No BOM / structure: the constraints are the only evidence a component left."""
    older = {"identity": {"model_type": "ASSEMBLY", "filename": "x.asm"},
             "constraints": {"components": [{"model_name": "plate_3.prt", "component_id": 783,
                                             "component_path": [783], "constraints": [{"type": "ALIGN"}]}]}}
    newer = {"identity": {"model_type": "ASSEMBLY", "filename": "x.asm"}, "constraints": {"components": []}}
    assert "Assembly constraints removed (plate_3.prt" in _diff(older, newer)


def test_the_prompt_makes_the_model_name_every_part():
    from pathlib import Path

    prompt = (Path(__file__).resolve().parents[2] / "docs" / "ai-snapshot-compare-prompt.qwen3-8b-64k.txt").read_text(
        encoding="utf-8"
    )
    assert "Name EVERY part listed under Components removed / added" in prompt
    assert "plate_3.prt" in prompt and "family word" in prompt
    assert "constraints of components that were removed or added are not listed" in prompt
