"""The Files page filter dropdown replaces the row of count pills."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from tests.conftest import requires_git
from tests.unit.test_baselines import _signed_in_admin

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "src" / "creopdm" / "static" / "js"
CSS = ROOT / "src" / "creopdm" / "static" / "css" / "app.css"


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _add(client, product_uuid, name):
    added = client.post(
        f"/api/products/{product_uuid}/objects",
        files={"file": (name, b"bytes", "application/octet-stream")},
        data={"comment": "x"},
    )
    assert added.status_code == 201, added.text


# ------------------------------------------------------------------ markup
@requires_git
def test_the_pills_are_replaced_by_one_dropdown_after_search(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product = auth_client.post("/api/products", json={"name": "Filters"}).json()
    for name in ("a.prt", "b.asm", "c.pdf"):
        _add(auth_client, product["uuid"], name)
    html = auth_client.get(f"/?product={product['uuid']}").text
    # no row of pills
    assert 'class="metrics"' not in html and 'class="metric-link"' not in html
    # the control sits right after the search form, inside the title row (right edge)
    head = html.split('<div class="title-row">', 1)[1].split('<div class="tabs"', 1)[0]
    assert head.index('id="search-form"') < head.index('id="filter-dropdown"')
    assert 'id="filter-trigger"' in head and 'aria-haspopup="menu"' in head and 'id="filter-reset"' in head
    # the menu holds the type filters only; Modified / Checked out are tabs, the shortcut pills are gone
    menu = html.split('id="metric-filters"', 1)[1].split("</ul>", 1)[0]
    keys = re.findall(r'data-filter="([a-z_]+)"', menu)
    assert keys[0] == "files"
    assert {"folders", "cad_models", "creo_parts", "assemblies", "drawings", "documents", "other"} <= set(keys)
    assert "modified" not in keys and "checked_out" not in keys
    assert "baselines-pill" not in html and "discussion-pill" not in html
    assert menu.count('role="menuitemradio"') == len(keys)
    # the engine data stays on the same element
    assert "data-product-objects=" in html and "data-non-openable=" in html and "data-picker-models=" in html


@requires_git
def test_no_dropdown_on_an_empty_product(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product = auth_client.post("/api/products", json={"name": "Empty"}).json()
    html = auth_client.get(f"/?product={product['uuid']}").text
    box = html.split('id="filter-dropdown"', 1)[1].split(">", 1)[0]
    assert " hidden" in box


# ------------------------------------------------------------------ behaviour (script)
def _app_js() -> str:
    return (JS / "app.js").read_text(encoding="utf-8")


def test_one_filter_at_a_time_and_the_control_follows_it():
    app = _app_js()
    chip = app.split("function onMetricChip(", 1)[1].split("async function postAction(", 1)[0]
    assert "One filter at a time: choosing one turns every other one off." in chip
    assert "closeFilterMenu();" in chip  # the menu closes after choosing
    sync = app.split("function syncFilterMenu() {", 1)[1].split("/** Back to everything", 1)[0]
    # no empty filters: a row is listed only with something in it (the active one always stays)
    assert 'item.classList.toggle("is-empty", !(count > 0 || on))' in sync
    # the control shows the active filter, its count and the reset
    assert "filter-count" in sync and "filter-reset" in sync and "is-active" in sync
    # no rows at all: no control
    assert 'box.classList.toggle("is-empty", !anyListed)' in sync
    assert "function resetMetricFilters()" in app and "writeStoredFilters();" in app.split("function resetMetricFilters()", 1)[1][:600]
    # an older stored combination is cut to one filter
    restore = app.split("function restoreStoredFilters(", 1)[1].split("function clearProductFilterStorage(", 1)[0]
    assert ".slice(1)" in restore


def test_the_menu_follows_the_counts_and_the_control_is_closed_by_esc_and_outside_clicks():
    app = _app_js()
    update = app.split("function updateMetricCounts() {", 1)[1].split("}", 1)[0]
    assert "paintMetricCounts();" in update and "syncFilterMenu();" in update
    assert 'event.key === "Escape" && filterMenuEl()?.hidden === false' in app
    assert "box.contains(eventEl(event))" in app  # outside click closes


def test_switching_products_resets_the_filter_but_a_reload_keeps_it():
    app = _app_js()
    reset = app.split("function resetFiltersOnProductSwitch() {", 1)[1].split("const LIST_VIEW_MAX_AGE_MS", 1)[0]
    assert 'localStorage.getItem("creopdm.filterProduct")' in reset and "if (last === product) return;" in reset
    assert "clearProductFilterStorage(product);" in reset and "if (last) clearProductFilterStorage(last);" in reset
    # it runs before the stored filter is restored at boot
    boot = app[app.index("  resetFiltersOnProductSwitch();\n"):][:520]
    assert "restoreStoredFilters();" in boot and "syncFilterMenu();" in boot
    # filters only: the sort storage is left alone
    clear = app.split("function clearProductFilterStorage(productId) {", 1)[1].split("}\n\n  /**", 1)[0]
    assert "creopdm.filters." in clear and "creopdm.sort." not in clear


# ------------------------------------------------------------------ styles and visibility
def test_menu_rows_are_plain_with_hidden_counts_and_the_control_hides_on_other_tabs():
    css = CSS.read_text(encoding="utf-8")
    assert ".filter-menu .metric strong { display: none; }" in css  # counts live on the control, not the menu
    assert ".filter-menu li.is-empty { display: none; }" in css
    assert ".filter-dropdown.is-active" in css and ".filter-reset" in css
    for body_class in ("is-baseline-list", "is-discussion-tab"):
        assert f"body.{body_class} #filter-dropdown" in css
    mobile = css.split("pointer: coarse", 1)[1]
    assert ".filter-dropdown" in mobile


def test_changing_tab_resets_the_filter_before_the_switch():
    app = _app_js()
    handler = app.split('document.querySelectorAll(".tabs .tab").forEach((tab) => {', 1)[1][:1200]
    reset = handler.index("resetMetricFilters();")
    # only when another tab is clicked and a filter is on ...
    assert "!tab.classList.contains(\"is-active\")" in handler[:reset] and "metricMode(btn) !== \"off\"" in handler[:reset]
    # ... and before the new tab becomes active, while the filtered rows are still the visible list
    assert reset < handler.index('item.classList.toggle("is-active", item === tab)')


def test_the_filter_shows_only_on_files_and_inside_an_open_baseline():
    app = _app_js()
    sync = app.split("function syncFilterTabVisibility() {", 1)[1].split("function syncMetricFiltersVisibility", 1)[0]
    assert 'activeListTab() !== "files"' in sync and "is-baseline-browse" in sync
    assert 'classList.toggle("is-filter-off-tab", off)' in sync
    # recomputed on every tab click and whenever a baseline opens or closes
    handler = app.split('document.querySelectorAll(".tabs .tab").forEach((tab) => {', 1)[1][:3000]
    assert "syncFilterTabVisibility();" in handler
    assert 'addEventListener("creopdm:baseline-chrome", syncFilterTabVisibility)' in app
    assert "creopdm:baseline-chrome" in (JS / "baselines.js").read_text(encoding="utf-8")
    assert "body.is-filter-off-tab #filter-dropdown" in CSS.read_text(encoding="utf-8")


def test_the_product_gear_shows_only_on_the_files_tab():
    css = CSS.read_text(encoding="utf-8")
    assert "body.is-filter-off-tab #product-settings" in css and "body.is-baseline-browse #product-settings" in css


def test_a_tab_click_never_opens_the_filter_menu():
    """Regression: a routine that showed/hid the old pills row (when the product has files) ran on every tab
    click and un-hid the menu itself, so the menu popped open without the Filter button being clicked."""
    app = _app_js()
    sync = app.split("function syncMetricFiltersVisibility() {", 1)[1].split("function setProductObjectCount(", 1)[0]
    assert 'document.getElementById("filter-dropdown")' in sync  # the control, not the menu
    assert 'querySelector("#metric-filters")' not in sync and "metric-filters" not in sync
    # the filter menu is un-hidden in exactly one place (the right-click menu is a different element)
    assert app.count("function openFilterMenu()") == 1
    opener = app.split("function openFilterMenu() {", 1)[1].split("/** Rows with nothing in them", 1)[0]
    assert opener.count("menu.hidden = false;") == 1


def test_the_filter_stays_at_the_right_edge_when_search_hides():
    """Search hides on every tab but Files; the control must not slide next to the product gear then."""
    css = CSS.read_text(encoding="utf-8")
    assert ".search-form[hidden] + .filter-dropdown { margin-left: auto; }" in css
    page = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    # the sibling rule needs the control directly after the search form
    after_search = page.split('id="search-form"', 1)[1].split("</form>", 1)[1].lstrip()
    assert after_search.startswith("{% if selected and status %}") and 'id="filter-dropdown"' in after_search[:900]


def test_the_shortcut_pills_are_gone_from_the_scripts():
    notifications = (JS / "notifications.js").read_text(encoding="utf-8")
    baselines = (JS / "baselines.js").read_text(encoding="utf-8")
    assert "discussion-pill" not in notifications and "baselines-pill" not in baselines
    assert "data-tab-link" not in _app_js()


@requires_git
def test_the_product_sidebar_stays_on_the_details_page(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product = auth_client.post("/api/products", json={"name": "Sidebar"}).json()
    _add(auth_client, product["uuid"], "a.prt")
    obj = auth_client.get(f"/api/products/{product['uuid']}/objects").json()[0]
    page = auth_client.get(f"/products/{product['uuid']}/objects/{obj['uuid']}").text
    assert 'class="sidebar"' in page and 'id="product-list"' in page and 'id="sidebar-collapse-btn"' in page
    assert f'href="/?product={product["uuid"]}"' in page.split('id="product-list"', 1)[1]
    assert "product-item is-active" in page  # the file's own product is the highlighted one
    assert 'class="detail"' in page
    # the sidebar's New button opens this dialog; without it on the page the button did nothing
    assert 'id="new-product-btn"' in page and 'id="product-dialog"' in page and 'id="product-form"' in page


def test_the_details_discussion_tab_counts_only_its_own_target():
    """Regression: on a baseline file's Details the tab showed the product-wide open-thread total."""
    js = (JS / "notifications.js").read_text(encoding="utf-8")
    paint = js.split("function paintTabAndPill() {", 1)[1].split("function paintGlyphs()", 1)[0]
    assert '#panel-discussion[data-target-type]:not([data-feed])' in paint  # the product feed keeps the total
    assert "slot(panel.dataset.targetType, panel.dataset.target)" in paint


