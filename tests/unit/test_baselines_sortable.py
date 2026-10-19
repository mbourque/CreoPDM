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
        ("baselines-table", ("name", "type", "status", "members", "created", "by")),  # the tab's list
        ("baseline-members-table", ("name", "rev", "state", "type", "now")),
        ("baseline-structure-table", ("parent", "uses", "type", "qty", "resolved")),
        ("baseline-compare-table", ("name", "change", "mine", "other")),
    ):
        head = template[template.index(f'id="{table}"') :]
        head = head[: head.index("</thead>")]
        # the product list also has one unsortable column: the Details… buttons
        extra = 1 if table == "baselines-table" else 0
        assert len(re.findall(r"<th[ >]", head)) == len(keys) + extra, table
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
    assert 'renderRows(sortedRows("baselines", list))' in module  # the product's list of baselines
    assert 'sortedRows("files", filesData)' in module
    assert 'sortedRows("structure", structureData)' in module
    assert '"compare",\n        compareResult.items.filter' in module
    # a fresh open starts in the server order again
    assert "resetSorts();" in module


def test_the_admin_baselines_list_sorts_too_with_the_worst_integrity_first():
    template = _read("src", "creopdm", "templates", "admin_baselines.html")
    head = template[template.index('id="baseline-admin-table"') :]
    head = head[: head.index("</thead>")]
    for key in ("product", "name", "type", "status", "members", "created", "by", "integrity"):
        assert f'data-sort="{key}"' in head, key
    assert "<th>Actions</th>" in head  # the buttons column is not a sort column
    script = _read("src", "creopdm", "static", "js", "admin_baselines.js")
    assert 'closest("th[data-sort]")' in script and "{ key, dir: -sort.dir } : { key, dir: 1 }" in script
    assert "HEALTH_ORDER = { ERROR: 0, WARNING: 1, HEALTHY: 2 }" in script
    # the filter pills and the sort work together: sort the rows that are shown
    assert "const shown = sortedItems(" in script
    css = _read("src", "creopdm", "static", "css", "app.css")
    assert '#baseline-admin-table th[aria-sort="ascending"]::after' in css


def test_the_sorted_column_shows_an_arrow():
    css = _read("src", "creopdm", "static", "css", "app.css")
    assert '#baseline-members-dialog th[aria-sort="ascending"]::after' in css
    assert '#baseline-members-dialog th[aria-sort="descending"]::after' in css
    assert '#baselines-table th[aria-sort="ascending"]::after' in css  # the tab's own list
    assert "th[data-sort] { cursor: pointer;" in css
