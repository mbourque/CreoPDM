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
    block = text.split("Features suppressed by insert mode:", 1)[1]
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
    block = moved.split("Features suppressed by insert mode:", 1)[1]
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
