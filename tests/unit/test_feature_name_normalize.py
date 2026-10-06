"""Feature Name: Creo GetName as-is; never invent order; skip General subtype."""

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


def test_normalize_feature_rows_does_not_invent_order_from_number():
    # Order belongs only if Creo GetName returned it — we must not synthesize.
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
        ]
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[2457]["name"] == "ROUND"
    assert by_id[19]["name"] == "Extrude"


def test_normalize_feature_rows_keeps_creo_name_with_order_as_is():
    rows = normalize_feature_rows(
        [{"id": 1, "name": "Round 3", "type": "ROUND", "subtype": "General"}]
    )
    assert rows[0]["name"] == "Round 3"


def test_normalize_feature_rows_ignores_non_dicts():
    assert normalize_feature_rows(None) == []
    assert normalize_feature_rows([None, "x", {"name": "DEFAULT_CS", "type": "COORDINATE SYSTEM"}]) == [
        {"name": "DEFAULT_CS", "type": "COORDINATE SYSTEM"}
    ]
