"""Unit tests for Search box glob → SQL ILIKE conversion."""

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


def test_blank_query_is_none():
    assert sql_like_from_search_query("") is None
    assert sql_like_from_search_query("   ") is None
    assert sql_like_from_search_query(None) is None