def test_a_checkin_that_adds_files_collects_metadata_for_them_too():
    app = _app_js()
    targets = app.split("function metadataTargetsFromResult(result) {", 1)[1].split("function checkedInItemsFromResult", 1)[0]
    assert "result.added" in targets and "targets.push(" in targets


def test_add_selected_collects_metadata_as_an_audited_add_run():
    script = (JS / "checkin.js").read_text(encoding="utf-8")
    tail = script.split('await withBusy("Collecting Creo metadata…", async () => {', 1)[1][:500]
    assert "metadataTargetsFromResult(result)" in tail and "audit: true" in tail and "addOnlyCheckin" in tail


def test_add_selected_looks_up_ids_the_reply_left_out():
    script = (JS / "checkin.js").read_text(encoding="utf-8")
    assert "async function fillAddedIds(result, productId)" in script
    tail = script.split('await withBusy("Collecting Creo metadata…", async () => {', 1)[1][:400]
    assert "await fillAddedIds(" in tail and tail.index("fillAddedIds") < tail.index("pushCreoMetadataForItems")


def test_a_bulk_item_is_saved_from_its_identity_when_the_full_collect_fails():
    script = (JS / "creo_workspace.js").read_text(encoding="utf-8")
    assert "async function bulkIdentitySnapshot(base, tip, path)" in script
    assert 'domains: "identity"' in script and 'kind === "BULK" ? snapshot : null' in script
    gather = script.split("async function gatherViaToolkitAgent(", 1)[1][:3200]
    assert gather.count("bulkIdentitySnapshot(base, tip, path)") == 2  # a refused reply and an unusable one


