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


def test_add_paths_sends_purgeable_extensions():
    """Regression: agent omit-older-saves must use Settings → Purgeable extensions."""
    script = _app_js()
    assert "purgeable_extensions: [...purgeableExtensionSet()]" in script
    assert "function purgeableExtensionSet" in script
    pick_folder = _between(
        script,
        "async function browseViaAgentFolderPicker(",
        '$("#choose-workspace-files")?.addEventListener("click"',
    )
    assert "purgeable_extensions" in pick_folder
    add_chunk = _between(
        script,
        "if (chosenAgentPaths.length)",
        "if (chosenUploads.length)",
    )
    assert "purgeable_extensions" in add_chunk
    assert "importExtensionSet" in script
    # logicalUploadName must not strip .N from non-purgeable names (e.g. .snagx.1).
    logical = _between(script, "function logicalUploadName(", "function purgeableExtensionSet(")
    assert "isImportVersionedExtension" in logical


def test_agent_add_chunks_continue_after_http_error():
    """Regression: one failed /add-paths batch used to abort the rest of a large folder add."""
    script = _app_js()
    start = script.index("if (chosenAgentPaths.length)")
    end = script.index("if (chosenUploads.length)", start)
    body = script[start:end]
    assert "continue;" in body
    assert "return combined.ok.length ? combined : null;" not in body
    assert "Keep going" in body or "must not drop" in body
    assert "addInFlight" in _app_js()
    assert "client_offset" in body


def test_add_partial_failure_notice_survives_reload():
    """Regression: partial add errors were wiped by reloadPage before the user saw them."""
    script = _app_js()
    assert 'sessionStorage.setItem("creopdmNotice"' in script
    assert "summarizeAddFailures" in script
    assert "See creopdm-agent log" in script


def test_dropped_folder_keeps_nested_relative_paths():
    """Disk .path must not flatten a walked folder tree (subfolders would be lost)."""
    script = _app_js()
    body = _between(script, "function applyDroppedFiles(", "function applyBrowserPickedFiles(")
    assert "nestedUploads" in body
    assert "commonParentDir" in script
    assert 'String(item.relativePath || "").includes("/")' in body
    # Nested browser paths win over absolute disk paths.
    assert body.index("nestedUploads") < body.index("uniquePaths")


def test_project_dialog_has_vault_folder_and_use_hash():
    html = APP_HTML.read_text(encoding="utf-8")
    assert "Vault/Workspace name" in html
    assert 'id="project-use-hash"' in html
    assert 'name="vault_folder"' in html
    assert 'class="checkbox-row"' in html
    assert 'for="project-use-hash"' in html
    # Use hash is the default — uncheck to type a custom vault folder.
    assert 'id="project-use-hash" checked' in html
    assert "data-vault-folder=" in html
    script = _app_js()
    assert "syncProjectVaultFolderField" in script
    assert "currentVaultFolder" in script
    assert "vault_folder: currentVaultFolder()" in script
    assert "slugifyVaultFolder" in script
    assert ".toLowerCase()" in _between(script, "function slugifyVaultFolder(", "function fillVaultFolderFromName(")
    assert "Enter a vault/workspace name, or check Use hash." in script
    assert "if (!vaultFolder) vaultFolder = slugifyVaultFolder(body.name)" not in script
    assert "Vault/workspace name cannot contain spaces" in script
    assert "getRandomValues" in script
    assert "proj-${" not in script
    css = APP_CSS.read_text(encoding="utf-8")
    assert ".project-vault-fields .checkbox-row" in css
    assert "flex-direction: row" in css.split(".project-vault-fields .checkbox-row", 1)[1].split("}", 1)[0]


def test_delete_project_dialog_offers_local_workspace_checkbox():
    html = APP_HTML.read_text(encoding="utf-8")
    assert 'id="delete-local-workspace" checked' in html
    assert "Also delete local workspace on this PC" in html
    script = _app_js()
    assert "/delete-project-cache" in script
    assert "delete-local-workspace" in script


def test_soft_nav_does_not_silently_drop_when_busy():
    """Regression: soft-nav busy used to no-op or hard-reload (SSR Not Connected flash)."""
    body = _between(_app_js(), "function softNavigate(", "function leavePage(")
    assert "__creopdmSoftNavBusy" in body
    assert "softNavQueued" in body
    assert "Never hard-reload list home" in body or "never hard-reload" in body.lower()
    # Busy path must queue — not location.href for list home.
    busy = body.split("if (window.__creopdmSoftNavBusy || softNavBusy)")[1].split("softNavBusy = true")[0]
    assert "softNavQueued" in busy
    assert "window.location.href" not in busy
    assert "window.__creopdmBoot({ soft: true })" in body


