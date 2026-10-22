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
    reset = app.split("function resetFiltersOnProductSwitch() {", 1)[1].split("function clearProductViewStorage(", 1)[0]
    assert 'sessionStorage.getItem("creopdm.filterProduct")' in reset and "if (last === product) return;" in reset
    assert "clearProductFilterStorage(product);" in reset and "if (last) clearProductFilterStorage(last);" in reset
    # it runs before the stored filter is restored at boot
    boot = app[app.index("  resetFiltersOnProductSwitch();\n  restoreStoredFilters();"):][:140]
    assert "syncFilterMenu();" in boot
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


def test_the_open_notice_keeps_the_toolkits_own_reason():
    script = (JS / "creo_workspace.js").read_text(encoding="utf-8")
    loop = script.split("if (sessionOnly || sessionWaitRounds > 0) {", 1)[1][:900]
    assert "target.detail = String(snapshot.__detail || snapshot.__error" in loop
