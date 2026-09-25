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


def test_add_toolbar_is_menu_with_modes():
    """Add ▾ exposes files / folders / folder / Create folder like Checkout/Check In."""
    html = APP_HTML.read_text(encoding="utf-8")
    assert 'id="add-menu"' in html
    assert "Add ▾" in html
    assert 'id="add-files-btn"' in html
    assert 'id="add-folders-btn"' in html
    assert 'id="add-folder-btn"' in html
    assert 'id="create-folder-btn"' in html
    assert 'id="create-folder-dialog"' in html
    script = _app_js()
    assert 'openAddDialog("files")' in script
    assert 'openAddDialog("folders")' in script
    assert 'openAddDialog("folder")' in script
    assert "recursive" in script
    assert "/api/projects/${projectId}/folders" in script or '/api/projects/${projectId}/folders' in script


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
    assert "base_folder: baseFolder || \"\"" in script
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
    assert "recursive" in pick_folder
    add_chunk = _between(
        script,
        "async function addAgentPathChunks(",
        "if (chosenAgentFolderBatches.length)",
    )
    assert "purgeable_extensions" in add_chunk
    assert "importExtensionSet" in script
    # logicalUploadName must not strip .N from non-purgeable names (e.g. .snagx.1).
    logical = _between(script, "function logicalUploadName(", "function purgeableExtensionSet(")
    assert "isImportVersionedExtension" in logical


def test_agent_add_chunks_continue_after_http_error():
    """Regression: one failed /add-paths batch used to abort the rest of a large folder add."""
    script = _app_js()
    start = script.index("async function addAgentPathChunks(")
    end = script.index("if (chosenAgentFolderBatches.length)", start)
    body = script[start:end]
    assert "continue;" in body
    assert "return combined.ok.length ? combined : null;" not in body
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
    assert "never hard-reload" in body.lower()
    # Busy path must queue — not location.href for soft-nav pages.
    busy = body.split("if (window.__creopdmSoftNavBusy || softNavBusy)")[1].split("softNavBusy = true")[0]
    assert "softNavQueued" in busy
    assert "window.location.href" not in busy
    assert "window.__creopdmBoot({ soft: true })" in body


def test_soft_nav_skips_creojs_reconnect():
    """Regression: shell soft nav used to re-probe Creo.JS and flash offline.

    Soft switches only replace main.shell; the status pill and Creo.JS bridge live
    outside it and must stay connected — including folders, projects, and Settings.
    Hard reload SSR-paints Not Connected and drops the live bridge.
    """
    script = _app_js()
    base = (ROOT / "src" / "creopdm" / "templates" / "base.html").read_text(encoding="utf-8")

    # Pill / status cluster sit outside the soft-swapped shell.
    assert 'id="creo-status"' in base
    assert base.index("status-cluster") < base.index('<main class="shell">')
    assert base.index('id="creo-status"') < base.index('<main class="shell">')
    assert 'href="/settings"' in base

    # Soft-nav covers list home, settings, and object detail (not Settings-only hard load).
    soft_fn = _between(script, "function isSoftNavUrl(", "let softNavBusy")
    assert 'path === "/settings"' in soft_fn
    assert 'path === "/settings/types"' in soft_fn
    assert "/projects/" in soft_fn or r"/projects\/" in soft_fn
    assert "objects" in soft_fn
    soft_nav = _between(script, "function softNavigate(", "function leavePage(")
    assert "window.__creopdmBoot({ soft: true })" in soft_nav
    assert "Keep the live Creo.JS bridge" in soft_nav
    assert "softNavQueued" in soft_nav
    assert "isSoftNavUrl" in soft_nav

    leave = _between(script, "function leavePage(", "function reloadPage(")
    assert "isSoftNavUrl(url)" in leave
    assert "softNavigate" in leave
    assert "inCreoBrowser()" not in leave

    # Any same-origin soft-nav <a href> (Settings pill, crumbs, folders, …).
    assert 'closest("a[href]")' in script
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
    poll_cb = script.split("window.__creopdmStatusPollId = window.setInterval(")[1].split("}, interval)")[0]
    assert "__creopdmSoftNavBusy" in poll_cb

    # Pill refresh must not flash Session offline during soft nav / bridge flake.
    pill_fn = _between(script, "async function refreshCreoStatusPill(", "function showCreoSessionControls(")
    assert "__creopdmSoftNavBusy" in pill_fn
    assert "Transient bridge flake" in pill_fn
    assert "Session offline" in pill_fn


def test_checkout_checkin_toolbar_menus_and_open_wd():
    """Checkout/Check In fly-up menus and open-dialog Set working directory."""
    html = APP_HTML.read_text(encoding="utf-8")
    base = (ROOT / "src" / "creopdm" / "templates" / "base.html").read_text(encoding="utf-8")
    script = _app_js()
    assert 'id="checkout-menu"' in html
    assert 'id="checkout-project-btn"' in html
    assert "Checkout project" in html
    assert 'id="undo-btn"' in html
    assert html.index('id="checkout-menu"') < html.index('id="undo-btn"')
    assert html.index('id="undo-btn"') < html.index('id="checkin-menu"')
    assert 'id="checkin-menu"' in html
    assert 'id="checkin-project-btn"' in html
    assert "Check in project" in html
    assert "function beginCheckin" in script
    assert 'beginCheckin("project")' in script
    assert "function runCheckoutObjects" in script
    assert "pendingProjectSaves" in script
    assert "projectCheckoutCount" in script
    assert "pendingProjectSaves > 0 || pendingProjectNew > 0 || projectCheckoutCount > 0" in script
    assert "Nothing to check in for this project" in script
    assert "data-checkoutable" in html
    assert "setCheckoutableCount" in script
    assert "canCheckoutProject" in script
    assert "Nothing left to check out in this project" in script
    assert "pushLocalNewPathsToVault" in script
    assert "localOnlyCacheFiles" in _between(script, "async function beginCheckin(", "$(\"#checkin-cancel\")")
    assert "Preview is vault-only" in script
    assert "undoIds" in script
    assert "Releasing unchanged checkouts" in script
    assert "Undo checkout on" in script
    assert 'id="open-checkout-set-wd"' in base
    assert "Set Creo working directory" in base
    assert "open-checkout-set-wd" in script
    assert "setWorkingDirectory" in _between(
        script, "async function openPdmObjectFromUi(", "function agentBase("
    )


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
