"""Creo 2D section (.sec) metadata from Toolkit Companion 0.5.0 (provisional contract)."""

from creopdm.toolkit_snapshot import domains_for_filename, map_toolkit_collect_to_snapshot
from creopdm.utils.sketch_metadata import sketch_overview

SKETCH = {
    "ok": True,
    "units": {"length": "inch", "angle": "deg"},
    "outline": {"min": [0.0, 0.0], "max": [4.98, 2.25], "width": 4.98, "height": 2.25},
    "entities": {
        "total": 6,
        "counts": {"line": 4, "arc": 2, "circle": 0, "spline": 0, "point": 0,
                   "centerline": 0, "text": 0, "other": 0},
        "construction_count": 1,
        "items": [{"id": 1, "type": "line", "start": [0, 0], "end": [4.98, 0], "construction": False}],
        "truncated": False,
    },
    "dimensions": [
        {"id": "sd0", "type": "linear", "value": 4.98, "display": " 4.980 ",
         "entity_ids": [1], "reference": None, "tolerance": None},
        {"id": "sd1", "type": "radial", "value": 0.125, "display": "R 0.125",
         "entity_ids": [5], "reference": False, "tolerance": None},
    ],
    "constraints": [
        {"type": "horizontal", "entity_ids": [1]},
        {"type": "horizontal", "entity_ids": [3]},
        {"type": "tangent", "entity_ids": [4, 5]},
    ],
    "loops": {"closed": 1, "open": 0},
    "status": {"fully_dimensioned": None, "over_constrained": None, "strong_dimensions": None,
               "weak_dimensions": None, "regenerated": None},
}


def test_sec_collect_asks_only_for_identity_and_sketch():
    assert domains_for_filename("test-sec.sec") == "identity,sketch"
    assert domains_for_filename("TEST-SEC.SEC.3") == "identity,sketch"  # numbered save
    assert domains_for_filename("shaft.prt") != "identity,sketch"


def test_toolkit_section_collect_maps_the_sketch_and_ignores_not_applicable_domains():
    payload = {
        "ok": True,
        "fileName": "test-sec.sec",
        "domains": {
            "identity": {
                "ok": True,
                "identity": {
                    "file_name": "test-sec.sec",
                    "common_name": "TEST-SEC",
                    "model_type": "SECTION",
                    "creo_release": "Creo 10.0.10.0",
                    "saved_release": "13.4.1.0",
                    "subtype": None,
                },
            },
            "sketch": dict(SKETCH),
            # Expected for a section — not a failure.
            "parameters": {"ok": False, "error": "parameters does not apply to a SECTION"},
        },
    }
    snap = map_toolkit_collect_to_snapshot(payload, fallback_filename="test-sec.sec")
    assert snap is not None
    assert snap["identity"]["model_type"] == "SECTION"
    assert snap["identity"]["saved_release"] == "13.4.1.0"
    assert snap["sketch"]["outline"]["width"] == 4.98
    assert snap["sketch"]["entities"]["counts"]["line"] == 4
    assert "ok" not in snap["sketch"]  # transport flag, not data
    assert snap["parameters"] == []
    assert snap["features"] in (None, [])


def test_collect_without_a_sketch_domain_has_no_sketch():
    payload = {
        "ok": True,
        "domains": {"identity": {"ok": True, "identity": {"file_name": "shaft.prt"}}},
    }
    snap = map_toolkit_collect_to_snapshot(payload, fallback_filename="shaft.prt")
    assert snap is not None and snap["sketch"] is None


def test_overview_view_model_rows():
    view = sketch_overview(SKETCH)
    assert view["size"] == "4.98 × 2.25 inch"
    assert view["entity_total"] == 6
    assert view["entity_text"] == "4 line, 2 arc"
    assert view["construction_count"] == 1
    assert view["dimension_count"] == 2
    assert view["constraint_total"] == 3
    assert view["constraint_text"] == "2 horizontal, 1 tangent"
    assert view["closed_loops"] == 1
    assert view["loops"] == "1 closed, 0 open"
    assert [d["type"] for d in view["dimensions"]] == ["Linear", "Radius"]
    assert view["dimensions"][0]["value"] == "4.980"  # display text, trimmed
    # null → "—", never false / zero
    assert view["dimensions"][0]["reference"] == "—"
    assert view["dimensions"][1]["reference"] == "No"
    assert view["dimensions"][0]["tolerance"] == "—"
    assert view["fully_dimensioned"] == ""  # shown only when the Toolkit sent a boolean


def test_fully_dimensioned_only_when_the_toolkit_sends_a_boolean():
    yes = dict(SKETCH, status={"fully_dimensioned": True})
    no = dict(SKETCH, status={"fully_dimensioned": False})
    assert sketch_overview(yes)["fully_dimensioned"] == "Yes"
    assert sketch_overview(no)["fully_dimensioned"] == "No"


def test_unknown_values_stay_unknown_and_units_are_not_guessed():
    sparse = {
        "ok": True,
        "units": {"length": None},
        "outline": None,
        "entities": {"total": 3, "counts": {"line": 3}},
        "dimensions": None,
        "constraints": None,
        "loops": None,
    }
    view = sketch_overview(sparse)
    assert view["size"] == ""  # template shows "—"
    assert view["dimension_count"] is None
    assert view["constraint_total"] is None
    assert view["closed_loops"] is None
    sized = dict(SKETCH, units={"length": None})
    assert sketch_overview(sized)["size"] == "4.98 × 2.25"  # no unit invented


def test_nothing_useful_or_a_failed_domain_means_no_sketch_view():
    assert sketch_overview(None) is None
    assert sketch_overview({}) is None
    assert sketch_overview({"ok": False, "error": "x"}) is None
    assert sketch_overview({"ok": True, "entities": {"total": 0, "counts": {}}}) is None


def test_a_failed_sketch_domain_keeps_the_toolkit_reason_instead_of_vanishing():
    # Real Toolkit 0.5.0 answer for a section it could not read.
    payload = {
        "ok": True,
        "domains": {
            "identity": {"ok": True, "identity": {"file_name": "test-sec.sec", "model_type": "SECTION"}},
            "sketch": {"ok": False, "error": "could not read the section entities (ProSectionEntityIdsGet=-2)"},
        },
    }
    snap = map_toolkit_collect_to_snapshot(payload, fallback_filename="test-sec.sec")
    assert snap["sketch"] == {
        "ok": False,
        "error": "could not read the section entities (ProSectionEntityIdsGet=-2)",
    }
    from creopdm.utils.sketch_metadata import sketch_error

    assert sketch_error(snap["sketch"]).endswith("ProSectionEntityIdsGet=-2)")
    assert sketch_overview(snap["sketch"]) is None  # no rows from an error
    assert sketch_error(SKETCH) == ""
    assert sketch_error(None) == ""
    assert sketch_error({"ok": False}) == "the Toolkit could not read this sketch"
