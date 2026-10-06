"""Feature Name column: skip Creo subtype placeholders like General."""

from creopdm.services.metadata_service import normalize_feature_rows


def test_normalize_feature_rows_replaces_general_with_type():
    # ROUND / General used to show Name=General; model tree says Round.
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


def test_normalize_feature_rows_ignores_non_dicts():
    assert normalize_feature_rows(None) == []
    assert normalize_feature_rows([None, "x", {"name": "DEFAULT_CS", "type": "COORDINATE SYSTEM"}]) == [
        {"name": "DEFAULT_CS", "type": "COORDINATE SYSTEM"}
    ]
