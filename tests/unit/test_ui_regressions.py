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
    """Add ▾: Create folder…, Add files…, Add folder…, Add folders…, Add selected…"""
    html = APP_HTML.read_text(encoding="utf-8")
    assert 'id="add-menu"' in html
    assert "Add ▾" in html
    assert 'id="create-folder-btn"' in html
    assert 'id="add-files-btn"' in html
    assert 'id="add-folder-btn"' in html
    assert 'id="add-folders-btn"' in html
    assert 'id="add-selected-btn"' in html
    assert html.index('id="create-folder-btn"') < html.index('id="add-files-btn"')
    assert html.index('id="add-files-btn"') < html.index('id="add-folder-btn"')
    assert html.index('id="add-folder-btn"') < html.index('id="add-folders-btn"')
    assert html.index('id="add-compressed-btn"') < html.index('id="add-selected-btn"')
    assert ">Create folder…<" in html
    assert ">Add files…<" in html
    assert ">Add folder…<" in html
    assert ">Add folders…<" in html
    assert ">Add selected…<" in html
    assert 'id="create-folder-dialog"' in html
    script = _app_js()
    assert 'openAddDialog("files")' in script
    assert 'openAddDialog("folders")' in script
    assert 'openAddDialog("folder")' in script
    assert "recursive" in script
    assert "/api/products/${productId}/folders" in script or '/api/products/${productId}/folders' in script
    # Add selected… only for New files queue rows (never Modified / Files).
    assert "function beginAddSelected" in script
    assert "selectionIsAddOnly(selected)" in script
    assert 'id: "files-context-add-selected"' in script or 'action: "add-selected"' in script
    sync = _between(script, "function syncToolbar(", "function setCheckinQueueCounts(")
    assert "canAddSelected" in sync
    assert "addOnly" in sync
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "### Add selected…" in docs
    assert "enabled only when the selection is **New files**" in docs or "New files** rows" in docs


def test_remove_from_product_sends_folder_paths():
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
    sync = _between(script, "function syncToolbar(", "function setCheckinQueueCounts(")
    assert "Boolean(removeBtn)" in sync
    assert "ids.length > 0 || folderPaths.length > 0" in sync


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
    html = APP_HTML.read_text(encoding="utf-8")
    assert 'id="add-keep-root-folder"' in html
    assert "function keepRootFolder" in script
    assert "keep_root_folder: keepRootFolder()" in script
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "Keep chosen folder name" in docs


def test_choose_files_still_prefers_agent_picker():
    files_click = _between(
        _app_js(),
        '$("#choose-workspace-files")?.addEventListener("click"',
        '$("#choose-workspace-folder")?.addEventListener("click"',
    )
    assert "browseViaAgentPicker" in files_click
    assert files_click.index("browseViaAgentPicker") < files_click.index("browseLocalFiles")
    script = _app_js()
    pick = _between(script, "async function browseViaAgentPicker(", "async function browseViaAgentFolderPicker(")
    assert 'setBusy("Waiting for file picker…")' in pick
    assert 'setBusy("Preparing selection…")' in pick
    assert "Add folders…" in pick
    assert 'confirmLargeBulk("Add", bulkCount)' in script


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
    assert "effectiveComment" in add_chunk
    assert "`Add ${total} files`" in add_chunk
    assert "offset === 0 ? commentOnce" not in add_chunk
    assert 'data.append("batch_total"' in script
    assert "bulkCount > 1 ? `Add ${bulkCount} files`" in script
    assert "importExtensionSet" in script
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "Add 5 files` just because the agent uploaded in 5-file chunks" in docs
    # logicalUploadName must not strip .N from non-purgeable names (e.g. .snagx.1).
    logical = _between(script, "function logicalUploadName(", "function purgeableExtensionSet(")
    assert "isImportVersionedExtension" in logical


def test_settings_muted_help_under_field_top_margin_only():
    """Help under form fields uses a small top margin only (no stacked p bottom gap)."""
    css = APP_CSS.read_text(encoding="utf-8")
    block = _between(css, ".settings-form .muted.small {", ".settings-form h2 + .muted.small")
    assert "margin: 0.2rem 0 0" in block
    assert ".settings-form label + .muted.small" in css
    label_help = _between(css, ".settings-form label + .muted.small {", "}")
    assert "margin-top: 0.15rem" in label_help


def test_status_pills_do_not_shrink_into_tall_capsules():
    """Regression: narrow topbar wrapped pill text + border-radius 999px → tall ovals."""
    css = APP_CSS.read_text(encoding="utf-8")
    block = _between(css, ".status-pill {", ".status-pill[data-state=")
    assert "white-space: nowrap" in block
    assert "flex-shrink: 0" in block
    assert "inline-flex" in block
    assert "border-radius: 999px" in block


def test_locked_product_changes_help_does_not_offer_add_checkin():
    """Tab help blurbs appear only when product_ui says those actions are available."""
    html = APP_HTML.read_text(encoding="utf-8")
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    # Modified / New files: no tip blurb (count + list are enough).
    changes_panel = _between(html, 'id="panel-changes"', 'id="checkin-dialog"')
    assert 'id="changes-help"' not in changes_panel
    assert "muted small" not in changes_panel.split('id="changes-table"', 1)[0]
    mod_panel = _between(html, 'id="panel-modified"', 'id="panel-changes"')
    assert 'id="modified-help"' not in mod_panel
    assert "muted small" not in mod_panel.split('id="modified-table"', 1)[0]
    assert 'id="checked-out-help"' in html
    assert "Use <strong>Add</strong> to bring them in" not in html
    assert "Use <strong>Check In</strong> to record them" not in html
    assert "Open, Check In, and Undo Checkout still apply" in html
    assert "are blocked while this product is" not in html
    assert "function canOfferAdd" in script
    assert "function canOfferCheckin" in script
    assert '"Local workspace."' in script
    assert '"Not in the product yet."' in script
    assert "no tip blurb on **Modified** or **New files**" in docs


def test_modified_tab_between_checked_out_and_new_files():
    """Modified tab lists vault/local newer saves; New files stays new-only with its own count."""
    html = APP_HTML.read_text(encoding="utf-8")
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert 'data-tab="modified"' in html
    assert 'id="modified-table"' in html
    assert 'id="panel-modified"' in html
    assert html.index('data-tab="checked-out"') < html.index('data-tab="modified"')
    assert html.index('data-tab="modified"') < html.index('data-tab="changes"')
    assert "function loadModifiedTab(" in script
    assert "function loadCheckinQueueParts(" in script
    counts = _between(script, "function setCheckinQueueCounts(", "function setCheckedOutTabCount(")
    assert 'data-tab="modified"' in counts
    assert "`Modified · ${n}`" in counts
    assert "`New files · ${n}`" in counts
    assert "Number(pendingSaves || 0) + Number(newFiles || 0)" not in counts
    apply = _between(script, "async function applyCheckinQueueParts(", "function appendQueueRow(")
    assert 'focus === "modified"' in apply
    assert "renderModifiedQueueRows" in apply
    assert "renderNewFilesQueueRows" in apply
    assert 'applyCheckinQueueParts(productId, parts, "changes")' in script
    assert 'applyCheckinQueueParts(productId, cached, "changes")' in script
    assert 'applyCheckinQueueParts(productId, parts, "modified")' in script
    assert 'applyCheckinQueueParts(productId, cached, "modified")' in script
    changes = _between(script, "async function loadChangesTab(", "async function loadCheckedOutTab(")
    assert 'focus === "modified"' not in changes
    assert 'applyCheckinQueueParts(productId' in changes
    modified = _between(script, "async function loadModifiedTab(", "async function loadChangesTab(")
    assert 'applyCheckinQueueParts(productId' in modified
    assert 'forceNetwork' in modified
    assert 'activeTab === "modified"' in script
    assert "await loadModifiedTab({ quiet: true, forceNetwork: true })" in script
    assert "function prefetchCheckinQueueParts(" in script
    assert "function cachedCheckinQueueParts(" in script
    assert "function invalidateCheckinQueueCache(" in script
    assert "function tabBadgeCount(" in script
    assert "forceNetwork: true" in script
    assert 'loadChangesTab({ quiet: true, forceNetwork: true })' in script
    assert 'loadModifiedTab({ quiet: true, forceNetwork: true })' in script
    assert "counts.created !== tabBadgeCount" in script
    assert "counts.modified !== tabBadgeCount" in script
    changes_loader = _between(script, "async function loadChangesTab(", "async function loadCheckedOutTab(")
    modified_loader = _between(script, "async function loadModifiedTab(", "async function loadChangesTab(")
    assert "showQueueLoading" not in changes_loader
    assert "showQueueLoading" not in modified_loader
    assert "Looking for new vault and local workspace files" not in changes_loader
    assert "Looking for modified vault and local workspace files" not in modified_loader
    assert "warm the row list" in docs
    assert "Looking for…" in docs or "Looking for" in docs
    assert "**Modified** tab" in docs or "**Modified tab**" in docs
    assert "not modified vault tips" in docs
    assert "live counts for Modified and New files" in docs


def test_product_state_badge_in_files_header():
    """Product lifecycle state uses the same .state dot badge as the Files State column."""
    html = APP_HTML.read_text(encoding="utf-8")
    css = APP_CSS.read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert 'id="product-state-badge"' in html
    assert 'class="state product-state"' in html
    assert "selected.state.replace('_', ' ') | title" in html
    assert "Read only" in html
    assert html.index('id="product-state-badge"') < html.index('id="search-form"')
    assert ".title-row .product-state" in css
    assert '.state[data-state="ON_HOLD"]::before' in css
    assert '.state[data-state="CLOSED"]::before' in css
    assert '.checkout-state[data-state="locked"]::before' in css
    assert "current product state" in docs.lower()
    assert "can_checkout %}available{% else %}locked" in html
    # Lock banner states the fact only — no laundry list of blocked actions.
    banner = _between(html, 'id="product-access-banner"', "</p>")
    assert "This product is" in banner
    assert "are blocked" not in banner
    assert "checkout" not in banner.lower()
    assert "without listing blocked actions" in docs