def test_the_notification_panel_is_not_inside_a_span():
    """HTML validity: a div (the panel) is not allowed inside a span; the wrapper is a div."""
    base = (ROOT / "src" / "creopdm" / "templates" / "base.html").read_text(encoding="utf-8")
    assert '<div class="notif-wrap">' in base and '<span class="notif-wrap">' not in base
    assert ".notif-wrap { position: relative; display: inline-flex; }" in CSS.read_text(encoding="utf-8")


def test_filter_and_search_survive_a_reopened_browser():
    """Regression: Creo recreates its embedded browser (new session storage) when its panel is expanded;
    the filter was reset (marker in sessionStorage) and the search text was lost (sessionStorage)."""
    app = _app_js()
    reset = app.split("function resetFiltersOnProductSwitch() {", 1)[1].split("const LIST_VIEW_MAX_AGE_MS", 1)[0]
    assert "sessionStorage" not in reset  # the marker lives in localStorage
    assert "function readListSearchState()" in app and "LIST_SEARCH_MAX_AGE_MS" in app
    persist = app.split("function persistListSearchState() {", 1)[1].split("function persistListTabState(", 1)[0]
    assert "localStorage.setItem(" in persist and "at: Date.now()" in persist
    assert "sessionStorage.getItem(LIST_SEARCH_KEY)" not in app and "sessionStorage.setItem(\n        LIST_SEARCH_KEY" not in app
    # a search older than a working day is dropped, and so is one from another product
    read = app.split("function readListSearchState() {", 1)[1].split("function persistListSearchState()", 1)[0]
    assert "LIST_SEARCH_MAX_AGE_MS" in read and "localStorage.removeItem(LIST_SEARCH_KEY)" in read
    restore = app.split("async function restoreListSearchState() {", 1)[1][:900]
    assert "saved.productId !== productId" in restore


