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
    """Add ▾: Create folder…, Add files…, Add folder…, Add folders…"""
    html = APP_HTML.read_text(encoding="utf-8")
    assert 'id="add-menu"' in html
    assert "Add ▾" in html
    assert 'id="create-folder-btn"' in html
    assert 'id="add-files-btn"' in html
    assert 'id="add-folder-btn"' in html
    assert 'id="add-folders-btn"' in html
    assert html.index('id="create-folder-btn"') < html.index('id="add-files-btn"')
    assert html.index('id="add-files-btn"') < html.index('id="add-folder-btn"')
    assert html.index('id="add-folder-btn"') < html.index('id="add-folders-btn"')
    assert ">Create folder…<" in html
    assert ">Add files…<" in html
    assert ">Add folder…<" in html
    assert ">Add folders…<" in html
    assert 'id="create-folder-dialog"' in html
    script = _app_js()
    assert 'openAddDialog("files")' in script
    assert 'openAddDialog("folders")' in script
    assert 'openAddDialog("folder")' in script
    assert "recursive" in script
    assert "/api/projects/${projectId}/folders" in script or '/api/projects/${projectId}/folders' in script


def test_remove_from_project_sends_folder_paths():
    """Regression: Create/Add folder rows may lack data-object-ids; remove by path."""
    script = _app_js()
    assert "function selectedFolderPaths" in script
    assert "folder_paths: folderPaths" in script
    remove = _between(
        script,
        "removeBtn?.addEventListener(\"click\"",
        "async function loadChangesTab",
    )
    assert "selectedFolderPaths()" in remove
    assert "folder_paths" in remove
    assert "canRemoveProject = ids.length > 0 || folderPaths.length > 0" in script


def test_remove_rows_update_folder_tbody_cache_and_soft_reload():
    """Regression: folder stayed visible after remove until hard refresh.

    removeSelectedRowsFromDom must refresh folderTbodyHtml (showFolderView restores it),
    reloadPage must soft-nav with no-store, and stripRemovedListRows covers SSR lag.
    """
    script = _app_js()
    remove_dom = _between(
        script,
        "function removeSelectedRowsFromDom(",
        "function stripRemovedListRows(",
    )
    assert "folderTbodyHtml = objectTbody.innerHTML" in remove_dom
    assert "function stripRemovedListRows(" in script
    soft = _between(script, "function softNavigate(", "function leavePage(")
    assert 'cache: "no-store"' in soft
    assert "softNavTail" in soft
    reload = _between(script, "function reloadPage(", "function reloadPageAfterDialog(")
    assert 'softNavigate(next, "replace")' in reload
    remove = _between(
        script,
        "removeBtn?.addEventListener(\"click\"",
        "async function loadChangesTab",
    )
    assert "await reloadPage(" in remove
    assert "__creopdmStripRemovedListRows" in remove
    assert "window.__creopdmStripRemovedListRows" in script


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
    assert "parent_folder: parentFolder" in script
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
    """Regression: soft-nav must serialize refreshes (never no-op or hard-reload)."""
    body = _between(_app_js(), "function softNavigate(", "function leavePage(")
    assert "__creopdmSoftNavBusy" in body
    assert "softNavTail" in body
    assert "Serialize" in body or "softNavTail.then" in body
    # Must not early-resolve while dropping a queued refresh.
    assert "softNavQueued" not in body
    assert "window.__creopdmBoot({ soft: true })" in body