def test_metadata_gear_items_require_creo_session():
    """Collect / Rebuild Where Used use creo-session-only like Set Working Directory."""
    app_html = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    script = _app_js()
    assert "product_ui.show_metadata_tools" in app_html
    assert "product_ui.show_add" in app_html
    assert "product_ui.show_checkin" in app_html
    assert "product_ui.show_remove_vault" in app_html
    assert "product_ui.show_remove_product" in app_html
    assert 'data-requires-mutation=' not in app_html
    assert "creo-session-only" in app_html
    assert "productAllowsMutation" not in script
    assert "mutationActionAllowed" not in script
    assert "data-allows-mutation" in app_html
    assert "Rebuild Where Used" in docs and "Collect all metadata" in docs
    assert "read only" in docs.lower() or "read-only" in docs.lower()
    # Collect blocks the UI like Add — progress on busy overlay, no mid-run soft-nav.
    loop = _between(script, "async function runMetadataCollectLoop(", "async function runCollectAllMetadata(")
    assert 'setBusy("Collecting Creo metadata…")' in loop
    assert "setBusyMessage(message)" in loop
    assert "clearBusy()" in loop
    # Type labels are SSR — must refresh Files after Collect saves (not only on F5).
    assert "shouldRefreshList = captured > 0" in loop
    assert 'await reloadPage({ keepBusy: true, busyMessage: "Refreshing…" })' in loop
    assert loop.index("metadataCollectJob.running = false") < loop.index("await reloadPage(")
    assert "beforeunload" in script
    soft = _between(script, "function softNavigate(", "function leavePage(")
    assert "metadataCollectJob.running" in soft
    assert "busy overlay" in docs.lower()
    assert "refresh the Files list" in docs
    assert "stale Type labels until a hard refresh" in docs
    # Product-link soft-nav must not withBusy("Loading…") while Collect owns the overlay.
    assert "isMetadataCollectRunning" in script
    assert "warnMetadataCollectBlockingNav" in script
    click = _between(script, 'document,\n      "click",', 'origAddEventListener.call(window, "popstate"')
    assert "isMetadataCollectRunning()" in click
    assert click.index("isMetadataCollectRunning()") < click.index('void api.withBusy("Loading…"')


def test_compressed_data_add_requires_agent_and_busy_overlay():
    """Add ▾ → Compressed data… explains first, then pick-files + import-zip."""
    app_html = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    script = _app_js()
    assert 'id="add-compressed-btn"' in app_html
    assert 'id="compressed-dialog"' in app_html
    assert 'id="compressed-choose-btn"' in app_html
    assert "Compressed data…" in app_html
    assert "Compressed data…" in docs
    assert "creopdm-agent" in docs.lower() or "require creopdm-agent" in docs.lower()
    assert "function openCompressedDialog(" in script
    assert "async function chooseCompressedZip(" in script
    assert 'filter_mode: "archive"' in script
    assert "/pick-files" in script
    assert "/import-zip" in script
    assert "Uploading and importing compressed data…" in script
    assert "Start creopdm-agent on this Creo PC to add compressed data." in script
    assert "Zip archives" in docs or "*.zip" in docs
    products = (ROOT / "src" / "creopdm" / "api" / "products.py").read_text(encoding="utf-8")
    assert "/objects/from-zip" in products
    assert "ensure_product_mutable" in products
    dialog = (ROOT / "src" / "creopdm" / "utils" / "native_dialog.py").read_text(encoding="utf-8")
    assert "def archive_dialog_filter_pairs(" in dialog
    assert '"*.zip"' in dialog


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


def test_product_dialog_has_vault_folder_and_use_hash():
    html = APP_HTML.read_text(encoding="utf-8")
    assert "Vault/Workspace name" in html
    assert 'id="product-use-hash"' in html
    assert 'name="vault_folder"' in html
    assert 'class="checkbox-row"' in html
    assert 'for="product-use-hash"' in html
    # Use hash is the default — uncheck to type a custom vault folder.
    assert 'id="product-use-hash" checked' in html
    assert "data-vault-folder=" in html
    script = _app_js()
    assert "syncProductVaultFolderField" in script
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
    assert ".product-vault-fields .checkbox-row" in css
    assert "flex-direction: row" in css.split(".product-vault-fields .checkbox-row", 1)[1].split("}", 1)[0]


def test_admin_edit_vault_folder_is_readonly_disabled():
    """Edit form shows vault_folder but must never allow changing it."""
    html = (ROOT / "src" / "creopdm" / "templates" / "admin_product_form.html").read_text(
        encoding="utf-8"
    )
    # Edit branch: disabled vault field (create branch stays editable).
    assert "readonly disabled" in html
    assert "cannot be changed" in html.lower()
    assert 'name="vault_folder"' in html


def test_delete_product_dialog_offers_local_workspace_checkbox():
    html = APP_HTML.read_text(encoding="utf-8")
    assert 'id="delete-local-workspace" checked' in html
    assert "Also delete local workspace on this PC" in html
    script = _app_js()
    assert "/delete-product-cache" in script
    assert "remove_folder: true" in script
    assert "delete-local-workspace" in script


