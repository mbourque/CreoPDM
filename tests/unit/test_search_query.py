"""Unit tests for Search box glob / anchor → SQL ILIKE conversion."""

from creopdm.utils.search_query import sql_like_from_search_query


def test_plain_text_is_substring():
    assert sql_like_from_search_query("pin") == "%pin%"
    assert sql_like_from_search_query("  Shaft  ") == "%Shaft%"


def test_plain_text_escapes_like_specials():
    assert sql_like_from_search_query("a%b_c") == r"%a\%b\_c%"
    assert sql_like_from_search_query(r"a\b") == r"%a\\b%"


def test_glob_star_and_question():
    assert sql_like_from_search_query("*.prt") == "%.prt"
    assert sql_like_from_search_query("*") == "%"
    assert sql_like_from_search_query("*.*") == "%.%"
    assert sql_like_from_search_query("*.prt.*") == "%.prt.%"
    assert sql_like_from_search_query("shaft?") == "shaft_"
    assert sql_like_from_search_query("CAD/*.prt") == "CAD/%.prt"


def test_glob_escapes_literal_like_specials():
    assert sql_like_from_search_query("*%*") == r"%\%%"
    assert sql_like_from_search_query("*_*") == r"%\_%"


def test_caret_and_dollar_anchors():
    assert sql_like_from_search_query("^CAD/") == "CAD/%"
    assert sql_like_from_search_query(".prt$") == "%.prt"
    assert sql_like_from_search_query("^shaft.prt$") == "shaft.prt"
    assert sql_like_from_search_query("^CAD/*.prt") == "CAD/%.prt"
    assert sql_like_from_search_query("^") is None
    assert sql_like_from_search_query("$") is None
    assert sql_like_from_search_query("^$") is None


def test_blank_query_is_none():
    assert sql_like_from_search_query("") is None
    assert sql_like_from_search_query("   ") is None
    assert sql_like_from_search_query(None) is None


# --------------------------------------------------------------------------- field terms
from types import SimpleNamespace

from creopdm.utils.search_query import (
    SearchTerm,
    object_matches_search,
    object_search_fields,
    parse_search_query,
    split_search_terms,
    text_matches,
)


def test_terms_split_on_spaces_and_quotes_keep_them():
    assert split_search_terms('type=bulk  name="my part" shaft') == ["type=bulk", "name=my part", "shaft"]
    assert split_search_terms('"my part"') == ["my part"]
    assert split_search_terms("   ") == []


def test_field_terms_and_plain_terms():
    terms = parse_search_query('type=bulk param.MATERIAL=steel* foo=bar sec type= name="my part"')
    assert terms == [
        SearchTerm(field="type", value="bulk"),
        SearchTerm(field="param", value="steel*", param_name="MATERIAL"),
        SearchTerm(field=None, value="foo=bar"),  # unknown field: plain text
        SearchTerm(field=None, value="sec"),
        SearchTerm(field="name", value="my part"),  # `type=` with no value is ignored
    ]


def test_text_matches_exact_partial_and_anchors():
    assert text_matches("BULK", "bulk", exact=True)
    assert not text_matches("BULKY", "bulk", exact=True)
    assert text_matches("BULKY", "bul*", exact=True)
    assert text_matches("shaft.prt", "*.prt", exact=True)
    assert text_matches("shaft.prt", "sha", exact=False)  # plain text: substring
    assert text_matches("shaft.prt", "^sha", exact=False) and not text_matches("shaft.prt", "^haft", exact=False)
    assert text_matches("shaft.prt", ".prt$", exact=False)


def _obj(**kw):
    version = SimpleNamespace(
        identity_json=kw.pop("identity_json", None), creo_release=kw.pop("creo_release", None)
    )
    base = dict(
        filename="1s0122.prt", name="1s0122", number="N-1", relative_path="A/1s0122.prt",
        lifecycle_state="IN_WORK", revision="A", iteration=2, current_version=version,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_object_search_fields_and_matching():
    obj = _obj(identity_json='{"model_type": "PART", "subtype": "BULK"}', creo_release="13.4.1.0")
    fields = object_search_fields(obj, "BULK")
    assert fields["subtype"] == ["BULK"] and fields["model"] == ["PART"] and fields["type"] == ["BULK"]
    assert fields["rev"] == ["A", "A.2"] and "In Work" .lower() in [s.lower() for s in fields["state"]]

    def hit(query, params=None):
        return object_matches_search(parse_search_query(query), fields, params)

    assert hit("type=bulk subtype=bulk model=part rev=A.2 creo=13.4.1.0 state=in_work number=n-1")
    assert hit("bulk") and hit("N-1") and hit("1s01")
    assert not hit("type=part")
    assert not hit("sec")
    assert hit("param.MATERIAL=steel*", {"MATERIAL": "STEEL_1018"})
    assert not hit("param.MATERIAL=steel*", {"COLOR": "red"}) and not hit("param.MATERIAL=steel*")
