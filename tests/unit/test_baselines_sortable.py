"""Baseline contents: the Files, Structure and Compare columns sort when clicked."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def test_every_column_of_the_three_tables_is_a_sortable_header():
    template = _read("src", "creopdm", "templates", "app.html")
    for table, keys in (
        ("baseline-members-table", ("name", "rev", "state", "type", "now")),
        ("baseline-structure-table", ("parent", "uses", "type", "qty", "resolved")),
        ("baseline-compare-table", ("name", "change", "mine", "other")),
    ):
        head = template[template.index(f'id="{table}"') :]
        head = head[: head.index("</thead>")]
        assert len(re.findall(r"<th[ >]", head)) == len(keys), table
        for key in keys:
            assert f'data-sort="{key}"' in head, (table, key)


def test_sorting_is_done_on_the_loaded_rows_with_a_stable_version_aware_sort():
    module = _read("src", "creopdm", "static", "js", "baselines.js")
    # one click handler for all three tables, mapped by table id
    assert 'closest("th[data-sort]")' in module and "SORT_TABLE_IDS" in module
    # click again reverses; a new column starts ascending
    assert "{ key, dir: -current.dir } : { key, dir: 1 }" in module
    # revisions compare by letters then number (A.2 < A.10 < B.1), empty versions last
    assert "function compareVersions" in module and "Intl.Collator" in module and "numeric: true" in module
    # each table paints from its stored rows through sortedRows, so no new request is made
    assert 'sortedRows("files", filesData)' in module
    assert 'sortedRows("structure", structureData)' in module
    assert '"compare",\n        compareResult.items.filter' in module
    # a fresh open starts in the server order again
    assert "resetSorts();" in module


def test_the_sorted_column_shows_an_arrow():
    css = _read("src", "creopdm", "static", "css", "app.css")
    assert '#baseline-members-dialog th[aria-sort="ascending"]::after' in css
    assert '#baseline-members-dialog th[aria-sort="descending"]::after' in css
    assert "th[data-sort] { cursor: pointer;" in css