def test_batch_remove_commits_before_response():
    """Remove-from-project soft reload raced FastAPI's post-response commit."""
    text = (ROOT / "src" / "creopdm" / "api" / "objects.py").read_text(encoding="utf-8")
    body = text.split("def remove_batch(", 1)[1].split("\n@router", 1)[0]
    assert "db.commit()" in body
    assert body.index("db.commit()") < body.index("return BatchOperationResponse")
    assert "soft reload would otherwise re-paint" in body or "Commit before the response" in body


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
    assert "softNavTail" in soft_nav
    assert "isSoftNavUrl" in soft_nav
    assert 'cache: "no-store"' in soft_nav

    leave = _between(script, "function leavePage(", "function reloadPage(")
    assert "isSoftNavUrl(url)" in leave
    assert "softNavigate" in leave
    assert "inCreoBrowser()" not in leave

    # Soft reload after remove/add — hard assign is ignored in Creo and left a stale table.
    reload = _between(script, "function reloadPage(", "function reloadPageAfterDialog(")
    assert "isSoftNavUrl(next)" in reload
    assert 'softNavigate(next, "replace")' in reload
    assert "window.location.assign(next)" in reload

    # Any same-origin soft-nav <a href> (Settings pill, crumbs, folders, …).
    assert 'closest("a[href]")' in script
    assert "api.softNavigate(href, \"push\")" in script or 'softNavigate(href, "push")' in script
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
    assert "Transient bridge / agent flake" in pill_fn or "Transient bridge flake" in pill_fn
    assert "wasConnected" in pill_fn
    assert "Do not require a healthy agent probe" in pill_fn
    assert "Session offline" in pill_fn
    # Soft-nav click/popstate must survive soft boots (not pageAbort-bound).
    assert "__creopdmSoftNavBound" in script
    assert "__creopdmSoftNavApi" in script
    assert "origAddEventListener.call" in script
    assert "abort prior page listeners" in script or "no pageAbort signal" in script


def test_checkout_checkin_toolbar_menus_and_open_wd():
    """Checkout/Check In fly-up menus and open-dialog Set working directory."""
    html = APP_HTML.read_text(encoding="utf-8")
    base = (ROOT / "src" / "creopdm" / "templates" / "base.html").read_text(encoding="utf-8")
    script = _app_js()
    assert 'id="open-menu"' in html
    assert "Open ▾" in html
    assert 'id="open-btn"' in html
    assert 'id="open-workspace-btn"' in html
    assert html.index('id="open-btn"') < html.index('id="open-workspace-btn"')
    assert ">Open selected…<" in html
    assert ">Open workspace…<" in html
    assert "function toggleOpenMenu" in script
    assert "closeOpenMenu" in script
    assert 'id="checkout-menu"' in html
    assert 'id="checkout-project-btn"' in html
    assert "Checkout project" in html
    assert 'id="undo-btn"' in html
    assert html.index('id="checkout-menu"') < html.index('id="undo-btn"')
    assert html.index('id="undo-btn"') < html.index('id="checkin-menu"')
    assert 'id="checkin-menu"' in html
    assert 'id="checkin-project-btn"' in html
    assert 'id="checkin-btn"' in html
    assert html.index('id="checkin-project-btn"') < html.index('id="checkin-btn"')
    assert ">Check in project…<" in html
    assert ">Check in selected…<" in html
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


def test_open_model_uses_nested_cache_folder():
    """Regression: nested agent-cache materialize must open from the file's folder."""
    base = (ROOT / "src" / "creopdm" / "templates" / "base.html").read_text(encoding="utf-8")
    open_fn = base.split("function openModel(", 1)[1].split("function setWorkingDirectory(", 1)[0]
    assert "creoParentDir" in open_fn
    assert "creoRelativeToDir" in open_fn
    assert "Nested agent-cache layout" in open_fn
    assert "var openWd = fileDir || directory" in open_fn or "openWd = fileDir || directory" in open_fn
    assert "ChangeDirectory(cacheDir)" in open_fn
    script = _app_js()
    meta = _between(script, "async function prepareLocalPathForMetadata(", "async function gatherCreoMetadataForFilename(")
    assert "openSpec.path" in meta
    assert "looksLikeLocalWindowsPath(materialized)" in meta


