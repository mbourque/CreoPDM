"""Regression guards for list UI, Add Folder, icons, and app.js boot.

These catch failures that wiped click handlers (syntax), blocked folder pick on
LAN http, or mismatched filetype icon sizes — without needing a browser.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "creopdm" / "static" / "js" / "app.js"
APP_CSS = ROOT / "src" / "creopdm" / "static" / "css" / "app.css"
APP_HTML = ROOT / "src" / "creopdm" / "templates" / "app.html"
ICONS = ROOT / "src" / "creopdm" / "static" / "icons"


def _app_js() -> str:
    return APP_JS.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str) -> str:
    assert start in text, f"missing marker {start!r}"
    chunk = text.split(start, 1)[1]
    assert end in chunk, f"missing end marker {end!r} after {start!r}"
    return chunk.split(end, 1)[0]


def test_app_js_has_no_syntax_error_via_node():
    """The `if label ||` typo killed the entire script — nothing was clickable."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    result = subprocess.run(
        [node, "--check", str(APP_JS)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_resolve_type_icon_if_conditions_use_parens():
    """Bare `if label` is a SyntaxError; keep parentheses on resolveTypeIcon guards."""
    body = _between(_app_js(), "function resolveTypeIcon(", "function typeIconHtml(")
    bare = re.findall(r"\bif\s+[a-zA-Z_]\w*\s*\|\|", body)
    assert not bare, f"resolveTypeIcon has bare if without (: {bare}"
    assert "if (label || ext || objectType)" in body


def test_choose_folder_uses_agent_before_browser_picker():
    """LAN http:// cannot use showDirectoryPicker; agent native folder pick must run first."""
    script = _app_js()
    assert "function browseViaAgentFolderPicker" in script
    assert "/pick-folder" in script
    folder_click = _between(
        script,
        '$("#choose-workspace-folder")?.addEventListener("click"',
        "async function handleDroppedTransfer",
    )
    assert "browseViaAgentFolderPicker" in folder_click
    assert folder_click.index("browseViaAgentFolderPicker") < folder_click.index("browseLocalFolder")
    assert "useNativePicker()" in folder_click


def test_choose_files_still_prefers_agent_picker():
    files_click = _between(
        _app_js(),
        '$("#choose-workspace-files")?.addEventListener("click"',
        '$("#choose-workspace-folder")?.addEventListener("click"',
    )
    assert "browseViaAgentPicker" in files_click
    assert files_click.index("browseViaAgentPicker") < files_click.index("browseLocalFiles")


def test_browser_folder_pick_explains_secure_context():
    script = _app_js()
    body = _between(script, "async function browseLocalFolder(", "function bindDropTarget(")
    assert "canUseDirectoryPicker" in body
    assert "isSecureContext" in script
    assert "Folder pick needs https://" in body
    assert "Drag the folder onto the drop zone" in body


def test_add_paths_sends_agent_base_folder():
    script = _app_js()
    assert "chosenAgentBaseFolder" in script
    assert "base_folder: chosenAgentBaseFolder" in script
    assert "applyAgentPickedPaths(paths, folder)" in script


def test_soft_nav_does_not_silently_drop_when_busy():
    """Regression: soft-nav busy used to no-op folder/project clicks."""
    body = _between(_app_js(), "function softNavigate(", "function leavePage(")
    assert "__creopdmSoftNavBusy" in body
    assert "window.location.href = absolute.href" in body
    assert "Never silently drop" in body or "already in flight" in body
    assert "window.__creopdmBoot({ soft: true })" in body


def test_new_project_and_sidebar_collapse_handlers_present():
    script = _app_js()
    assert '$("#new-project-btn")?.addEventListener("click"' in script
    assert "showProjectDialog(\"create\")" in script or 'showProjectDialog("create")' in script
    assert "sidebarCollapseBtn?.addEventListener(\"click\"" in script
    assert "is-sidebar-collapsed" in script
    assert 'id="new-project-btn"' in APP_HTML.read_text(encoding="utf-8")
    assert 'id="sidebar-collapse-btn"' in APP_HTML.read_text(encoding="utf-8")


def test_type_icon_css_svg_larger_than_png():
    """Solid Creo PNGs look heavier; SVGs are drawn slightly larger for optical match."""
    css = APP_CSS.read_text(encoding="utf-8")
    assert ".type-icon {" in css
    base = _between(css, ".type-icon {", "}")
    assert "width: 14px" in base
    assert "height: 14px" in base
    assert "img.type-icon[src$=\".svg\"]" in css
    svg = css.split("img.type-icon[src$=\".svg\"]", 1)[1]
    svg_rule = svg.split("{", 1)[1].split("}", 1)[0]
    assert "width: 16px" in svg_rule
    assert "height: 16px" in svg_rule


def test_creo_and_filetype_icons_exist_on_disk():
    for name in ("part.png", "assembly.png", "drawing.png", "pdf.svg", "word.svg", "text.svg", "json.svg"):
        path = ICONS / name
        assert path.is_file(), path
        assert path.stat().st_size > 20


def test_normalize_type_icons_script_restores_viewbox():
    path = ROOT / "scripts" / "normalize_type_icons.py"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "restore_viewbox" in text or "PREV_FILL" in text
    assert "0.84" in text