def test_delete_workspace_menu_warns_new_files_vault_safe():
    """Remove ▾ → Clear workspace… danger-confirm; no product-name typing; vault stays."""
    html = APP_HTML.read_text(encoding="utf-8")
    assert 'id="delete-workspace-btn"' in html
    assert ">Clear workspace…<" in html
    assert 'class="toolbar-menu-item is-danger" role="menuitem" id="delete-workspace-btn"' in html
    assert html.index('id="purge-versions-btn"') < html.index('id="delete-workspace-btn"')
    script = _app_js()
    assert "async function deleteLocalProductWorkspace(" in script
    assert 'title: "Clear workspace"' in script
    assert "Local-only new files that were never added" in script
    assert "empty workspace folder stays" in script
    assert "Vault copies and the product file list are not changed" in script
    assert "requireProductName: false" in script
    assert "Same danger-confirm overlay" in script
    assert "deleteWorkspaceBtn?.addEventListener(" in script
    assert "setToolbarActionVisible(deleteWorkspaceBtn, canDeleteWorkspace)" in script
    base = (ROOT / "src" / "creopdm" / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'id="danger-confirm-dialog"' in base
    assert 'id="danger-confirm-name-label"' in base
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "### Clear workspace…" in docs
    assert "local-only **new** files" in docs
    assert "does **not** require typing the product name" in docs
    clear_section = docs.split("### Clear workspace…", 1)[1].split("### Remove from Vault…", 1)[0]
    assert "danger-confirm warning dialog" in clear_section
    assert "Clear workspace" in clear_section
    assert "| Confirm |" in clear_section
    assert "Confirm with the correct product name" not in clear_section
    assert "delete the workspace folder itself" in clear_section


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
    """Remove-from-product soft reload raced FastAPI's post-response commit."""
    text = (ROOT / "src" / "creopdm" / "api" / "objects.py").read_text(encoding="utf-8")
    body = text.split("def remove_batch(", 1)[1].split("\n@router", 1)[0]
    assert "db.commit()" in body
    assert body.index("db.commit()") < body.index("return BatchOperationResponse")
    assert "soft reload would otherwise re-paint" in body or "Commit before the response" in body


def test_soft_nav_skips_creojs_reconnect():
    """Regression: shell soft nav used to re-probe Creo.JS and flash offline.

    Soft switches only replace main.shell; the status pill and Creo.JS bridge live
    outside it and must stay connected — including folders, products, and Settings.
    Hard reload SSR-paints Not Connected and drops the live bridge.
    """
    script = _app_js()
    base = (ROOT / "src" / "creopdm" / "templates" / "base.html").read_text(encoding="utf-8")

    # Pill / status cluster sit outside the soft-swapped shell.
    assert 'id="creo-status"' in base
    assert base.index("status-cluster") < base.index('<main class="shell">')
    assert base.index('id="creo-status"') < base.index('<main class="shell">')
    assert 'href="/admin"' in base
    assert 'can_view_objects' in base
    assert 'can_view_products' in base
    assert 'href="/settings"' not in base.split('<main')[0]

    # Soft-nav: all signed-in shell pages; hard-load only auth/API/static.
    soft_fn = _between(script, "function isSoftNavUrl(", "let softNavBusy")
    assert 'path.startsWith("/admin")' in soft_fn
    assert 'path.startsWith("/settings")' in soft_fn
    assert 'path.startsWith("/account")' in soft_fn
    assert 'path === "/logout"' in soft_fn
    assert 'path === "/login"' in soft_fn
    assert 'path.startsWith("/api/")' in soft_fn
    assert "/products/" in soft_fn or r"/products\/" in soft_fn
    assert "objects" in soft_fn
    assert "Creo.JS stays Connected" in soft_fn
    assert "userCanCheckout" in script
    assert "userCanCheckin" in script
    assert "roleCanCheckout" in _between(
        script, "function syncToolbar(", "function setCheckinQueueCounts("
    )
    assert "roleCanCheckin" in _between(
        script, "function syncToolbar(", "function setCheckinQueueCounts("
    )
    assert "userCanCheckout()" in _between(
        script, "function promptOpenCheckout(", "function checkoutBeforeOpen("
    )
    prompt_fn = _between(
        script, "function promptOpenCheckout(", "function checkoutBeforeOpen("
    )
    assert "hostedCreoJS()" in prompt_fn
    assert "skip a one-option dialog" in prompt_fn or "!allowCheckout" in prompt_fn
    assert "showWd" in prompt_fn
    assert "agentPdmAuth" in script
    assert "...agentPdmAuth()" in script or "agentPdmAuth()" in script
    open_fn = _between(script, "async function openPdmObjectWork(", "function openPdmLaunchResult(")
    assert "hostedCreoJS() && embeddedMode" in open_fn or 'hostedCreoJS() && creoOpenMode() === "embedded"' in open_fn
    assert 'openViaAgent(openSpec.path, "association")' in open_fn
    assert "function likelyStandaloneBrowser(" in script
    assert "Waiting for Creo.JS…" in open_fn
    assert "Creo.JS is not connected yet" in open_fn
    assert "Windows file association from the embedded browser" in open_fn
    assert "spec.localCache && spec.relativePath" in open_fn
    assert "!spec.objectId" not in open_fn.split("spec.localCache && spec.relativePath", 1)[1].split("\n", 1)[0]
    assert "openLocalCacheRelative(" in open_fn
    assert "function openLocalCacheRelative(" in script
    assert "function joinLocalWorkspacePath(" in script
    local_open = _between(script, "async function openLocalCacheRelative(", "async function openPdmObject(")
    assert "logicalUploadName(diskName)" in local_open
    assert 'CreoJS.openModel(directory, logicalName, "", diskName, fullPath)' in local_open
    open_spec = _between(script, "function openSpecFromRow(", "function stateSortToken(")
    assert "localCache && relativePath" in open_spec
    assert "Newer local save" in open_spec or "agent-workspace tip" in open_spec
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "Newer local save" in docs and "Vault file not found" in docs
    assert "**logical** tip" in docs
    assert "test-part.prt.1" in docs
    open_wrap = _between(script, "async function openPdmObject(", "async function openPdmObjectWork(")
    assert 'withBusy("Preparing…"' in open_wrap
    assert "withTimeout(" in open_wrap
    assert "Open timed out" in open_wrap
    assert "function setOpenPrepareBusyMessage(" in script
    assert "function setOpenDownloadBusyMessage(" in script
    assert 'setBusyMessage("Finding dependencies…")' in script
    assert "setOpenPrepareBusyMessage()" in open_fn
    assert "setOpenDownloadBusyMessage(prepared)" in open_fn
    assert "prefer_local: Boolean(prepared.prefer_local)" in script
    download_busy = _between(
        script,
        "function setOpenDownloadBusyMessage(",
        "async function materializeViaAgentPerFile(",
    )
    assert "Checking local index (${total} files)" in download_busy
    assert "Updating local workspace… (${total} tips)" in download_busy
    assert 'setBusyMessage("Updating local workspace…")' in download_busy
    assert "Syncing ${total} files to local workspace" not in download_busy
    assert "Downloading to local cache" not in download_busy
    assert "BULK_AGENT_CACHE_ZIP_THRESHOLD" in download_busy
    mat = _between(script, "async function materializeViaAgent(", "async function materializeCheckedOutToAgentCacheZip(")
    assert "materializeCheckedOutToAgentCacheZip(unique, prepared)" in mat
    assert "cachePlanItemsFromPrepared" in script
    assert "items: planItems" in script
    assert "materializeViaAgentPerFile(prepared, [])" in mat
    assert "one zip from CreoPDM" in mat
    assert "Local workspace already up to date" in mat
    docs_open = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "Open a file already checked out to you" in docs_open
    assert "do **not** overwrite with vault bytes" in docs_open
    assert "Checking local index" in script
    assert "`.creopdm_cache_index.json`" in docs_open or "creopdm_cache_index" in docs_open
    assert "Checking local cache for ${total} files…" not in script
    assert "Opening in Creo…" in open_fn
    assert "Opening with Windows…" in open_fn
    # Association path must not await creoJSReady first; embedded waits briefly then warns.
    assert "Do not await creoJSReady first on the association path" in open_fn
    assert open_fn.index("const useCreoSession") < open_fn.index("await creoJSReady;")
    docs_open_wait = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "Creo.JS is not Connected yet" in docs_open_wait or "Creo.JS is not connected yet" in docs_open_wait
    assert "Windows file association from Creo" in docs_open_wait or "open via Windows file association from Creo" in docs_open_wait
    ready = _between(script, "function whenCreoJSReady(", "async function refreshCreoStatusPill(")
    assert "session may be offline" in ready
    assert 'data-can-checkout=' in (
        ROOT / "src" / "creopdm" / "templates" / "base.html"
    ).read_text(encoding="utf-8")
    assert 'data-can-checkin=' in (
        ROOT / "src" / "creopdm" / "templates" / "base.html"
    ).read_text(encoding="utf-8")
    assert 'data-agent-token=' in (
        ROOT / "src" / "creopdm" / "templates" / "base.html"
    ).read_text(encoding="utf-8")
    soft_nav = _between(script, "function softNavigate(", "function leavePage(")
    assert "innerHTML = nextShell.innerHTML" in soft_nav or "curShell.innerHTML" in soft_nav
    # Soft-nav does not execute inline scripts; product-access toggle is document-bound.
    assert "function syncProductAccessUi" in script
    assert "__creopdmProductAccessBound" in script
    assert 'id !== "access-all-products"' in script
    assert "syncProductAccessUi();" in script
    assert "window.__creopdmBoot({ soft: true })" in soft_nav
    assert "Keep the live Creo.JS bridge" in soft_nav
    assert "softNavTail" in soft_nav
    assert "isSoftNavUrl" in soft_nav
    assert 'cache: "no-store"' in soft_nav

    leave = _between(script, "function leavePage(", "function reloadPage(")
    assert "isSoftNavUrl(url)" in leave
    assert "softNavigate" in leave
    assert "inCreoBrowser()" not in leave
    assert "leavePage(productHome())" in script
    assert "window.location.href = productHome()" not in script

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
    assert "function promoteCreoPillWhenSessionLive(" in script
    assert "function applyCreoSessionOnlyVisibility(" in script
    assert "Never re-probe agent or reconnect" in script
    block = script.split("function showCreoSessionControls(")[1].split("async function agentWorkdir(")[0]
    assert "if (soft)" in block
    assert "else if (!isListPage)" in block
    assert "skip agent /health" in block or "Skip agent /health" in block or "no Open workspace toolbar" in block
    soft_branch = block.split("if (soft)")[1].split("} else if (!isListPage)")[0]
    assert "syncCreoSessionControlsFromBridge()" in soft_branch
    assert "probeCreoAgent" not in soft_branch
    assert "refreshCreoStatusPill" not in soft_branch
    # Soft/Details boots may poll for a late Creo.JS bridge — never agent /health.
    assert "pollCreoBridgeUntilLive" in soft_branch
    assert "creoJSReady.then" in soft_branch
    non_list = block.split("else if (!isListPage)")[1].split("} else {")[0]
    assert "syncCreoSessionControlsFromBridge()" in non_list
    assert "probeCreoAgent" not in non_list
    assert "pollCreoBridgeUntilLive" in non_list
    assert "function pollCreoBridgeUntilLive(" in script
    assert "Details does not stay Session offline" in non_list
    # Embedded browser only: block clicks while Creo.JS is still linking.
    assert "function startCreoConnectingOverlayGuard(" in script
    assert "function looksLikeCreoEmbeddedBrowser(" in script
    assert "Connecting to Creo…" in (ROOT / "src" / "creopdm" / "templates" / "base.html").read_text(
        encoding="utf-8"
    )
    assert "startCreoConnectingOverlayGuard()" in block
    assert "soft || hostedCreoJS()" in script
    assert "never plain Chrome/Edge" in script or "Never plain Chrome" in script
    docs_creo = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "Connecting to Creo…" in docs_creo
    assert "never in Chrome/Edge" in docs_creo
    # Soft sync must promote a stale Session offline pill when Creo.JS is live.
    soft_sync = _between(
        script, "function syncCreoSessionControlsFromBridge(", "if (soft)"
    )
    assert "promoteCreoPillWhenSessionLive()" in soft_sync
    assert "Do not probe" in soft_sync
    assert "probeCreoAgent" not in soft_sync
    promote_fn = _between(
        script, "function promoteCreoPillWhenSessionLive(", "async function refreshCreoStatusPill("
    )
    assert 'pill.textContent = "Creo: Connected"' in promote_fn
    assert "Agent offline" in promote_fn
    assert "hostedCreoJS()" in promote_fn

    # Status poll must survive soft boots and skip updates while soft-nav busy.
    assert "__creopdmStatusPollId" in block
    assert "Survive soft folder/product boots" in block
    poll_cb = script.split("window.__creopdmStatusPollId = window.setInterval(")[1].split("}, interval)")[0]
    assert "__creopdmSoftNavBusy" in poll_cb
    assert 'querySelector("#object-table")' in poll_cb

    # Pill refresh must not flash Session offline during soft nav / bridge flake.
    pill_fn = _between(script, "async function refreshCreoStatusPill(", "function showCreoSessionControls(")
    assert "__creopdmSoftNavBusy" in pill_fn
    assert "Transient bridge / agent flake" in pill_fn or "Transient bridge flake" in pill_fn
    assert "wasConnected" in pill_fn
    assert "Do not require a healthy agent probe" in pill_fn
    assert "Session offline" in pill_fn
    # Visibility must follow the same inSession used for the pill (after agent await).
    assert "applyCreoSessionOnlyVisibility(inSession)" in pill_fn
    assert "first-pass visibility used to disagree" in pill_fn
    # Association open mode must reuse a prefetched /health (not probe twice).
    assert "association mode used to /health twice" in pill_fn
    assert "prefetchedAgent !== undefined ? prefetchedAgent : await probeCreoAgent()" in pill_fn
    # Soft-nav click/popstate must survive soft boots (not pageAbort-bound).
    assert "__creopdmSoftNavBound" in script
    assert "__creopdmSoftNavApi" in script
    assert "origAddEventListener.call" in script
    assert "abort prior page listeners" in script or "no pageAbort signal" in script
    # Pill label is session state only (not “· Embedded” / “· OS”).
    assert 'pill.textContent = "Creo: Connected"' in pill_fn
    assert 'pill.textContent = "Creo: Session offline"' in pill_fn
    assert "· ${modeName}" not in pill_fn
    assert "modeName" not in pill_fn


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
    assert ">Open selected<" in html
    assert ">Open workspace<" in html
    assert ">Open selected…<" not in html
    assert ">Open workspace…<" not in html
    assert "Requires creopdm-agent" in html
    assert "Falls back to the vault folder" not in html
    assert "agentIsOnline" in script
    assert "canOpenWorkspace" in script
    assert "agentIsOnline()" in _between(
        script, "function syncToolbar(", "function setCheckinQueueCounts("
    )
    assert "productAllowsMutation" not in _between(
        script, "function syncToolbar(", "function setCheckinQueueCounts("
    )
    assert "mutationActionAllowed" not in _between(
        script, "function syncToolbar(", "function setCheckinQueueCounts("
    )
    assert "mutable &&" not in _between(
        script, "function syncToolbar(", "function setCheckinQueueCounts("
    )
    assert "product_ui.show_add" in html
    assert "product_ui.show_checkin" in html
    assert "product_ui.show_remove_vault" in html
    assert 'data-requires-mutation=' not in html
    assert "Start creopdm-agent on this PC to open the local workspace folder" in script
    assert "Opened the vault folder on the CreoPDM host" not in script
    assert "do not show the control" in (
        ROOT / "docs" / "user-interactions.md"
    ).read_text(encoding="utf-8")
    assert "function toggleOpenMenu" in script
    assert "closeOpenMenu" in script
    assert 'id="checkout-menu"' in html
    assert 'id="checkout-product-btn"' in html
    assert "Checkout product" in html
    assert 'id="undo-btn"' in html
    assert "Force Undo Checkout" in html
    assert 'id="force-undo-btn"' in html
    assert html.index('id="checkout-menu"') < html.index('id="undo-btn"')
    assert html.index('id="undo-btn"') < html.index('id="force-undo-btn"')
    assert html.index('id="force-undo-btn"') < html.index('id="checkin-menu"')
    assert "product_ui.show_checkout or product_ui.show_undo_checkout or product_ui.show_force_undo_checkout" in html
    assert "product_ui.show_undo_checkout" in html
    assert "product_ui.show_checkin" in html
    assert "can-force-undo-checkout" in script
    assert "canForceUndo" in script
    assert "roleCanCheckout" in script
    assert "roleCanCheckin" in script
    assert "/api/objects/batch/force-undo-checkout" in script
    assert "product_ui.show_checkout and entry.object_ids" in html
    assert 'id="checkin-menu"' in html
    assert 'id="checkin-product-btn"' in html
    assert 'id="checkin-btn"' in html
    assert html.index('id="checkin-product-btn"') < html.index('id="checkin-btn"')
    assert ">Check in product…<" in html
    assert ">Check in selected…<" in html
    assert "function beginCheckin" in script
    assert 'beginCheckin("product")' in script
    assert "function runCheckoutObjects" in script
    assert "pendingProductSaves" in script
    assert "productCheckoutCount" in script
    assert "pendingProductSaves > 0 || pendingProductNew > 0 || productCheckoutCount > 0" in script
    assert "Nothing to check in for this product" in script
    assert "data-checkoutable" in html
    assert "setCheckoutableCount" in script
    assert "canCheckoutProduct" in script
    assert "Nothing left to check out in this product" in script
    assert "pushLocalNewPathsToVault" in script
    assert "localOnlyCacheFiles" in _between(script, "async function beginCheckin(", "$(\"#checkin-cancel\")")
    assert "Preview is vault-only" in script
    assert "undoIds" in script
    assert "Releasing unchanged checkouts" in script
    assert "Undo checkout on" in script
    assert 'id="open-checkout-set-wd"' in base
    assert "Set Creo working directory" in base
    assert "open-checkout-wd-note" not in base
    assert "Uses the creopdm-agent cache folder on this PC so Creo opens and saves" not in base
    assert "open-checkout-set-wd" in script
    assert "data-can-copy-to-vault" in base
    assert "data-can-export-product" in base
    assert "data-can-export-objects" in base
    assert 'id="export-menu"' in html
    assert 'id="export-menu-btn"' in html
    assert ">Export ▾<" in html
    assert 'id="export-product-btn"' in html
    assert ">Export product…<" in html
    assert 'id="export-selected-btn"' in html
    assert ">Export selected…<" in html
    assert 'id="export-confirm-dialog"' in html
    assert "function confirmExportZip" in html or "function confirmExportZip" in script
    assert "async function beginExport" in script
    assert 'beginExport("product")' in script
    assert 'beginExport("selected")' in script
    assert "canExportProduct" in script
    assert "exportSelectedBtn.disabled" in script
    assert "/api/products/" in script and "/export" in script
    assert "${agentBase()}/export-zip" in script
    assert "Preparing export…" in script
    assert "window.confirm(" not in _between(
        script, "async function beginExport(mode) {", "exportProductBtn?.addEventListener"
    )
    assert "canCopyToVault" in script
    # agentBase() lives near boot top (auth headers); openPdmObjectFromUi follows promptOpenCheckout.
    assert "setWorkingDirectory" in _between(
        script, "async function openPdmObjectFromUi(", "async function probeCreoAgent("
    )
    prompt_open = _between(
        script, "function promptOpenCheckout(", "function checkoutBeforeOpen("
    )
    assert "Working directory only applies inside Creo's embedded browser" in prompt_open
    assert "skip a one-option dialog" in prompt_open
    assert "showWd && Boolean(wdBox?.checked)" in prompt_open or "showWd && Boolean(wdBox" in prompt_open
    # Creo.JS / CEF: instanceof HTMLDialogElement / dataset can fail; use showModal + getAttribute.
    assert "function isModalDialog(" in script
    assert "function dataFlag(" in script
    assert "function rowCheckoutKind(" in script
    assert "function rowOffersCheckout(" in script
    assert 'typeof el.showModal === "function"' in script
    assert "getAttribute" in _between(script, "function dataFlag(", "function userCanCheckout(")
    assert "Could not show the Open dialog" in prompt_open
    assert "instanceof HTMLDialogElement" not in prompt_open
    assert "Do not silently open when checkout was an option" in prompt_open
    open_ui = _between(script, "async function openPdmObjectFromUi(", "async function probeCreoAgent(")
    assert 'kind === "mine"' in open_ui
    assert "Do not trust data-owned alone" in open_ui
    # Recover from real checkout/undo items only — not the Checkout fly-up shell.
    user_can_co = _between(script, "function userCanCheckout(", "function userCanCheckin(")
    assert "#checkout-btn" in user_can_co
    assert "#undo-btn" in user_can_co
    assert "#checkout-menu" not in user_can_co
    assert 'querySelector("#checkout-btn, #checkout-product-btn, #undo-btn")' in user_can_co
    assert 'getAttribute("data-can-checkout")' in user_can_co
    sync_tb = _between(script, "function syncToolbar(", "function setCheckinQueueCounts(")
    assert "rowOffersCheckout(row)" in sync_tb
    assert "canCheckout && checkoutBtn" in sync_tb or "(canCheckout && checkoutBtn)" in sync_tb
    base_open = (ROOT / "src" / "creopdm" / "templates" / "base.html").read_text(encoding="utf-8")
    open_form = _between(base_open, 'id="open-checkout-dialog"', 'id="busy-overlay"')
    assert 'method="dialog"' not in open_form
    assert 'id="open-checkout-form"' in open_form
    docs_open = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "do not skip straight to Open because" in docs_open
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "only inside Creo’s embedded browser" in docs or "only inside Creo's embedded browser" in docs
    assert "opens immediately" in docs.lower() or "Open dialog" in docs
    assert "## 11. Export ▾" in docs
    assert "Export product…" in docs
    assert "Export selected…" in docs
    assert "greyed out until" in docs.lower() or "greyed out until" in docs
    assert "products.export" in docs
    assert "objects.export" in docs


def test_new_product_and_sidebar_collapse_handlers_present():
    script = _app_js()
    assert '$("#new-product-btn")?.addEventListener("click"' in script
    assert "showProductDialog(\"create\")" in script or 'showProductDialog("create")' in script
    assert "sidebarCollapseBtn?.addEventListener(\"click\"" in script
    assert "is-sidebar-collapsed" in script
    assert 'id="new-product-btn"' in APP_HTML.read_text(encoding="utf-8")
    html = APP_HTML.read_text(encoding="utf-8")
    # Empty-home create invite is only for products.create (not for Viewer, etc.).
    assert re.search(
        r"\{%\s*if\s+can_create_product\s*%\}[^%]*Create a product to start managing",
        html,
        re.DOTALL,
    )
    # Empty-product add invite is only when product_ui allows Add (role ∩ mutable).
    assert "product_ui.show_add" in html
    assert "Add a Creo model, PDF, or document to get started" in html
    assert re.search(
        r"\{%\s*elif\s+product_ui\.show_add\s*%\}[^%]*Add a Creo model",
        html,
        re.DOTALL,
    )
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
    # New file / Modified local: try logical tip after numbered .prt.1 fails.
    assert "creoLogicalFileName(shortDisk" in open_fn
    assert "logicalName !== shortDisk" in open_fn
    assert "numbered names alone often fail" in open_fn
    script = _app_js()
    meta = _between(script, "async function prepareLocalPathForMetadata(", "async function gatherCreoMetadataForFilename(")
    assert "openSpec.path" in meta
    assert "looksLikeLocalWindowsPath(materialized)" in meta


def test_mobile_browse_css_is_minimal():
    """Touch-phone browse mode hides chrome; narrow desktop/Creo window must not match."""
    css = APP_CSS.read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "pointer: coarse" in css
    assert "hover: none" in css
    assert "orientation: landscape" in css
    assert "max-height: 560px" in css
    # Do not trigger browse mode on width alone (Creo window can be narrow with a mouse).
    assert "@media (max-width: 640px)," not in css
    assert "@media (max-width: 640px) {" not in css
    mobile = css.split("pointer: coarse", 1)[1]
    assert "Hide Logout" in docs or "**Logout**" in docs
    assert 'a[href="/logout"]' in mobile
    assert ".topbar .status-cluster > :not(" in mobile
    assert ".topbar .status-cluster { display: none" not in mobile
    assert "#new-product-btn" in mobile
    assert ".product-settings" in mobile
    assert ".metrics" in mobile
    assert "footer.toolbar" in mobile
    assert "#detail-toolbar" in mobile
    assert "#object-table th:nth-child(n + 3)" in mobile
    assert "#checked-out-table th:nth-child(n + 3)" in mobile
    assert "#modified-table th:nth-child(1)" in mobile
    assert "#changes-table th:nth-child(1)" in mobile
    assert "#modified-table:has(.empty-row) thead" in mobile
    assert "#changes-table:has(.empty-row) thead" in mobile
    assert "table-layout: fixed" in mobile
    assert ".object-open" in mobile
    assert "pointer-events: none" in mobile
    assert "tr.folder-row" in mobile
    assert "only folders" in docs or "**only folders**" in docs or "Tap a **folder**" in docs
    assert "browse-only" in docs
    assert "**Name** and **Rev**" in docs
    assert "## 14. Mobile browse" in docs
    assert "`pointer: coarse`" in docs
    assert "**desktop** browser" in docs
    assert "Rotate the phone" in docs


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
    assert "<dt>Checked out by</dt>" in overview
    assert "<dt>Checked out</dt>" in overview
    assert "object.checkout_since" in overview
    assert 'local_time_pretty(object.checkout_since)' in detail
    assert 'title="Checked out {{ local_time_pretty(object.checkout_since) }}"' in detail
    assert "show_name" in overview
    assert "show_common" in overview
    assert "show_full" in overview
    assert "show_instance" in overview
    assert 'class="mono"' not in overview
    assert "<dt>Origin</dt>" not in overview
    assert "identity.origin" not in overview
    assert "Content hash" not in overview
    assert "h[:12]" not in overview
    assert "<dt>Date created</dt>" in overview
    assert "local_time_pretty(object.created_at)" in overview
    assert "local_time(object.updated_at) != local_time(object.created_at)" in overview
    assert "omits content hash" in docs
    assert "omits content hash and **Origin**" in docs
    assert "Date created" in docs and "Date modified" in docs
    assert "hide Date modified when it matches Date created" in docs or "same as Date created" in docs
    assert "show content hash on Overview" in docs
    assert "show **Origin**" in docs
    assert ".detail .filename-cell" in css
    assert "font-family: inherit" in css
    assert "text-transform: uppercase" in css
    assert "<dt>Number</dt>" not in overview
    assert "<dt>Name</dt>" in overview
    assert "<dt>Model type</dt>" in overview
    assert "<dt>Subtype</dt>" in overview
    assert "<dt>Model role</dt>" not in overview
    assert "identity.model_type" in overview
    assert "is_top_level_assembly" in overview
    assert "ASSEMBLY (Top Level)" in overview
    assert "(Top Level)" in detail
    assert "Top Level" in docs
    assert "identity.model_role" in overview
    assert "Model type" in docs and "**Subtype**" in docs
    assert "label the model **Name**" in docs or "model **Name**" in docs
    assert "label the model identity as Number" in docs
    assert "skips duplicate identity fields" in docs
    assert "Overview → Checkout" in docs or "Checked out by" in docs
    assert "hide who/when for an active checkout" in docs
    assert "no mixed monospace" in docs
    assert "regular ink color" in docs
    assert "accent-colored hyperlinks" in docs
    assert ".detail a" in css
    assert "color: var(--ink)" in css
    # Admin Add user / Add role / etc. are <a class="btn btn-primary"> inside .detail —
    # must keep white text (`.detail a` alone would force ink).
    assert ".detail a.btn-primary" in css
    assert "color: #fff" in _between(css, ".detail a.btn-primary", ".detail a.btn-danger")
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


def test_details_where_used_tab_gated_on_creo_models():
    """Where Used on Details only when show_where_used (Settings → Creo Models)."""
    detail = (ROOT / "src" / "creopdm" / "templates" / "object_detail.html").read_text(
        encoding="utf-8"
    )
    pages = (ROOT / "src" / "creopdm" / "api" / "pages.py").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "{% if show_where_used %}" in detail
    assert 'data-tab="where-used"' in detail
    assert "matches_cad_models" in pages
    assert "cad_models_extensions()" in pages
    assert "show_where_used" in pages
    assert "Where Used** only for files whose extension is in **Settings → Creo Models" in docs
    assert "Show Where Used for Documents" in docs


def test_details_bom_qty_renders_whole_numbers():
    """BOM / Where Used Qty must use bom_qty so floats do not show as 1.0."""
    detail = (ROOT / "src" / "creopdm" / "templates" / "object_detail.html").read_text(
        encoding="utf-8"
    )
    pages = (ROOT / "src" / "creopdm" / "api" / "pages.py").read_text(encoding="utf-8")
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "|bom_qty" in detail
    assert 'filters["bom_qty"]' in pages or "filters['bom_qty']" in pages
    assert "function formatBomQty" in script
    assert "formatBomQty(row.quantity" in script
    assert "whole numbers" in docs and "1.0" in docs


def test_history_revert_only_for_older_versions():
    """Revert control appears only with older history; current row is not reversible."""
    detail = (ROOT / "src" / "creopdm" / "templates" / "object_detail.html").read_text(
        encoding="utf-8"
    )
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    css = (ROOT / "src" / "creopdm" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert "{% if product_ui.show_revert and history|length > 1 %}" in detail
    assert 'id="revert-version-btn"' in detail
    assert 'class="btn btn-danger" id="revert-version-btn"' in detail or 'btn btn-danger' in detail
    assert "red like Remove" in docs
    assert 'id="detail-toolbar"' in detail
    assert 'id="detail-tab-title"' in detail
    assert 'id="detail-tab-title-text"' in detail
    assert ">Details</h1>" in detail
    assert "hidden" not in detail.split('id="detail-tab-title"', 1)[1].split(">", 1)[0]
    assert 'id="detail-open-btn"' in detail
    assert 'class="btn detail-open-btn"' in detail or "detail-open-btn" in detail
    assert 'class="detail-title-row"' in detail
    assert 'class="detail-filename"' in detail
    css = (ROOT / "src" / "creopdm" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    title_row = _between(css, ".detail-title-row {", ".detail-head h1,")
    assert "flex-wrap: nowrap" in title_row
    assert "width: fit-content" in title_row
    assert "flex-wrap: wrap" not in title_row
    assert 'data-can-checkout=' in detail.split('id="detail-open-btn"', 1)[1].split(">", 1)[0]
    assert 'data-owned=' in detail.split('id="detail-open-btn"', 1)[1].split(">", 1)[0]
    assert 'id="detail-open-btn"' in script or '#detail-open-btn' in script
    assert "openPdmObjectFromUi" in script
    assert "Open…** button beside" in docs or "Open…** button beside it" in docs
    assert "omit **Open…** next to the Details file name" in docs
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
    assert "canCheckinProduct" not in detail_toolbar
    assert "never **Check In ▾**" in docs or "never **Check In" in docs
    assert "Check In stays on the Files page" in docs
    assert "Revert to selected…** only" in docs or "Revert to selected… only" in docs
    assert "You do not need to Check In afterward" in script
    assert "confirmByProductName({" in script
    assert 'title: `Revert to ${display}`' in script
    assert 'submitLabel: "Revert"' in script
    assert 'data-product-name="{{ product.name }}"' in detail
    assert '$("#revert-version-btn")?.dataset.productName' in script
    revert_click = _between(
        script,
        '$("#revert-version-btn")?.addEventListener("click"',
        'document.querySelectorAll(".tabs .tab")',
    )
    assert "confirmByProductName" in revert_click
    assert "window.confirm" not in revert_click
    assert "tryEraseModelsFromCreoSession" in revert_click
    assert "creoYieldForDeferredErase" in revert_click
    assert "eraseSessionModelsByNames" in script
    assert "CREO_REVERT_SESSION_HINT" in revert_click
    assert "File → Erase" in revert_click
    assert "Removed from Creo session" in revert_click
    # Erase before rematerialize so locked .N leftovers can be trashed.
    assert revert_click.index("tryEraseModelsFromCreoSession") < revert_click.index(
        "materializeViaAgent"
    )
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
    assert "rename the vault tip back to an old `.prt.N`" in docs
    assert "leave you checked out with a Check In prompt" in docs
    assert "type the **exact** product name" in docs
    assert "plain browser `confirm`" in docs
    assert "History **Revert to selected…**" in docs
    assert "no Check In prompt" in docs
    assert "keep old geometry in memory" in docs
    assert "File → Erase" in docs
    assert "pretend Creo already shows the restored geometry" in docs
    assert "function tryEraseModelsFromCreoSession" in script
    assert "function tryEraseRevertedModelFromCreo" in script
    assert "allowUndisplayed: false" in script
    assert "bottom toolbar" in docs.lower() or "at the bottom" in docs.lower()
    assert "Open the file **Details** page on the **Overview** tab" in docs
    assert "open the history tab by default" in docs.lower()
    assert "Creo stays Connected" in docs or "stays Connected" in docs
    html = APP_HTML.read_text(encoding="utf-8")
    assert 'id="history-btn"' in html
    assert "Overview and History" in html
    assert ">Details</button>" in html
    assert ">History</button>" not in html
    assert 'data-detail="/products/{{ selected.uuid }}/objects/{{ obj.uuid }}"' in html
    assert 'data-detail="/products/{{ selected.uuid }}/objects/{{ obj.uuid }}#history"' not in html
    assert "Details page defaults to Overview" in script
    href_fn = _between(script, "function rowHistoryHref(", "document.querySelector(\"#object-table\")")
    assert "return `/products/${productId}/objects/${uuid}`;" in href_fn
    assert "objects/${uuid}#history" not in href_fn
    # Details / double-click must soft-nav (leavePage) — hard location.href killed Creo.JS.
    dbl = _between(script, "function onFileTableDblclick(", "function rowHistoryHref(")
    assert "leavePage(href)" in dbl
    assert "window.location.href = href" not in dbl
    hist_click = _between(
        script,
        'historyBtn?.addEventListener("click"',
        "function expectedProductName(",
    )
    assert "leavePage(href)" in hist_click
    assert "window.location.href = href" not in hist_click
    assert "Soft-nav like folders" in hist_click or "hard reload kills Creo" in hist_click.lower()


def test_files_search_survives_details_and_back():
    """Search + Details / History / Back must not wipe the product-wide query."""
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert 'const LIST_SEARCH_KEY = "creopdmListSearch"' in script
    assert "function persistListSearchState(" in script
    assert "function restoreListSearchState(" in script
    soft = _between(script, "function softNavigate(", "function leavePage(")
    assert "persistListSearchState()" in soft
    leave = _between(script, "function leavePage(", "function reloadPage(")
    assert "persistListSearchState()" in leave
    assert "void restoreListSearchState()" in script
    assert "searchInput.value = query" in script
    assert "await searchAllFolders(query)" in script
    assert "Keep the search text" in docs
    assert "browser **Back** button" in docs
    assert "Clear search or show the empty folder list just because you opened Details" in docs


def test_search_form_only_on_files_tab():
    """Search box is for the Files list — hide it on other product list tabs."""
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    sync = _between(script, "function syncSearchFormVisibility(", "searchInput?.addEventListener")
    assert 'form.hidden = activeListTab() !== "files"' in sync
    assert "syncSearchFormVisibility()" in script
    tab_click = _between(
        script,
        'document.querySelectorAll(".tabs .tab").forEach((tab) => {',
        "let whereUsedLoaded = false;",
    )
    assert "syncSearchFormVisibility()" in tab_click
    assert "Type in Search (Files tab only)" in docs
    assert "show Search only on **Files**" in docs
    assert "leave Search visible on Checked out / Modified / New files" in docs


def test_soft_nav_reloads_app_js_when_cache_bust_changes():
    """After deploy, soft-nav must not keep a stale in-memory app.js open path."""
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    soft = _between(script, "function softNavigate(", "function leavePage(")
    assert "function loadUpdatedAppJs(" in script
    assert "loadUpdatedAppJs(nextAppJs)" in soft
    assert 'script[src*="/client/app.js"]' in soft
    assert 'getAttribute("data-creo-open-mode")' in soft
    assert "__creopdmSkipAutoBoot" in script
    assert 'getAttribute("data-creo-open-mode")' in _between(
        script, "function creoOpenMode(", "function creoExternalBridge("
    )
    local_open = _between(script, "async function openLocalCacheRelative(", "async function openPdmObject(")
    assert "Waiting for Creo.JS…" in local_open
    assert "do not open via Windows file association from the embedded browser" in local_open
    assert "pick up the new `app.js`" in docs
    assert "stale Windows-association path" in docs


def test_list_tab_survives_details_and_back():
    """Files / Checked out / Modified / New files must restore after Details → Back."""
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert 'const WATCH_KEY = "creopdmWatchRestore"' in script
    assert "LIST_RESTORE_TABS" in script
    assert "function persistListTabState(" in script
    assert '"modified"' in script and '"changes"' in script
    soft = _between(script, "function softNavigate(", "function leavePage(")
    assert "persistListTabState()" in soft
    leave = _between(script, "function leavePage(", "function reloadPage(")
    assert "persistListTabState()" in leave
    persist = _between(script, "function persistListTabState(", "function softNavigate(")
    assert "LIST_RESTORE_TABS.has" in persist
    assert 'querySelector("#object-table")' in persist
    restore = _between(script, "function restoreWatchView(", "function watchIdleMinutes(")
    assert "LIST_RESTORE_TABS.has" in restore
    assert "do not consume WATCH_KEY there" in restore
    assert "!isListPage" in restore
    assert "restoreWatchView()" in script
    assert "persistListTabState(name)" in script
    assert "keep the Files list tab you were on" in docs
    assert "reset to the **Files** tab when you left from **Modified**" in docs


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
    # Export selected + Check in selected stay greyed with a hover reason.
    assert "**Export selected…** and **Check in selected…**" in docs
    assert "function checkinSelectedHoverTitle(" in script
    assert "checkinBtn.hidden = false" in sync
    assert "checkinBtn.disabled = !canCheckin" in sync
    assert "content matches the vault tip" in script
    assert "keep **Check in selected…** visible but **greyed**" in docs
    # Set Working Directory: hide outside Creo / when disconnected; Details always hides it.
    apply_creo = _between(
        script, "function applyCreoSessionOnlyVisibility(", "function promoteCreoPillWhenSessionLive("
    )
    assert "Set Working Directory: only when inside Creo" in apply_creo
    assert "el.hidden = !inSession" in apply_creo
    assert 'btn.id === "set-creo-dir-btn"' in apply_creo
    assert 'Boolean($("article.detail"))' in apply_creo
    soft = _between(script, "function syncCreoSessionControlsFromBridge(", "if (soft)")
    assert "applyCreoSessionOnlyVisibility(inSession)" in soft
    assert 'btn.id === "set-creo-dir-btn"' in apply_creo
    assert "On the file **Details** page" in docs
    assert "every tab, including History" in docs
    assert "Check In stays on the Files page" in docs
    assert "show only inside creo" in docs.lower()
    assert "Set Working Directory must not disagree" in docs or "disagree with the status pill" in soft


def test_files_context_menu_download_to_workspace():
    """Right-click selected rows: toolbar-matched actions; hide when not possible."""
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    css = APP_CSS.read_text(encoding="utf-8")
    assert "function onFileTableContextMenu(" in script
    assert 'addEventListener("contextmenu", onFileTableContextMenu)' in script
    assert "function openFilesContextMenu(" in script
    assert "function filesContextMenuCapabilities(" in script
    assert "function downloadSelectedToWorkspace(" in script
    assert "function runFilesContextMenuAction(" in script
    assert "Download selected to workspace" in script
    assert 'label: "Open selected"' in script
    assert "Open selected…" not in script
    assert ">Details<" in script or '"Details"' in script
    assert "Checkout selected" in script
    assert "Undo Checkout" in script
    assert "Check in selected…" in script
    assert "Export selected…" in script
    assert 'dataset?.canView === "1"' in script
    caps = _between(script, "function filesContextMenuCapabilities(", "function ensureFilesContextMenu(")
    assert "selectedOpenSpec()" in caps
    assert "rowHistoryHref(one)" in caps
    assert "selectionCanCheckin(selected)" in caps
    assert "canAddSelected" in caps
    assert "selectionIsAddOnly(selected)" in caps
    assert "!addOnly" in caps
    assert "alreadyLocal" in caps
    assert 'dataset.localCache === "1"' in caps
    assert "!alreadyLocal" in caps
    assert 'dataset.canCheckout === "1"' in caps
    assert 'dataset.owned === "1"' in caps
    assert "canUndo" in caps
    assert "canExportObjects" in caps
    assert "canDiscardLocal" in caps
    assert "discardLocalBtn" in caps
    assert "isNewFileQueueRow(row) && row.dataset.localCache === \"1\"" in caps
    docs_ctx = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "already local-workspace tips" in docs_ctx or "already in the local workspace" in docs_ctx
    ensure = _between(script, "function ensureFilesContextMenu(", "function closeFilesContextMenu(")
    assert 'id: "files-context-discard-local"' in ensure
    assert 'action: "discard-local"' in ensure
    assert "Remove from Workspace…" in ensure
    html = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    assert 'id="discard-local-btn"' in html
    assert ">Remove from Workspace…</button>" in html
    open_menu = _between(script, "function openFilesContextMenu(", "async function downloadSelectedToWorkspace(")
    assert "openItem.hidden = !caps.canOpen" in open_menu
    assert "detailsItem.hidden = !caps.canDetails" in open_menu
    assert "checkoutItem.hidden = !caps.canCheckout" in open_menu
    assert "undoItem.hidden = !caps.canUndo" in open_menu
    assert "addSelectedItem.hidden = !caps.canAddSelected" in open_menu
    assert "checkinItem.hidden = !caps.canCheckin" in open_menu
    assert "downloadItem.hidden = !caps.canDownload" in open_menu
    assert "exportItem.hidden = !caps.canExport" in open_menu
    assert "discardLocalItem.hidden = !caps.canDiscardLocal" in open_menu
    run = _between(script, "function runFilesContextMenuAction(", "function onFileTableContextMenu(")
    assert "openBtn?.click()" in run
    assert "historyBtn?.click()" in run
    assert "checkoutBtn?.click()" in run
    assert "undoBtn?.click()" in run
    assert 'action === "add-selected"' in run
    assert "checkinBtn?.click()" in run
    assert "exportSelectedBtn?.click()" in run
    assert 'action === "discard-local"' in run
    assert "discardLocalBtn?.click()" in run
    download = _between(
        script,
        "async function downloadSelectedToWorkspace(",
        "function runFilesContextMenuAction(",
    )
    assert "/api/objects/batch/checkout" not in download
    assert "Start creopdm-agent" in download
    assert ".files-context-menu" in css
    assert "**Right-click** a file or folder row" in docs
    assert "**Open selected**" in docs
    assert "**Open workspace**" in docs
    assert "not on **Open selected** / **Open workspace**" in docs
    assert "**Details**" in docs
    assert "**Checkout selected**" in docs
    assert "**Undo Checkout**" in docs
    assert "**Add selected…**" in docs
    assert "**Export selected…**" in docs
    assert "**Remove from Workspace…**" in docs
    assert "**hide** each item when that action is not possible" in docs
    assert "without `objects.view`" in docs or "`objects.view`" in docs


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
    assert 'classList.contains("folder-row")' in apply_sel
    assert "foldersSelecting" in apply_sel
    assert "Folder selection follows the Folders pill only" in apply_sel
    assert "markRowSelected(row, foldersSelecting && !rowIsHidden(row))" in apply_sel
    vis = _between(script, "function applyMetricVisibility(", "function applyMetricSelection(")
    assert "fileTypeFilterOn" in vis
    assert "foldersFilterOn" in vis
    css = APP_CSS.read_text(encoding="utf-8")
    assert "cursor: default" in css.split(".folder-row {", 1)[1].split("}", 1)[0]
    assert "width: fit-content" in css


def test_folders_metric_pill_before_files():
    """Folders pill sits before Files; selects folder rows; stays visible at 0."""
    html = APP_HTML.read_text(encoding="utf-8")
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert 'data-filter="folders"' in html
    assert html.index('data-filter="folders"') < html.index('data-filter="files"')
    assert "status.folders" in html
    assert "{% if not status.folders %}" not in html
    assert "syncFoldersMetricVisibility" not in script
    chip = _between(script, "function onMetricChip(", "document.querySelector(\"#metric-filters\")")
    assert 'key === "folders"' in chip
    assert 'other !== "folders"' in chip
    assert "setMetricMode(foldersBtn, \"filter\")" not in chip
    assert "listedFolderRows().length" not in chip
    restore = _between(script, "function restoreStoredFilters(", "function clearProductViewStorage(")
    assert "setMetricMode(foldersBtn, \"filter\")" not in restore
    assert "Click **Folders**" in docs
    assert "including **0**" in docs
    assert "Hide the **Folders** pill when the count is 0" in docs
    assert "stays **on** together with **Files**" in docs
    assert "does not force Folders back on" in docs
    assert "turning **Folders** or **Files** off **stays off**" in docs
    assert "latest pill state wins" in docs
    assert "turning **Folders** off **unselects** folder rows" in docs or "unselects** folder rows" in docs
    assert "hides and unselects** folders" in docs
    assert "re-activate Folders or Files after navigation" in docs
    read_filters = _between(script, "function readStoredFilters(", "function writeStoredFilters(")
    assert 'filterStoreKey("_last")' in read_filters
    assert read_filters.index('filterStoreKey("_last")') < read_filters.index(
        "filterStoreKey(currentFolder())"
    )
    apply_sel = _between(script, "function applyMetricSelection(", "function metricSelectionActive(")
    assert "Folder selection follows the Folders pill only" in apply_sel
    vis = _between(script, "function applyMetricVisibility(", "function applyMetricSelection(")
    assert "fileTypeFilterOn && !foldersFilterOn" in vis


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
    confirm = _between(script, "function confirmByProductName(", "function workspacePathsForRemovedObjects(")
    assert "Type the product name exactly to confirm." in confirm
    assert "typed !== expected" in confirm

    # Check In comment required on dialog
    assert 'id="checkin-comment"' in html
    assert "required" in html.split('id="checkin-comment"', 1)[1].split(">", 1)[0]

    # Remove from Product enablement includes empty folders (V2 / N16)
    sync = _between(script, "function syncToolbar(", "function setCheckinQueueCounts(")
    assert "Boolean(removeBtn)" in sync
    assert "ids.length > 0 || folderPaths.length > 0" in sync
    # Ellipsis + red: items that open danger-confirm.
    assert ">Remove from Product…<" in html
    assert ">Remove from Vault…<" in html
    assert ">Purge workspace…<" in html
    assert 'class="toolbar-menu-item is-danger" role="menuitem" id="purge-versions-btn"' in html
    assert 'class="toolbar-menu-item is-danger" role="menuitem" id="purge-workspace-btn"' in html
    docs_rm = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "### Remove from Product…" in docs_rm
    assert "### Remove from Vault…" in docs_rm
    assert "### Purge workspace…" in docs_rm


def test_modified_metric_pill_left_of_checked_out():
    """Modified pill filters/selects dirty owned files; sits left of Checked out."""
    html = APP_HTML.read_text(encoding="utf-8")
    assert 'data-filter="modified"' in html
    assert html.index('data-filter="modified"') < html.index('data-filter="checked_out"')
    assert "> Modified</button>" in html.replace("\n", "")
    script = _app_js()
    match = _between(script, "function rowMatchesMetric(", "function rememberMetricCounts(")
    assert 'key === "modified"' in match
    assert "pendingCheckinIds.has" in match
    assert "function isStateMetric(" in script
    assert 'key === "checked_out" || key === "modified"' in script
    assert "activeStateMetricKeys" in script
    # Regression: files-tab counts must recount modified after agent probes
    # (SSR folderCount alone stayed 0 while STATE already showed Modified).
    counts_fn = _between(script, "function updateMetricCounts(", "function refreshTabMetrics(")
    assert "isStateMetric(key)" in counts_fn
    assert "rowMatchesMetric(row, key)" in counts_fn
    remember = _between(script, "function rememberPendingCheckinIds(", "function syncModifiedStateLabels(")
    assert "updateMetricCounts()" in remember
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "Click **Modified**" in docs
    assert "pill count matches rows shown as Modified" in docs

def test_local_only_new_files_prefer_highest_creo_save():
    """New files (local) must show test-part.prt.2, not a leftover .prt.1."""
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    body = _between(script, "function localOnlyCacheFiles(", "function newerLocalCacheSaves(")
    assert "bestByFamily" in body
    assert "creoSaveNumber(filename)" in body
    assert "saveNumber > prev.saveNumber" in body
    assert "Collapse Creo siblings to the highest" in body
    assert "**highest** save" in docs
    assert "test-part.prt.2" in docs
    assert "leftover `test-part.prt.1`" in docs


def test_newer_local_cache_matches_flat_save_for_nested_vault_path():
    """Regression: older flat agent caches + nested vault paths still detect Modified."""
    script = _app_js()
    body = _between(script, "function newerLocalCacheSaves(", "async function countLocalNewWorkspaceFiles(")
    assert "bestByBasename" in body
    assert "vaultBasenameCounts" in body
    assert "vaultBasenameCounts.get(base) || 0) === 1" in body
    assert "Older flat agent caches" in body


def test_agent_cache_matches_legacy_underscore_folder_paths():
    """Vault 'from ptc' must match older agent-cache 'from_ptc' (not count as New)."""
    script = _app_js()
    assert "function agentCacheSafeRelativePath(" in script
    assert "function agentCacheSafeSegment(" in script
    mark = _between(script, "function markKnownPath(", "async function loadKnownWorkspacePaths(")
    assert "agentCacheSafeRelativePath(path)" in mark
    body = _between(script, "function newerLocalCacheSaves(", "async function countLocalNewWorkspaceFiles(")
    assert "agentCacheSafeRelativePath(vaultRel)" in body
    assert "agentCacheSafeRelativePath(rel)" in body
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "from_ptc" in docs


def test_newer_local_cache_detects_same_save_content_replace_by_hash():
    """Modified requires content-hash mismatch — never .N / size / mtime alone."""
    script = _app_js()
    body = _between(script, "function newerLocalCacheSaves(", "async function countLocalNewWorkspaceFiles(")
    assert "needsHash" in body
    assert "current_version?.content_hash" in body
    assert "hashAgentCachePaths" in body
    assert "async function resolveNewerLocalCacheSaves(" in body
    assert "newer_save: newerSave" in body
    assert "Content hash must differ" in body
    assert "if (newerSave)" not in body
    assert "rows.push(row)" not in body
    assert "sizeDiffers" not in body
    assert "Math.max(" in body
    assert "current_version?.filename" in body
    assert "local.saveNumber < vaultNumber" in body
    # Prefer .creopdm_cache_index.json hash from GET /files (size-verified).
    assert "indexHash" in body
    assert "local.item.content_hash" in body
    assert ".creopdm_cache_index.json" in body
    assert "needHashPaths" in body
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert ".creopdm_cache_index.json" in docs
    assert "proves the file is real" in docs


def test_refresh_pending_clears_sticky_modified_locally():
    """Rematerialized matching tip must clear data-modified-locally, not re-seed it."""
    script = _app_js()
    body = _between(script, "async function refreshPendingCheckinIds(", "function rowHasCheckinWork(")
    assert "do not seed the final pending set from" in body
    assert 'row.dataset.modifiedLocally = pendingCheckinIds.has(String(id)) ? "1" : "0"' in body
    # Final pending ids come from preview/agent/queue — not from existing DOM flags.
    assert "const ids = [];" in body
    assert "ssrIds" in body
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "leave Modified stuck after a later refresh proves the tip matches" in docs


def test_checkin_dialog_keeps_local_tip_name():
    """After push, dialog must still show shaft.prt.2 — not strip to vault logical tip."""
    script = _app_js()
    html = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    assert "tipNameForCheckin" in script
    assert "Prefer the on-disk tip the user saw" in script
    assert "Prefer the local Creo tip" in script
    assert "tipNameForCheckin(id, pendingNames[index])" in script
    assert 'id="checkin-vault-tip"' in html
    assert "vault tip will be" in script
    assert "Creo .N stripped" in script
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "strip the Creo `.N` in the Check In dialog" in docs


def test_checkin_success_rematerializes_and_drops_local_n():
    """Clean check-in must rematerialize logical tip and trash leftover .prt.2 locally."""
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "function rematerializeCheckedInLocalTips" in script
    assert "function checkedInItemsFromResult" in script
    submit = _between(
        script,
        'checkinForm?.addEventListener("submit"',
        'historyBtn?.addEventListener("click"',
    )
    assert "await rematerializeCheckedInLocalTips(result)" in submit
    assert "applyCheckedInResult(result)" in submit
    assert submit.index("await rematerializeCheckedInLocalTips(result)") > submit.index(
        "applyCheckedInResult(result)"
    )
    # Check-in must not wipe open Creo models (product check-in used to erase undos).
    assert "tryEraseModelsFromCreoSession" not in submit
    assert "removed from Creo session" not in submit
    helper = _between(
        script,
        "async function rematerializeCheckedInLocalTips(",
        "function whenCreoJSReady(",
    )
    assert "tryEraseModelsFromCreoSession" not in helper
    assert "replace_newer: true" in helper
    assert '"/api/creo/open"' in helper or "'/api/creo/open'" in helper
    assert "materializeViaAgent" in helper
    assert "Updating local workspace" in helper
    items_fn = _between(
        script,
        "function checkedInItemsFromResult(",
        "function checkedInObjectIdsFromResult(",
    )
    assert 'status !== "checked_in"' in items_fn or "status !== 'checked_in'" in items_fn
    assert "trash higher local `.N` leftovers" in docs
    assert "leave `shaft.prt.2`" in docs
    assert "keep Creo windows open" in docs
    assert "Erase unrelated open models" in docs


def test_pending_from_status_requires_hash_for_dirty_tip():
    """Git dirty tip / higher .N with matching content_hash must not appear as Modified."""
    text = (ROOT / "src" / "creopdm" / "services" / "workspace_service.py").read_text(
        encoding="utf-8"
    )
    pending = _between(text, "def _pending_from_status(", "def product_checkin_queue(")
    assert "_file_modified" in pending
    assert "if not self._file_modified(path, obj):" in pending
    assert "not newer_save and not content_changed" not in pending
    workspace = _between(text, "def pending_workspace_save(", "def _pending_from_status(")
    assert "if not modified:" in workspace
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "content hash** differs from the vault tip" in docs

def test_admin_hub_panel_fills_full_width():
    """max-width on .admin-hub itself left body --bg showing beside the page."""
    css = APP_CSS.read_text(encoding="utf-8")
    hub = _between(css, ".admin-hub {", ".admin-tile-grid {")
    assert "max-width: none" in hub
    assert "max-width: 48rem" not in hub
    # Hub pages (Admin + Utilities) stretch full width; do not re-cap the tile grid.
    assert ".admin-hub .admin-tile-grid" in css
    hub_grid = _between(css, ".admin-hub .admin-tile-grid {", "}")
    assert "max-width: none" in hub_grid
    grid = _between(css, "\n.admin-tile-grid {", ".admin-tile {")
    assert "display: grid" in grid
    assert "max-width: 48rem" not in grid
    admin = (ROOT / "src" / "creopdm" / "templates" / "admin.html").read_text(encoding="utf-8")
    assert "admin-hub" in admin
    assert 'class="detail settings-page admin-page admin-hub"' in admin or "admin-hub" in admin
    assert ">System Settings</a>" in admin
    assert ">Settings</a>" not in admin
    assert ">Utilities</a>" in admin
    assert 'href="/admin/utilities"' in admin
    assert 'class="admin-tile is-disabled"' in admin
    assert ">Audit</span>" in admin
    assert ">AI</span>" in admin
    assert "Coming soon: review sign-ins" in admin
    assert "Coming soon: configure AI help" in admin
    assert ".admin-tile.is-disabled" in css
    utilities = (ROOT / "src" / "creopdm" / "templates" / "admin_utilities.html").read_text(
        encoding="utf-8"
    )
    assert "<h1>Utilities</h1>" in utilities
    assert "admin-hub" in utilities
    assert 'href="/admin/utilities/email-all"' in utilities
    assert 'href="/admin/utilities/compact"' in utilities
    assert 'href="/admin/utilities/delete-products"' in utilities
    assert 'href="/admin/utilities/health"' in utilities
    assert "Email all users, compact vault history, Delete products, and server health checks." in utilities
    assert 'action="/admin/utilities/email-all"' not in utilities
    assert "Disk space" not in utilities
    email_util = (
        ROOT / "src" / "creopdm" / "templates" / "admin_utilities_email.html"
    ).read_text(encoding="utf-8")
    assert 'action="/admin/utilities/email-all"' in email_util
    compact_util = (
        ROOT / "src" / "creopdm" / "templates" / "admin_utilities_compact.html"
    ).read_text(encoding="utf-8")
    assert 'id="utilities-compact-vault-form"' in compact_util
    delete_util = (
        ROOT / "src" / "creopdm" / "templates" / "admin_utilities_delete_products.html"
    ).read_text(encoding="utf-8")
    assert 'id="utilities-delete-products-form"' in delete_util
    product_form = (ROOT / "src" / "creopdm" / "templates" / "admin_product_form.html").read_text(
        encoding="utf-8"
    )
    assert "Remove product" not in product_form
    assert '}/delete"' not in product_form
    assert 'href="/admin/utilities/delete-products"' in product_form
    health = (ROOT / "src" / "creopdm" / "templates" / "admin_utilities_health.html").read_text(
        encoding="utf-8"
    )
    assert "Disk space" in health
    assert ">CPU<" in health or "<h2>CPU" in health
    assert "utilities-cpu-meter" in health
    assert "status.cpu.percent_label" in health
    # System volume row is {{ row.label }} from the API; template gates free/used on kind.
    assert "row.kind == 'volume'" in health or 'row.kind == "volume"' in health
    assert "size of that folder only" in health
    assert "<strong>System</strong>" in health
    assert 'href="/admin/utilities/logs"' in health
    assert "row.label == 'Logs'" in health or 'row.label == "Logs"' in health
    logs_tmpl = (ROOT / "src" / "creopdm" / "templates" / "admin_utilities_logs.html").read_text(
        encoding="utf-8"
    )
    assert "utilities-log-body" in logs_tmpl
    assert ".utilities-log-body" in css
    assert ".utilities-status-ok" in css
    assert ".utilities-cpu-meter" in css
    assert ".utilities-status-cpu-hot" in css
    script = _app_js()
    # Sync compact / delete POSTs can take a while — show busy until the response navigates.
    assert 'form.id === "utilities-compact-vault-form"' in script
    assert 'form.id === "utilities-delete-products-form"' in script
    assert "Compacting vault history for ${label}" in script
    assert "Deleting product ${label}" in script
    settings = (ROOT / "src" / "creopdm" / "templates" / "settings.html").read_text(encoding="utf-8")
    assert "<h1>System Settings</h1>" in settings
    assert "admin-hub" in settings
    assert 'href="/settings/{{ tile.slug }}"' in settings or 'href="/settings/' in settings
    assert "settings_tiles" in settings
    hub = (ROOT / "src" / "creopdm" / "settings_hub.py").read_text(encoding="utf-8")
    assert 'slug="availability"' in hub
    assert 'slug="database"' in hub
    assert hub.index('slug="availability"') < hub.index('slug="open"')
    assert hub.index('slug="open"') < hub.index('slug="vault"')
    assert hub.index('slug="types"') < hub.index('slug="ignored-files"')
    section = (ROOT / "src" / "creopdm" / "templates" / "settings_section.html").read_text(
        encoding="utf-8"
    )
    assert 'id="settings-form"' in section
    assert "settings_partials/" in section
    assert "Back to System Settings" in section
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "System Settings" in docs
    assert "hub of short tiles" in docs
    assert "Utilities" in docs
    assert "utilities.access" in docs
    assert "folder’s used size" in docs or "folder" in docs
    assert "Audit** and **AI**" in docs or "**Audit** and **AI**" in docs
    assert "Compacting vault history" in docs
    assert "four hub tiles" in docs
    assert "Delete products" in docs
    script = _app_js()
    assert "Hub section pages only send fields present" in script
    assert 'settingsForm.querySelector(\'[name="site_availability"]\')' in script


def test_workspace_poll_pauses_after_idle_setting():
    """File-list watch stops after configured idle minutes until user activity."""
    script = _app_js()
    body = _between(script, "function watchIdleMinutes(", "async function pollWorkspaceWatch(")
    assert "function isWatchIdle(" in body
    assert "function noteUserActivity(" in body
    assert "return isWatchIdle()" in body
    settings = (
        ROOT / "src" / "creopdm" / "templates" / "settings_partials" / "agent.html"
    ).read_text(encoding="utf-8")
    assert 'name="workspace_poll_idle_minutes"' in settings
    assert "Pause refresh after idle" in settings
    base = (ROOT / "src" / "creopdm" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "data-workspace-poll-idle-minutes=" in base
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "Pause refresh after idle" in docs
    assert "Stop file-list / agent workspace polling" in docs
    cfg = (ROOT / "src" / "creopdm" / "config.py").read_text(encoding="utf-8")
    assert "workspace_poll_idle_minutes: int = 10" in cfg


def test_workspace_poll_only_on_files_list_page():
    """Regression: Details/Admin still expose product toolbar ids — do not poll there."""
    script = _app_js()
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    watch_setup = _between(script, "function watchPaused(", "async function pollWorkspaceWatch(")
    assert "isListPage" in watch_setup
    assert 'Files list only' in watch_setup or "Files list only" in watch_setup
    poll_fn = _between(script, "async function pollWorkspaceWatch(", "if (watchProductId)")
    assert 'document.querySelector("#object-table")' in poll_fn
    assert "isListPage && pendingProductId" in script
    assert "Stop workspace-watch / file-list change polling" in docs
    assert "Keep polling for list/check-in changes while Admin" in docs
    assert "do not probe creopdm-agent `/health`" in docs or "do not probe creopdm-agent" in docs
    assert "hit agent `/health` on every Admin" in docs or "hit agent /health on every Admin" in docs


def test_agent_auth_headers_sent_to_localhost_agent():
    """Browser→agent calls send Authorization; /health stays unauthenticated."""
    script = _app_js()
    assert "function agentAuthHeaders(" in script
    assert "headers: agentAuthHeaders(" in script or "headers: agentAuthHeaders()" in script
    # Status probe must remain open (no auth header required on /health).
    health = _between(script, "async function probeCreoAgent(", "async function pushLocalWorkspaceToVault(")
    assert 'fetch(`${agentBase()}/health`' in health or 'agentBase()}/health' in health
    assert "agentAuthHeaders" not in health
