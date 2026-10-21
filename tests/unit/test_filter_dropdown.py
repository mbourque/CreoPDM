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


def test_the_shortcut_pills_are_gone_from_the_scripts():
    notifications = (JS / "notifications.js").read_text(encoding="utf-8")
    baselines = (JS / "baselines.js").read_text(encoding="utf-8")
    assert "discussion-pill" not in notifications and "baselines-pill" not in baselines
    assert "data-tab-link" not in _app_js()