def test_soft_nav_skips_creojs_reconnect():
    """Regression: folder/project soft nav used to re-probe Creo.JS and flash offline.

    Soft switches only replace main.shell; the status pill and Creo.JS bridge live
    outside it and must stay connected — including when changing projects.
    Hard reload SSR-paints Not Connected and drops the live bridge.
    """
    script = _app_js()
    base = (ROOT / "src" / "creopdm" / "templates" / "base.html").read_text(encoding="utf-8")

    # Pill / status cluster sit outside the soft-swapped shell.
    assert 'id="creo-status"' in base
    assert base.index("status-cluster") < base.index('<main class="shell">')
    assert base.index('id="creo-status"') < base.index('<main class="shell">')

    # Soft navigate rebinds UI only — never a full reload for list home URLs.
    soft_nav = _between(script, "function softNavigate(", "function leavePage(")
    assert "window.__creopdmBoot({ soft: true })" in soft_nav
    assert "Keep the live Creo.JS bridge" in soft_nav
    assert "softNavQueued" in soft_nav

    # leavePage always soft-navs list home (no inCreoBrowser gate — false negatives
    # caused hard reloads that flashed Not Connected).
    leave = _between(script, "function leavePage(", "function reloadPage(")
    assert "isListHomeUrl(url)" in leave
    assert "softNavigate" in leave
    assert "inCreoBrowser()" not in leave

    # Project, folder crumb, brand, and folder-open clicks soft-navigate.
    assert "a.project-item, nav.folder-crumb a, a.brand, a.folder-open" in script
    assert 'softNavigate(href, "push")' in script
    assert "Do not gate on inCreoBrowser" in script

    # Soft boot: toolbar sync only — no agent probe, no bridge reconnect poll.
    assert "syncCreoSessionControlsFromBridge" in script
    assert "Do not probe or touch the pill" in script
    assert "Never re-probe agent or reconnect" in script
    block = script.split("function showCreoSessionControls(")[1].split("async function agentWorkdir(")[0]
    assert "if (soft)" in block
    soft_branch = block.split("if (soft)")[1].split("} else {")[0]
    assert "syncCreoSessionControlsFromBridge()" in soft_branch
    assert "probeCreoAgent" not in soft_branch
    assert "bridgePoll" not in soft_branch
    assert "refreshCreoStatusPill" not in soft_branch
    assert "creoJSReady.then" not in soft_branch

    # Status poll must survive soft boots and skip updates while soft-nav busy.
    assert "__creopdmStatusPollId" in block
    assert "Survive soft folder/project boots" in block
    assert "__creopdmSoftNavBusy" in script.split("window.__creopdmStatusPollId")[1].split("}, interval)")[0]

    # Pill refresh must not flash Session offline during soft nav / bridge flake.
    pill_fn = _between(script, "async function refreshCreoStatusPill(", "function showCreoSessionControls(")
    assert "__creopdmSoftNavBusy" in pill_fn
    assert "Transient bridge flake" in pill_fn
    assert "Session offline" in pill_fn


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


def test_folder_row_click_selects_link_opens():
    """Regression: row click selects for Remove; only the folder name link navigates."""
    script = _app_js()
    body = _between(script, "function onFileTableClick(", "function onFileTableDblclick(")
    assert "Folder name link opens" in body or "anywhere else on the row only selects" in body
    assert "openFolderRow(folderRow)" in body
    assert "selectOnly(folderRow)" in body
    assert 'closest?.("a.folder-open, button.folder-open")' in body
    assert body.index("openFolderRow(folderRow)") < body.index("selectOnly(folderRow)")
    assert 'closest(".object-row, .queue-row")' in body
    css = APP_CSS.read_text(encoding="utf-8")
    assert "cursor: default" in css.split(".folder-row {", 1)[1].split("}", 1)[0]
    assert "width: fit-content" in css


def test_newer_local_cache_matches_flat_save_for_nested_vault_path():
    """Regression: agent cache is flat; vault may be Documents/part.prt.1 while Creo
    saves part.prt.2 at the cache root — full-path-only matching hid Modified/Check In.
    """
    script = _app_js()
    body = _between(script, "function newerLocalCacheSaves(", "async function countLocalNewWorkspaceFiles(")
    assert "bestByBasename" in body
    assert "vaultBasenameCounts" in body
    assert "vaultBasenameCounts.get(base) || 0) === 1" in body
    assert "Agent cache is flat" in body


def test_newer_local_cache_matches_flat_save_for_nested_vault_path():
    """Regression: agent cache is flat; vault may be Documents/part.prt.1 while Creo
    saves part.prt.2 at the cache root — full-path-only matching hid Modified/Check In.
    """
    script = _app_js()
    body = _between(script, "function newerLocalCacheSaves(", "async function countLocalNewWorkspaceFiles(")
    assert "bestByBasename" in body
    assert "vaultBasenameCounts" in body
    assert "vaultBasenameCounts.get(base) || 0) === 1" in body
    assert "Agent cache is flat" in body