def test_a_reopened_browser_returns_to_the_last_folder_and_tab():
    app = _app_js()
    restore = app.split("function restoreListViewOnReopen() {", 1)[1].split("function applyReopenTab()", 1)[0]
    # only the first page load of a session, never a soft navigation
    assert 'sessionStorage.getItem("creopdm.sessionStarted")' in restore and "|| soft" in restore
    # an explicit address always wins
    assert '["folder", "tab", "baseline", "file", "select", "q"]' in restore
    assert "LIST_VIEW_MAX_AGE_MS" in restore and "window.location.replace(" in restore
    boot = app[app.index("  resetFiltersOnProductSwitch();\n  // Going back to the saved folder?"):][:260]
    assert "if (!restoreListViewOnReopen()) rememberListView();" in boot
    assert "applyReopenTab();" in app and "rememberListView(name);" in app
    remember = app.split("function rememberListView(tabName) {", 1)[1].split("function restoreListViewOnReopen()", 1)[0]
    assert "localStorage.setItem(" in remember and "listViewKey(productId)" in remember


# ------------------------------------------------------------------ the lighter first view
def test_the_files_list_loads_a_big_folders_remaining_rows_after_the_first_page():
    app = _app_js()
    loader = app.split("function loadRemainingFileRows() {", 1)[1].split("/** The Filter control belongs", 1)[0]
    assert "table?.dataset.rowsTailUrl" in loader and "signal: pageSignal" in loader
    # the rows arrive in chunks, never as one block
    assert "const CHUNK = 400;" in loader and 'insertAdjacentHTML("beforeend"' in loader
    # a changed folder (the totals differ) reloads the page instead of mixing two lists
    assert 'response.headers.get("X-Rows-Total")' in loader and "window.location.reload()" in loader
    # the folder snapshot (what clearing a search restores) always holds every row; a search or a
    # back-to-folder swap while the tail is arriving stops the insert
    assert "folderTbodyHtml += html;" in loader and "version !== tableViewVersion" in loader
    assert 'objectTable.dataset.searching === "1"' in loader
    # one refresh when the last chunk is in
    for call in ("reapplyActiveTableSorts();", "syncModifiedStateLabels();", "refreshTabMetrics();", "creopdm:rows-added"):
        assert call in loader
    assert app.count("tableViewVersion += 1;") == 2  # showFolderView and showSearchMatches
    assert "function whenFileRowsReady()" in app


