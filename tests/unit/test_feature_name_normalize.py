"""Feature Name: Creo feature.name as-is; never use subtype placeholders as Name."""

from creopdm.services.metadata_service import normalize_feature_rows


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


def test_normalize_feature_rows_ignores_non_dicts():
    assert normalize_feature_rows(None) == []
    assert normalize_feature_rows([None, "x", {"name": "DEFAULT_CS", "type": "COORDINATE SYSTEM"}]) == [
        {"name": "DEFAULT_CS", "type": "COORDINATE SYSTEM"}
    ]
