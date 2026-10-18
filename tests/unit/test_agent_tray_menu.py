"""The tray agent has a menu entry that opens CreoPDM as a web page."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_tray_menu_opens_creopdm_in_the_browser():
    tray = (ROOT / "src" / "creopdm_agent" / "tray.py").read_text(encoding="utf-8")
    assert 'Item("Open CreoPDM in browser", on_open_creopdm, default=True)' in tray
    body = tray.split("def on_open_creopdm(", 1)[1].split("def on_open_cache(", 1)[0]
    assert "settings.pdm_url" in body  # read at click time, after Settings changes
    assert "webbrowser.open(url)" in body
    assert "not set yet" in body  # an unset address is explained, not a silent no-op
    # first actionable entry in the menu
    assert tray.index("Open CreoPDM in browser") < tray.index('Item("Show status"')