def test_mobile_browse_css_is_minimal():
    """Narrow screens hide chrome/toolbar and trim file-table columns (no sideways scroll)."""
    css = APP_CSS.read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "@media (max-width: 640px)" in css
    mobile = css.split("@media (max-width: 640px)", 1)[1]
    assert ".topbar .status-cluster" in mobile
    assert "#new-project-btn" in mobile
    assert ".project-settings" in mobile
    assert ".metrics" in mobile
    assert "footer.toolbar" in mobile
    assert "#detail-toolbar" in mobile
    assert "#object-table th:nth-child(n + 3)" in mobile
    assert "#checked-out-table th:nth-child(n + 3)" in mobile
    assert "#changes-table th:nth-child(n + 3)" in mobile
    assert "#history-files-table th:nth-child(n + 3)" in mobile
    assert ".detail-meta" in mobile
    assert "overflow-x: hidden" in mobile
    assert "browse-only" in docs
    assert "Name** and **Rev**" in docs


def test_details_overview_dedupes_identity_and_unifies_fonts():
    """Overview drops header duplicates and Details tabs share one UI font."""
    detail = (ROOT / "src" / "creopdm" / "templates" / "object_detail.html").read_text(
        encoding="utf-8"
    )
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    css = (ROOT / "src" / "creopdm" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    overview = _between(detail, 'id="panel-overview"', 'id="panel-parameters"')
    assert "<dt>Revision</dt>" not in overview
    assert "<dt>Lifecycle</dt>" not in overview
    assert "<dt>Checkout</dt>" not in overview
    assert "show_name" in overview
    assert "show_common" in overview
    assert "show_full" in overview
    assert "show_instance" in overview
    assert 'class="mono"' not in overview
    assert "detail-path" in overview
    assert "Content hash" not in overview
    assert "h[:12]" not in overview
    assert "<dt>Date created</dt>" in overview
    assert "local_time_pretty(object.created_at)" in overview
    assert "local_time(object.updated_at) != local_time(object.created_at)" in overview
    assert "omits content hash" in docs
    assert "Date created" in docs and "Date modified" in docs
    assert "hide Date modified when it matches Date created" in docs or "same as Date created" in docs
    assert "show content hash on Overview" in docs
    assert ".detail .filename-cell" in css
    assert "font-family: inherit" in css
    assert "text-transform: uppercase" in css
    assert "<dt>Number</dt>" not in overview
    assert "<dt>Name</dt>" in overview
    assert "label the model **Name**" in docs or "model **Name**" in docs
    assert "label the model identity as Number" in docs
    assert "skips duplicate identity fields" in docs
    assert "no mixed monospace" in docs
    assert "regular ink color" in docs
    assert "accent-colored hyperlinks" in docs
    assert ".detail a" in css
    assert "color: var(--ink)" in css
    assert ".detail .bom-legend-in" in css
    # One content size on Details — kv/grid inherit, not a smaller rem.
    assert ".detail .kv" in css and "font-size: inherit" in _between(css, ".detail .kv {", ".detail .kv dt")
    assert "font-size: inherit" in _between(css, ".detail .grid {", ".detail .grid th")
    # Detail tables no longer force mono class on every value cell.
    assert 'td class="mono"' not in detail
    assert 'th class="mono"' not in detail
    assert "object-open mono bom-name" not in detail
    script = _app_js()
    assert "function formatStampPretty" in script
    assert "function formatLocalPrettyDate" in script
    assert "local_time_pretty" in APP_HTML.read_text(encoding="utf-8")


def test_history_revert_only_for_older_versions():
    """Revert control appears only with older history; current row is not reversible."""
    detail = (ROOT / "src" / "creopdm" / "templates" / "object_detail.html").read_text(
        encoding="utf-8"
    )
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    css = (ROOT / "src" / "creopdm" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert "{% if history|length > 1 %}" in detail
    assert 'id="revert-version-btn"' in detail
    assert 'class="btn btn-danger" id="revert-version-btn"' in detail or 'btn btn-danger' in detail
    assert "red like Remove" in docs
    assert 'id="detail-toolbar"' in detail
    assert 'id="detail-tab-title"' in detail
    assert 'id="detail-tab-title-text"' in detail
    assert ">Details</h1>" in detail
    assert "hidden" not in detail.split('id="detail-tab-title"', 1)[1].split(">", 1)[0]
    assert 'id="open-menu-btn"' in detail and "Open ▾" in detail
    assert 'id="checkout-menu-btn"' in detail and "Checkout ▾" in detail
    assert 'id="checkin-menu-btn"' in detail and "Check In ▾" in detail
    assert "history-actions" not in detail
    assert "detail-actions" not in detail
    assert "panel-heading" not in detail
    assert 'data-can-revert=' in detail
    assert "version-row" in detail
    assert "function syncRevertVersionButton" in script
    assert "function syncDetailToolbar" in script
    assert "function syncDetailTabTitle" not in script
    assert "historyTabActive" not in script
    assert "setToolbarActionVisible(btn, canRevert)" in script
    assert 'setToolbarActionVisible(openMenuBtn, false)' in script
    assert "Open ▾" in detail
    assert 'id="open-btn"' in detail
    assert ">Open…</button>" in detail or "Open…</button>" in detail
    assert "revert-version-hint" not in detail
    assert "That is the current version" not in script
    assert "Select an older version to restore it." not in script
    assert "historyOlderRowSelected" not in script
    assert 'setToolbarActionVisible(checkoutMenuBtn, false)' in script
    assert 'setToolbarActionVisible(removeMenuBtn, false)' in script
    detail_toolbar = _between(script, "function syncDetailToolbar(", "function selectHistoryVersionRow(")
    assert 'setToolbarActionVisible(openMenuBtn, false)' in detail_toolbar
    assert 'setToolbarActionVisible(checkoutMenuBtn, false)' in detail_toolbar
    assert 'setToolbarActionVisible(removeMenuBtn, false)' in detail_toolbar
    assert 'setToolbarActionVisible(checkinMenuBtn, false)' in detail_toolbar
    assert 'setToolbarActionVisible(checkinBtn, false)' in detail_toolbar
    assert "setCreoDirBtn.hidden = true" in detail_toolbar
    assert "pendingSaves" not in detail_toolbar
    assert "canCheckinProject" not in detail_toolbar
    assert "never **Check In ▾**" in docs or "never **Check In" in docs
    assert "Check In stays on the Files page" in docs
    assert "Revert to selected…** only" in docs or "Revert to selected… only" in docs
    assert "You do not need to Check In afterward" in script
    assert "confirmByProjectName({" in script
    assert 'title: `Revert to ${display}`' in script
    assert 'submitLabel: "Revert"' in script
    assert 'data-project-name="{{ project.name }}"' in detail
    assert '$("#revert-version-btn")?.dataset.projectName' in script
    revert_click = _between(
        script,
        '$("#revert-version-btn")?.addEventListener("click"',
        'document.querySelectorAll(".tabs .tab")',
    )
    assert "confirmByProjectName" in revert_click
    assert "window.confirm" not in revert_click
    assert "Version History" not in detail
    assert "File History" not in detail
    assert "subpanel-versions" not in detail
    assert 'id="history-files-table"' in detail
    assert "never **Check In ▾**" in docs or "Check In stays on the Files page" in docs
    assert "**Details** title" in docs
    assert "separate Version History view" in docs
    assert "left: 0" in css
    assert "#remove-menu .toolbar-menu-panel" in css
    assert "row.dataset.canRevert === \"1\"" in script or "dataset.canRevert === \"1\"" in script
    assert "/versions/" in script and "/revert" in script
    assert "background: var(--panel)" in css
    assert ".detail-tab-title" in css
    assert "Choose an older version to revert" in (
        (ROOT / "src" / "creopdm" / "services" / "checkin_service.py").read_text(encoding="utf-8")
    )
    assert "path_changed" in (
        (ROOT / "src" / "creopdm" / "services" / "checkin_service.py").read_text(encoding="utf-8")
    )
    assert "replace_newer" in script
    assert "replace_newer: true" in script or "replace_newer: true," in script
    assert "purge_newer_creo_saves" in (
        (ROOT / "src" / "creopdm" / "services" / "workspace_service.py").read_text(encoding="utf-8")
    )
    assert "_purge_newer_local_saves" in (
        (ROOT / "src" / "creopdm_agent" / "server.py").read_text(encoding="utf-8")
    )
    assert "restore_version" in (
        (ROOT / "src" / "creopdm" / "services" / "checkin_service.py").read_text(encoding="utf-8")
    )
    assert "Revert to selected" in docs
    assert "Offer Revert for the current version" in docs
    assert "keep a newer `.prt.N` name while only swapping bytes" in docs
    assert "leave you checked out with a Check In prompt" in docs
    assert "type the **exact** project name" in docs
    assert "plain browser `confirm`" in docs
    assert "History **Revert to selected…**" in docs
    assert "no Check In prompt" in docs
    assert "bottom toolbar" in docs.lower() or "at the bottom" in docs.lower()
    assert "Open the file **Details** page on the **Overview** tab" in docs
    assert "Open the History tab by default" in docs
    html = APP_HTML.read_text(encoding="utf-8")
    assert 'id="history-btn"' in html
    assert ">Details</button>" in html
    assert ">History</button>" not in html
    assert 'data-detail="/projects/{{ selected.uuid }}/objects/{{ obj.uuid }}"' in html
    assert 'data-detail="/projects/{{ selected.uuid }}/objects/{{ obj.uuid }}#history"' not in html
    assert "Details page defaults to Overview" in script
    href_fn = _between(script, "function rowHistoryHref(", "document.querySelector(\"#object-table\")")
    assert "return `/projects/${projectId}/objects/${uuid}`;" in href_fn
    assert "objects/${uuid}#history" not in href_fn


def test_toolbar_hides_inactive_actions():
    """Inactive toolbar buttons and fly-up items are hidden, not left greyed out."""
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    visible = _between(script, "function setToolbarActionVisible(", "function isNewFileQueueRow(")
    assert "button.hidden = !visible" in visible
    assert "button.disabled = !visible" in visible
    assert 'button.closest(".toolbar-tip")' in visible
    assert 'button.classList.contains("toolbar-menu-toggle")' in visible
    assert "menu.hidden = !visible" in visible
    sync = _between(script, "function syncToolbar(", "function setCheckinQueueCounts(")
    assert "setToolbarActionVisible(openMenuBtn," in sync
    assert "setToolbarActionVisible(checkoutMenuBtn," in sync
    assert "setToolbarActionVisible(checkinMenuBtn," in sync
    assert "setToolbarActionVisible(removeMenuBtn," in sync
    assert "setToolbarActionVisible(historyBtn," in sync
    assert "setToolbarActionVisible(addMenuBtn," in sync
    assert "openBtn.disabled =" not in sync
    assert "| Hidden when |" in docs
    assert "are **hidden** (not greyed out)" in docs
    # Set Working Directory stays visible on Files (discoverable) even when disabled;
    # Details page always hides it.
    creo = _between(script, "async function refreshCreoStatusPill(", "function showCreoSessionControls(")
    assert "Keep Set Working Directory in the Files toolbar" in creo
    assert "el.hidden = false" in creo
    assert "btn.hidden = false" in creo
    assert 'btn.id === "set-creo-dir-btn"' in creo
    assert "File Details page hides it" in creo
    assert 'Boolean($("article.detail"))' in creo
    assert "On the file **Details** page" in docs
    assert "every tab, including History" in docs
    assert "Check In stays on the Files page" in docs


def test_folder_row_click_selects_double_click_opens():
    """Regression: folder name link opens; row chrome selects; double-click opens."""
    script = _app_js()
    click = _between(script, "function onFileTableClick(", "function onFileTableDblclick(")
    assert 'closest?.("a.folder-open")' in click
    assert "openFolderRow(folderRow)" in click
    assert click.index("openFolderRow(folderRow)") < click.index("selectOnly(folderRow)")
    assert "selectOnly(folderRow)" in click
    assert "stopPropagation()" in click
    assert 'closest?.(".folder-row")' in click
    assert 'closest(".object-row, .queue-row")' in click
    dbl = _between(script, "function onFileTableDblclick(", "function rowHistoryHref(")
    assert "openFolderRow(folder)" in dbl
    assert 'closest?.(".folder-row")' in dbl
    soft = script.split("Keep Creo.JS connected: soft-navigate shell pages", 1)[1]
    soft = soft.split('window.addEventListener("popstate"', 1)[0]
    assert "folder-open" in soft
    assert "tr.folder-row" in soft
    assert "return;" in soft
    html = APP_HTML.read_text(encoding="utf-8")
    assert "Click the folder name to open" in html
    select_only = _between(script, "function selectOnly(", "function selectRange(")
    assert 'classList.contains("folder-row")' in select_only
    assert "syncToolbar()" in select_only
    apply_sel = _between(script, "function applyMetricSelection(", "function metricSelectionActive(")
    assert 'classList.contains("folder-row")) return' in apply_sel or 'folder-row")) return' in apply_sel
    assert "markRowSelected(row, false)" not in apply_sel
    css = APP_CSS.read_text(encoding="utf-8")
    assert "cursor: default" in css.split(".folder-row {", 1)[1].split("}", 1)[0]
    assert "width: fit-content" in css


def test_user_interaction_negative_client_guards():
    """docs/user-interactions.md — Add / Create / confirm / check-in negative strings."""
    script = _app_js()
    html = APP_HTML.read_text(encoding="utf-8")

    # Create folder… blank name (A1)
    create = _between(
        script,
        'createFolderForm?.addEventListener("submit"',
        'purgeBtn?.addEventListener("click"',
    )
    assert 'Enter a folder name.' in create
    assert 'id="create-folder-name"' in html
    assert 'maxlength="200"' in html.split('id="create-folder-name"', 1)[1].split(">", 1)[0]

    # Add mode negatives (A6–A10)
    assert "Use Add folders or Add Folder to import a folder tree." in script
    assert "No top-level files found in that folder. Subfolder files are skipped for Add Folder." in script
    assert "Add is already running — wait for it to finish." in script
    assert "Choose files or a folder first." in script
    assert "Choose a folder first." in script
    assert "function filterTopLevelUploads(" in script
    filter_body = _between(script, "function filterTopLevelUploads(", "function applyDroppedFiles(")
    assert "parts.length > 2" in filter_body

    # Danger confirm (D1 / N15)
    confirm = _between(script, "function confirmByProjectName(", "function workspacePathsForRemovedObjects(")
    assert "Type the project name exactly to confirm." in confirm
    assert "typed !== expected" in confirm

    # Check In comment required on dialog
    assert 'id="checkin-comment"' in html
    assert "required" in html.split('id="checkin-comment"', 1)[1].split(">", 1)[0]

    # Remove from Project enablement includes empty folders (V2 / N16)
    assert "canRemoveProject = ids.length > 0 || folderPaths.length > 0" in script


def test_newer_local_cache_matches_flat_save_for_nested_vault_path():
    """Regression: older flat agent caches + nested vault paths still detect Modified."""
    script = _app_js()
    body = _between(script, "function newerLocalCacheSaves(", "async function countLocalNewWorkspaceFiles(")
    assert "bestByBasename" in body
    assert "vaultBasenameCounts" in body
    assert "vaultBasenameCounts.get(base) || 0) === 1" in body
    assert "Older flat agent caches" in body
