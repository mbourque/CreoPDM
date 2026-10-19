"""A baseline's files are browsed inside the Baselines tab; Details… keeps the inspection dialog."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from tests.conftest import requires_git
from tests.unit.test_baselines import _create, _product, _signed_in_admin

ROOT = Path(__file__).resolve().parents[2]


def _read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


@requires_git
def test_the_tab_has_a_browse_pane_and_a_details_column(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client, "Gearbox")
    assert _create(auth_client, product, "Design Review 01").status_code == 201
    page = auth_client.get(f"/?product={product['uuid']}").text
    assert 'id="baseline-browse"' in page and 'id="baseline-browse-table"' in page
    for control in ("baseline-browse-back", "baseline-browse-details", "baseline-browse-download",
                    "baseline-browse-compare"):
        assert f'id="{control}"' in page, control
    # The list and its header can step aside for the pane.
    assert 'id="baselines-head"' in page and 'id="baselines-table-wrap"' in page
    # Sortable like every other table: a header per file column.
    head = page[page.index('id="baseline-browse-table"') :]
    head = head[: head.index("</thead>")]
    for key in ("name", "rev", "state", "type", "now"):
        assert f'data-sort="{key}"' in head, key
    # The pane is read-only: none of the Files page's editing actions live in it.
    pane = page[page.index('id="baseline-browse"') : page.index("</section>", page.index('id="baseline-browse"'))]
    for forbidden in ("Check out", "Check in", "Rename", "Remove", "Add files"):
        assert forbidden not in pane, forbidden


def test_a_name_browses_and_details_opens_the_dialog():
    module = _read("src", "creopdm", "static", "js", "baselines.js")
    assert "async function browseBaseline(" in module and "mod.browseBaseline = browseBaseline;" in module
    # name -> browse in the tab; the Details… button -> the existing inspection dialog
    assert 'void browseBaseline(link.getAttribute("data-open-baseline") || "")' in module
    assert 'data-baseline-details="' in module
    assert 'void openBaselineMembers(details.getAttribute("data-baseline-details") || "")' in module
    # Opening the tab (or the "N Baselines" pill) always lands on the list.
    assert "async function loadBaselinesTab() {\n      // Opening the tab" in module.replace("\r\n", "\n")
    assert "function leaveBrowse()" in module and "leaveBrowse();" in module
    # The address follows the open baseline so refresh and shared links work.
    assert 'url.searchParams.set("baseline", uuid)' in module and "history.replaceState" in module
    # A baseline that cannot be opened (deleted, no access) falls back to the list with a reason.
    assert "That baseline could not be opened" in module
    # Compare / Download shortcuts reuse the dialog's own flows.
    assert 'setBaselineView("compare")' in module and "await openAddToWorkspace();" in module


def test_a_link_with_a_baseline_opens_its_files():
    app = _read("src", "creopdm", "static", "js", "app.js")
    assert 'new URLSearchParams(window.location.search).get("baseline")' in app
    assert "m.browseBaseline?.(linkedBaseline)" in app
    # the pill still just opens the tab (which shows the list)
    assert 'data-tab-link' in app and "loadBaselinesTab?.()" in app


def test_browse_pane_styles_exist():
    css = _read("src", "creopdm", "static", "css", "app.css")
    for selector in (".baseline-crumbs", ".baseline-browse-banner", "#baseline-browse-table th[data-sort]",
                     '#baseline-browse-table th[aria-sort="ascending"]::after'):
        assert selector in css, selector