def test_everything_that_needs_every_row_waits_for_the_tail():
    app = _app_js()
    # boot starts the loader once the page is built
    boot = app[app.index("  resetFiltersOnProductSwitch();\n"):][:600]
    assert "loadRemainingFileRows();" in boot
    # selection restore (Details -> Back) and navigator deep links wait for the rows
    watch = app.split("function restoreWatchView() {", 1)[1].split("restoreWatchView();", 1)[0]
    assert "whenFileRowsReady().then(" in watch
    deep = app.split("async function consumeNavigatorDeepLink() {", 1)[1][:200]
    assert "await whenFileRowsReady();" in deep
    notifications = (JS / "notifications.js").read_text(encoding="utf-8")
    assert 'addEventListener("creopdm:rows-added"' in notifications and "paintGlyphs()" in notifications


def test_the_row_template_and_the_fragment_endpoint_share_one_partial():
    app_html = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    assert '{% include "partials/file_rows.html" %}' in app_html and "data-rows-tail-url" in app_html
    rows = (ROOT / "src" / "creopdm" / "templates" / "partials" / "file_rows.html").read_text(encoding="utf-8")
    assert "{% for entry in entries %}" in rows and 'class="object-row"' in rows
    pages = (ROOT / "src" / "creopdm" / "api" / "pages.py").read_text(encoding="utf-8")
    assert 'render(\n        request,\n        "partials/file_rows.html"' in pages and "FILES_FIRST_PAGE = 300" in pages
    # counts come from every file in the folder, not from the rows of this page
    assert "folder_view_counts(\n        all_files," in pages


def test_a_creo_browser_says_connecting_before_the_page_is_read():
    base = (ROOT / "src" / "creopdm" / "templates" / "base.html").read_text(encoding="utf-8")
    head = base.split("</head>", 1)[0]
    assert 'localStorage.getItem("creopdm.creoBrowser") === "1"' in head and '"creo-booting"' in head
    assert "setTimeout" in head  # never stuck
    css = CSS.read_text(encoding="utf-8")
    assert "html.creo-booting body::after" in css and 'content: "Connecting to Creo…"' in css
    app = _app_js()
    assert "function rememberCreoBrowser(isCreo)" in app
    assert app.count('document.documentElement.classList.remove("creo-booting")') >= 2


def test_a_big_baseline_paints_its_first_rows_at_once_and_the_rest_in_chunks():
    baselines = (JS / "baselines.js").read_text(encoding="utf-8")
    assert "const FIRST_ROWS = 300;" in baselines and "const CHUNK_ROWS = 400;" in baselines
    assert "token !== browsePaintToken" in baselines  # another paint replaced the table: stop
    assert 'insertAdjacentHTML("beforeend"' in baselines and "creopdm:rows-added" in baselines
