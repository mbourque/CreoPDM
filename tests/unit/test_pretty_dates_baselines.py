"""Dates on the baseline pages use the app's date format, never a raw ISO string or a locale date."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "src" / "creopdm" / "static" / "js"


def _read(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8")


def test_the_baseline_list_hover_is_the_pretty_date():
    module = _read("baselines.js")
    assert 'title="${esc(prettyWhen(item.created_at))}"' in module
    # no raw ISO value is ever put in a title again
    assert 'title="${esc(item.created_at' not in module
    assert "shell.formatStampPretty" in module and "shell.formatStamp" in module
    # one date function for the app: no private copy of the formatting
    assert "getFullYear()" not in module


def test_the_admin_baselines_page_uses_the_same_dates():
    admin = _read("admin_baselines.js")
    assert 'title="${esc(prettyWhen(item.created_at))}"' in admin and 'title="${esc(item.created_at' not in admin
    assert "toLocaleDateString" not in admin and "toLocaleString" not in admin
    assert "checked ${when(report.checked_at)}" in admin


def test_the_shell_shares_the_apps_date_helpers_and_nothing_else_prints_raw_stamps():
    app = _read("app.js")
    assert "    formatStamp,\n    formatStampPretty," in app.replace("\r\n", "\n")
    # across every client script: no title attribute carries a raw timestamp field
    import re

    for path in JS.glob("*.js"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r'title="\$\{esc\([a-z.]*(created_at|updated_at|released_at|finalized_at)( \|\| "")?\)\}"', text), path.name
