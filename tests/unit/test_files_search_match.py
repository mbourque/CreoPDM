"""Navigator and Files share files_search_match.js for Search matching."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "src/creopdm/static/js/files_search_match.js"
BASE_HTML = ROOT / "src/creopdm/templates/base.html"
EMBED_HTML = ROOT / "src/creopdm/templates/embed_explorer.html"
APP_JS = ROOT / "src/creopdm/static/js/app.js"
EMBED_JS = ROOT / "src/creopdm/static/js/embed_explorer.js"


def _run_node(harness: str) -> object:
    if not shutil.which("node"):
        pytest.skip("node not on PATH")
    result = subprocess.run(
        ["node", "-e", harness],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout.strip() or "null")


def test_files_search_match_loaded_by_files_and_navigator():
    assert "files_search_match.js" in BASE_HTML.read_text(encoding="utf-8")
    assert "files_search_match.js" in EMBED_HTML.read_text(encoding="utf-8")
    app = APP_JS.read_text(encoding="utf-8")
    assert "CreoPdmFilesSearchMatch" in app
    assert "function parseSearchAnchors" not in app
    assert "function globToRegExp" not in app
    embed = EMBED_JS.read_text(encoding="utf-8")
    assert "objectMatchesSearchQuery" in embed
    assert "hay.indexOf(q)" not in embed
    shared = SCRIPT.read_text(encoding="utf-8")
    assert "function parseSearchAnchors" in shared
    assert "function globToRegExp" in shared
    assert "function fieldsMatchSearchQuery" in shared
    assert "function rowMatchesSearchQuery" in shared
    assert "function objectMatchesSearchQuery" in shared


def test_files_search_match_node_globs_and_anchors():
    """Node: *.prt / ^CAD/ / .prt$ match the same as Files product Search."""
    script_path = json.dumps(str(SCRIPT))
    harness = f"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync({script_path}, "utf8");
const sandbox = {{ console }};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const api = sandbox.CreoPdmFilesSearchMatch;
const objs = [
  {{ filename: "shaft.prt", relative_path: "CAD/shaft.prt", type_label: "PART", object_type: "PART" }},
  {{ filename: "notes.txt", relative_path: "docs/notes.txt", type_label: "Document", object_type: "DOCUMENT" }},
  {{ filename: "bracket.prt", relative_path: "CAD/bracket.prt", type_label: "SHEETMETAL", object_type: "PART" }},
];
const hit = (q) => objs.filter((o) => api.objectMatchesSearchQuery(o, q)).map((o) => o.relative_path);
process.stdout.write(JSON.stringify({{
  prt: hit("*.prt"),
  cad: hit("^CAD/"),
  ends: hit(".prt$"),
  sheet: hit("SHEETMETAL"),
  substr: hit("shaft"),
  empty: hit(""),
}}));
"""
    payload = _run_node(harness)
    assert payload["prt"] == ["CAD/shaft.prt", "CAD/bracket.prt"]
    assert payload["cad"] == ["CAD/shaft.prt", "CAD/bracket.prt"]
    assert payload["ends"] == ["CAD/shaft.prt", "CAD/bracket.prt"]
    assert payload["sheet"] == ["CAD/bracket.prt"]
    assert payload["substr"] == ["CAD/shaft.prt"]
    assert payload["empty"] == [
        "CAD/shaft.prt",
        "docs/notes.txt",
        "CAD/bracket.prt",
    ]


def test_files_search_match_node_field_terms():
    """Node: type=bulk / subtype=bulk / quotes / wildcards behave like the server Search."""
    script_path = json.dumps(str(SCRIPT))
    harness = f"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync({script_path}, "utf8");
const sandbox = {{ console }};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const api = sandbox.CreoPdmFilesSearchMatch;
const bulk = {{ filename: "1s0122.prt", relative_path: "A/1s0122.prt", type_label: "BULK", model_role: "BULK",
  model_type: "PART", lifecycle_state: "IN_WORK", display_revision: "A.2", creo_release: "13.4.1.0", number: "N-1" }};
const hit = (q) => api.objectMatchesSearchQuery(bulk, q);
process.stdout.write(JSON.stringify({{
  typeBulk: hit("type=bulk"),
  subBulk: hit("subtype=bulk"),
  typePartial: hit("type=bul"),
  typeStar: hit("type=bul*"),
  all: hit("type=bulk subtype=bulk model=part rev=A.2 state=in_work creo=13.4.1.0 number=n-1"),
  quoted: hit('name="1s0122.prt"'),
  plainType: hit("bulk"),
  plainMetadata: hit("sec"),
  paramNoData: hit("param.MATERIAL=steel*"),
  unknownField: hit("foo=bar"),
  emptyValue: hit("type="),
  terms: api.parseSearchQuery('type=bulk param.X=1 name="a b" plain'),
}}));
"""
    payload = _run_node(harness)
    assert payload["typeBulk"] and payload["subBulk"] and payload["typeStar"] and payload["all"]
    assert payload["quoted"] and payload["plainType"] and payload["emptyValue"]
    assert not payload["typePartial"]  # `=` is exact
    assert not payload["plainMetadata"]  # plain text is names and types only
    assert payload["paramNoData"]  # the page carries no parameters: the server decides
    assert not payload["unknownField"]  # an unknown field is plain text, which matches nothing here
    assert [t["field"] for t in payload["terms"]] == ["type", "param", "name", None]
    assert payload["terms"][1]["paramName"] == "X" and payload["terms"][2]["value"] == "a b"


def test_the_search_tooltip_has_the_bulk_and_parameter_examples_in_both_search_boxes():
    for html in (
        ROOT / "src/creopdm/templates/app.html",
        EMBED_HTML,
    ):
        text = html.read_text(encoding="utf-8")
        box = text.split('type="search"', 1)[1].split("autocomplete", 1)[0]
        assert "type=bulk" in box and "param.MATERIAL=steel*" in box, html.name
    app = (ROOT / "src/creopdm/utils/file_rows_html.py").read_text(encoding="utf-8")  # the Python row builder
    for attr in ("data-subtype=", "data-model=", "data-lifecycle=", "data-rev=", "data-creo=", "data-number="):
        assert attr in app
    assert 'data-subtype="${escapeHtml(obj.model_role' in APP_JS.read_text(encoding="utf-8")
