"""A baseline's files are browsed inside the Baselines tab; Details… keeps the inspection dialog."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.models.baseline import BaselineMember
from sqlalchemy import select
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
    # An open baseline stays open through the tab and the "N Baselines" pill; only the
    # breadcrumb returns to the list.
    assert "An open baseline stays open" in module and "function leaveBrowse()" in module
    back = module.split('$("#baseline-browse-back")', 1)[1][:200]
    assert "leaveBrowse();" in back and "loadBaselinesTab()" in back
    # The address follows the open baseline so refresh and shared links work.
    assert 'url.searchParams.set("baseline", uuid)' in module and "history.replaceState" in module
    # A baseline that cannot be opened (deleted, no access) falls back to the list with a reason.
    assert "That baseline could not be opened" in module
    # Compare / Download shortcuts reuse the dialog's own flows.
    assert 'setBaselineView("compare")' in module and "await openAddToWorkspace();" in module


def test_a_link_with_a_baseline_opens_its_files():
    app = _read("src", "creopdm", "static", "js", "app.js")
    assert 'params.get("baseline")' in app and 'new URLSearchParams(window.location.search)' in app
    assert "m.browseBaseline?.(linkedBaseline)" in app
    # the pill opens the tab, which keeps whichever baseline is open
    assert 'data-tab-link' in app and "loadBaselinesTab?.()" in app


def test_baseline_files_act_like_files_rows():
    module = _read("src", "creopdm", "static", "js", "baselines.js")
    # Files-page rows: the page's own selection, pills and hover preview work on them.
    assert 'class="object-row baseline-file-row"' in module
    for attribute in ("data-object-type", "data-extension", "data-content-hash", "data-detail",
                      "data-top-level-assembly"):
        assert attribute in module, attribute
    painter = module.split("function paintBrowse", 1)[1].split("async function browseBaseline", 1)[0]
    # The name must not carry the live Open class (that would open the CURRENT file).
    assert "thumb-preview-target" in painter and "object-open" not in painter
    # Top level assemblies come from the baseline's own frozen structure, drawings excluded.
    assert "function topLevelAssemblyVersions(" in module and '"CREO_ASSEMBLY"' in module
    app = _read("src", "creopdm", "static", "js", "app.js")
    assert 'tab === "baselines" && document.getElementById("baseline-browse")?.hidden === false' in app
    assert 'querySelector("#baseline-browse-table")?.addEventListener("click", onFileTableClick)' in app
    assert 'querySelector("#baseline-browse-table")?.addEventListener("dblclick", onFileTableDblclick)' in app
    assert "typeIconHtml," in app and "refreshTabMetrics," in app  # shared with baselines.js


def test_a_name_opens_the_file_from_the_downloaded_baseline_and_details_is_the_footer_button():
    module = _read("src", "creopdm", "static", "js", "baselines.js")
    assert "async function openBaselineFile(" in module
    # materialize through the agent (skipped when already installed and unchanged), then open
    assert '"/baseline-workspace/check"' in module and '"/baseline-workspace"' in module
    assert "overwrite: false" in module  # never replaces files on this PC silently
    assert "window.CreoJS.openModel(dir, member.filename" in module and 'mode: "association"' in module
    assert "Start creopdm-agent on this PC" in module
    # a click opens after a beat so a double-click can open Details instead
    assert "}, 280);" in module and '"dblclick", cancelPendingBaselineOpen' in module
    # footer: only Details, only with exactly one row selected
    assert "selectedBrowseRows().length === 1" in module
    page = _read("src", "creopdm", "templates", "app.html")
    assert 'id="baseline-browse-file-details"' in page and "Baseline details…" in page
    css = _read("src", "creopdm", "static", "css", "app.css")
    assert "body.is-baseline-browse footer.toolbar .toolbar-actions > :not(#baseline-browse-file-details)" in css
    assert ".baseline-browse { flex: 1 1 auto; min-height: 0;" in css  # the table scrolls in the pane


def test_browse_pane_styles_exist():
    css = _read("src", "creopdm", "static", "css", "app.css")
    for selector in (".baseline-crumbs", ".baseline-browse-banner", "#baseline-browse-table th[data-sort]",
                     '#baseline-browse-table th[aria-sort="ascending"]::after'):
        assert selector in css, selector


@requires_git
def test_the_version_page_has_breadcrumbs_back_to_the_baseline(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client, "Gearbox")
    baseline = _create(auth_client, product, "Design Review 01").json()
    members = auth_client.get(f"/api/baselines/{baseline['uuid']}/members").json()
    member = members[0]
    base = f"/products/{product['uuid']}/objects/{member['object_uuid']}/versions/{member['version_uuid']}"

    plain = auth_client.get(base).text
    assert 'id="crumb-baseline"' not in plain  # opened from elsewhere: the old breadcrumb

    page = auth_client.get(base, params={"baseline": baseline["uuid"]}).text
    assert f'href="/?product={product["uuid"]}&amp;tab=baselines"' in page and 'id="crumb-baselines"' in page
    assert f'tab=baselines&amp;baseline={baseline["uuid"]}' in page and "Design Review 01" in page
    # a baseline of another product, or an unknown one, adds no link
    other, _ = _product(auth_client, "Other", ("a.prt",))
    other_baseline = _create(auth_client, other, "Other review").json()
    wrong = auth_client.get(base, params={"baseline": other_baseline["uuid"]}).text
    assert 'id="crumb-baseline"' not in wrong
    assert 'id="crumb-baseline"' not in auth_client.get(base, params={"baseline": "nope"}).text


def test_the_open_baseline_is_remembered_and_rows_link_back():
    module = _read("src", "creopdm", "static", "js", "baselines.js")
    assert 'const REMEMBER_KEY = "creopdm.openBaseline";' in module
    assert "rememberBaseline(baselineUuid);" in module and 'rememberBaseline("");' in module
    assert "const remembered = rememberedBaseline();" in module and "void browseBaseline(remembered);" in module
    assert "?baseline=${encodeURIComponent(browseUuid)}" in module  # Details carries the baseline
    assert "mod.showBaselineList" in module
    app = _read("src", "creopdm", "static", "js", "app.js")
    assert 'params.get("tab") === "baselines" && !linkedBaseline' in app and "m.showBaselineList?.()" in app
    page = _read("src", "creopdm", "templates", "app.html")
    footer = page[page.index('id="baseline-browse-file-details"') - 80 : page.index('id="baseline-browse-file-details"')]
    assert "btn-primary" not in footer  # a plain button, like the Files toolbar


def _collect(auth_client, obj, *, parameter, value, material="STEEL"):
    posted = auth_client.post(
        f"/api/objects/{obj['uuid']}/creo-metadata",
        json={
            "identity": {"model_type": "PART", "common_name": "Shaft"},
            "parameters": [{"name": parameter, "value": value}],
            "materials": {"current": material, "available": [material]},
        },
    )
    assert posted.status_code == 200, posted.text


@requires_git
def test_a_baseline_copies_the_metadata_and_shows_it_unchanged(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client, "Gearbox")
    shaft = objects["shaft.prt"]
    _collect(auth_client, shaft, parameter="DIAMETER", value="25", material="STEEL")
    baseline = _create(auth_client, product, "Design Review 01").json()
    member = next(
        m for m in auth_client.get(f"/api/baselines/{baseline['uuid']}/members").json() if m["filename"] == "shaft.prt"
    )

    # The same version is collected again later: its own metadata changes ...
    _collect(auth_client, shaft, parameter="DIAMETER", value="40", material="TITANIUM")
    base = f"/products/{product['uuid']}/objects/{member['object_uuid']}/versions/{member['version_uuid']}"
    live = auth_client.get(base).text
    assert "40" in live and "TITANIUM" in live

    # ... but the baseline shows what it copied when it was made.
    frozen = auth_client.get(base, params={"baseline": baseline["uuid"]}).text
    assert 'data-tab="parameters"' in frozen and "DIAMETER" in frozen
    assert ">25<" in frozen.replace(" ", "").replace("\n", "") or "25" in frozen
    assert "TITANIUM" not in frozen and "STEEL" in frozen
    assert 'id="metadata-note"' not in frozen
    # Rows are stored on the member itself.
    with auth_ctx.session_factory() as db:
        row = db.scalar(select(BaselineMember).where(BaselineMember.object_version_id.is_not(None)))
        assert row is not None
        stored = [m.metadata_json for m in db.scalars(select(BaselineMember))]
        assert any(item and "STEEL" in item and "TITANIUM" not in item for item in stored)


@requires_git
def test_a_file_without_collected_metadata_says_so_in_the_baseline(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client, "Gearbox")
    baseline = _create(auth_client, product, "Design Review 01").json()
    member = auth_client.get(f"/api/baselines/{baseline['uuid']}/members").json()[0]
    base = f"/products/{product['uuid']}/objects/{member['object_uuid']}/versions/{member['version_uuid']}"
    page = auth_client.get(base, params={"baseline": baseline["uuid"]}).text
    assert 'id="metadata-note"' in page and "No Creo metadata was kept with this baseline" in page


def test_the_dialog_file_links_keep_the_baseline_so_details_stays_frozen():
    module = _read("src", "creopdm", "static", "js", "baselines.js")
    link = module.split("function versionLink", 1)[1].split("return `<a", 1)[0]
    assert "?baseline=${encodeURIComponent(info.uuid)}" in link


def test_the_browse_view_has_an_about_section_with_what_the_baseline_records():
    page = _read("src", "creopdm", "templates", "app.html")
    assert 'id="baseline-about"' in page and "About this baseline" in page
    module = _read("src", "creopdm", "static", "js", "baselines.js")
    painter = module.split("function paintAbout", 1)[1].split("function paintBrowse", 1)[0]
    for label in ("Description", "Created", "Repository commit", "Git tag", "Structure", "Immutable"):
        assert f'"{label}"' in painter, label
    assert "paintAbout(browseInfo);" in module
