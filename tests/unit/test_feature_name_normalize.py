"""Feature Name column: skip General; append Creo order for unnamed features."""

from creopdm.services.metadata_service import normalize_feature_rows


def test_normalize_feature_rows_replaces_general_with_type():
    rows = normalize_feature_rows(
        [
            {"id": 2457, "name": "General", "type": "ROUND", "subtype": "General"},
            {"id": 3, "name": "RIGHT", "type": "DATUM PLANE", "subtype": ""},
            {"id": 19, "name": "", "type": "WALL SURFACE", "subtype": "Extrude"},
        ]
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[2457]["name"] == "ROUND"
    assert by_id[3]["name"] == "RIGHT"
    assert by_id[19]["name"] == "Extrude"


def test_normalize_feature_rows_appends_order_for_unnamed_type():
    rows = normalize_feature_rows(
        [
            {
                "id": 2457,
                "name": "General",
                "type": "ROUND",
                "subtype": "General",
                "number": 3,
            },
            {
                "id": 19,
                "name": "Extrude",
                "type": "WALL SURFACE",
                "subtype": "Extrude",
                "number": 1,
            },
            {
                "id": 3,
                "name": "RIGHT",
                "type": "DATUM PLANE",
                "subtype": "",
                "number": 2,
            },
        ]
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[2457]["name"] == "ROUND 3"
    assert by_id[19]["name"] == "Extrude 1"
    # Real rename — do not append order.
    assert by_id[3]["name"] == "RIGHT"


def test_normalize_feature_rows_ignores_non_dicts():
    assert normalize_feature_rows(None) == []
    assert normalize_feature_rows([None, "x", {"name": "DEFAULT_CS", "type": "COORDINATE SYSTEM"}]) == [
        {"name": "DEFAULT_CS", "type": "COORDINATE SYSTEM"}
    ]
