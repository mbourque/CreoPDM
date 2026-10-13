"""Feature Name: Creo feature.name as-is; never use subtype placeholders as Name."""

from creopdm.services.metadata_service import (
    normalize_feature_rows,
    scrub_relations_placeholder_names,
)
from creopdm.toolkit_snapshot import normalize_toolkit_feature_rows


def test_normalize_feature_rows_replaces_general_and_edge_placeholders():
    rows = normalize_feature_rows(
        [
            {"id": 1252, "name": "ROUND", "type": "ROUND", "subtype": "General"},
            {"id": 2222, "name": "Edge", "type": "CHAMFER", "subtype": "Edge"},
            {"id": 5253, "name": "FIXTURE-HOLES", "type": "SMT CUT", "subtype": "Extrude"},
            {"id": 3, "name": "RIGHT", "type": "DATUM PLANE", "subtype": ""},
        ]
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[1252]["name"] == "ROUND"
    # Edge is FeatSubType for chamfer — Name should be CHAMFER, not Edge.
    assert by_id[2222]["name"] == "CHAMFER"
    assert by_id[5253]["name"] == "FIXTURE-HOLES"
    assert by_id[3]["name"] == "RIGHT"


def test_normalize_feature_rows_keeps_creo_name_as_is():
    rows = normalize_feature_rows(
        [{"id": 1, "name": "Round 3", "type": "ROUND", "subtype": "General"}]
    )
    assert rows[0]["name"] == "Round 3"


def test_normalize_feature_rows_preserves_level_and_status():
    rows = normalize_feature_rows(
        [{"id": 1, "name": "CUT", "type": "CUT", "level": 2, "status": "SUPRESSED"}]
    )
    assert rows[0]["level"] == 2
    assert rows[0]["status"] == "SUPRESSED"


def test_normalize_feature_rows_ignores_non_dicts():
    assert normalize_feature_rows(None) == []
    assert normalize_feature_rows([None, "x", {"name": "DEFAULT_CS", "type": "COORDINATE SYSTEM"}]) == [
        {"name": "DEFAULT_CS", "type": "COORDINATE SYSTEM"}
    ]


def test_normalize_feature_rows_drops_no_name_and_invisible():
    """Stale Collect JSON must not keep Creo no_name / invisible internals on Details."""
    rows = normalize_feature_rows(
        [
            {"id": 1, "name": "ASM_RIGHT", "type": "DATUM_PLANE", "visible": True},
            {"id": 451, "name": "no_name", "type": "DATUM_PLANE", "visible": True},
            {"id": 454, "name": "NO_NAME", "type": "DATUM_PLANE"},
            {"id": 99, "name": "HIDDEN_PLANE", "type": "DATUM_PLANE", "visible": False},
            {"id": 7, "name": "ASM_DEF_CSYS", "type": "COORDINATE_SYSTEM"},
        ]
    )
    ids = [row["id"] for row in rows]
    assert ids == [1, 7]
    assert all(str(row["name"]).lower() != "no_name" for row in rows)


def test_scrub_relations_clears_no_name_feature_name():
    scrubbed = scrub_relations_placeholder_names(
        {
            "normal": ["a = 1"],
            "features": [
                {
                    "feature_id": 451,
                    "feature_name": "no_name",
                    "relations": ["x = 2"],
                },
                {
                    "feature_id": 12,
                    "feature_name": "EXTRUDE_1",
                    "relations": ["y = 3"],
                },
            ],
        }
    )
    assert scrubbed is not None
    assert scrubbed["features"][0]["feature_name"] is None
    assert scrubbed["features"][0]["relations"] == ["x = 2"]
    assert scrubbed["features"][1]["feature_name"] == "EXTRUDE_1"


def test_normalize_toolkit_feature_rows_drops_no_name():
    rows = normalize_toolkit_feature_rows(
        [
            {"id": 1, "name": "RIGHT", "type": "DATUM_PLANE", "level": 0},
            {"id": 451, "name": "no_name", "type": "DATUM_PLANE", "level": 1},
        ]
    )
    assert rows is not None
    assert len(rows) == 1
    assert rows[0]["id"] == 1
    assert rows[0]["level"] == 1
