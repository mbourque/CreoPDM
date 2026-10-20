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


def test_no_page_template_prints_a_timestamp_field_without_the_date_filters():
    """Every {{ ... }} that prints a timestamp goes through local_time / local_time_pretty."""
    import re

    templates = ROOT / "src" / "creopdm" / "templates"
    field = re.compile(r"(_at|_since|timestamp|checkout_since|released|finalized)\b")
    offenders = []
    for path in templates.rglob("*.html"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # a cell that prints the short stamp but carries the pretty hover on the same line is fine
            if "local_time_pretty" in line:
                continue
            for expr in re.findall(r"\{\{(.*?)\}\}", line):
                if field.search(expr) and "local_time" not in expr and "|" not in expr:
                    offenders.append(f"{path.name}:{number}: {expr.strip()}")
    assert offenders == [], offenders


def test_the_baseline_header_lines_carry_the_pretty_hover_for_their_date():
    module = _read("baselines.js")
    assert "meta.title = prettyWhen(browseInfo.created_at);" in module  # the banner over the file list
    assert "meta.title = prettyWhen(info.created_at);" in module  # the baseline window's header
