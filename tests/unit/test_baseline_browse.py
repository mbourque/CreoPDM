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
    # the Baselines tab keeps whichever baseline is open
    assert "loadBaselinesTab?.()" in app


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
    # the open itself is shared (creo_workspace.js): the file list and the Details page both use it
    assert "shell.openBaselineVersion(browseInfo, member)" in module
    shared = _read("src", "creopdm", "static", "js", "creo_workspace.js")
    body = shared.split("async function openBaselineVersion", 1)[1].split("function noteCollectFailures", 1)[0]
    # materialize through the agent (skipped when already installed and unchanged), then open
    assert '"/baseline-workspace/check"' in body and '"/baseline-workspace"' in body
    assert "overwrite: false" in body  # never replaces files on this PC silently
    assert "window.CreoJS.openModel(dir, member.filename" in body and 'mode: "association"' in body
    assert "Start creopdm-agent on this PC" in body
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



@requires_git
def test_members_carry_the_files_list_type_label_from_the_copied_metadata(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client, "Gearbox")
    shaft = objects["shaft.prt"]
    posted = auth_client.post(
        f"/api/objects/{shaft['uuid']}/creo-metadata",
        json={"identity": {"model_type": "PART", "model_role": "SHEETMETAL"}},
    )
    assert posted.status_code == 200, posted.text
    live = next(o for o in auth_client.get(f"/api/products/{product['uuid']}/objects").json()
                if o["filename"] == "shaft.prt")
    baseline = _create(auth_client, product, "Design Review 01").json()
    members = {m["filename"]: m for m in auth_client.get(f"/api/baselines/{baseline['uuid']}/members").json()}
    # the very label the Files list shows for that file ...
    assert members["shaft.prt"]["type_label"] == live["type_label"] != ""
    # ... and a file with no metadata falls back to the usual label, never to an empty cell
    assert members["gear.prt"]["type_label"]
    # recollecting later does not move what the baseline shows
    auth_client.post(f"/api/objects/{shaft['uuid']}/creo-metadata", json={"identity": {"model_type": "MFG"}})
    again = {m["filename"]: m for m in auth_client.get(f"/api/baselines/{baseline['uuid']}/members").json()}
    assert again["shaft.prt"]["type_label"] == live["type_label"]


def test_the_baseline_tables_show_the_type_label():
    module = _read("src", "creopdm", "static", "js", "baselines.js")
    assert "function typeText(m)" in module and "m.type_label" in module
    assert module.count("typeText(m)") >= 3  # browse rows, dialog rows, sorting


@requires_git
def test_the_type_label_never_reads_the_live_version_metadata(auth_client, auth_ctx):
    """A member with no copy gets the usual type, even if the version has metadata today."""
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client, "Gearbox")
    shaft = objects["shaft.prt"]
    baseline = _create(auth_client, product, "Design Review 01").json()  # no metadata collected yet
    before = {m["filename"]: m for m in auth_client.get(f"/api/baselines/{baseline['uuid']}/members").json()}
    posted = auth_client.post(
        f"/api/objects/{shaft['uuid']}/creo-metadata",
        json={"identity": {"model_type": "PART", "model_role": "SHEETMETAL"}},
    )
    assert posted.status_code == 200, posted.text
    after = {m["filename"]: m for m in auth_client.get(f"/api/baselines/{baseline['uuid']}/members").json()}
    assert after["shaft.prt"]["type_label"] == before["shaft.prt"]["type_label"]


def test_the_list_of_baselines_has_no_pills_and_no_files_toolbar():
    module = _read("src", "creopdm", "static", "js", "baselines.js")
    assert 'classList.toggle("is-baseline-list", baselinesTabActive() && !browseUuid)' in module
    css = _read("src", "creopdm", "static", "css", "app.css")
    assert "body.is-baseline-list #metric-filters" in css and "body.is-baseline-list #selection-summary" in css
    assert "body.is-baseline-list footer.toolbar .toolbar-actions" in css and "{ display: none !important; }" in css
    # an open baseline brings the pills back (and the single Details button), so no list rule leaks
    assert "body.is-baseline-browse footer.toolbar .toolbar-actions" in css


def test_a_new_page_starts_without_the_baseline_view_classes():
    app = _read("src", "creopdm", "static", "js", "app.js")
    boot = app.split("window.__creopdmBoot = function creopdmBoot", 1)[1][:600]
    assert 'classList.remove("is-baseline-browse", "is-baseline-list", "is-discussion-tab", "is-filter-off-tab")' in boot


def test_an_open_baseline_shows_only_the_pills_that_work_on_its_files():
    module = _read("src", "creopdm", "static", "js", "baselines.js")
    assert 'const PILLS_NOT_FOR_BASELINE_FILES = ["folders", "modified", "checked_out"];' in module
    painter = module.split("function syncPills", 1)[1].split("function syncBrowseChrome", 1)[0]
    assert "item.hidden = on" in painter and "chip.hidden" not in painter  # no shortcut pill any more
    # a filter left on is switched off first, so it cannot hide every baseline row
    assert 'btn.click()' in painter
    assert "syncPills(on);" in module
    # the pills that do work are the Files-page ones (types, documents, other, top level assemblies)
    app = _read("src", "creopdm", "templates", "app.html")
    for key in ("files", "cad_models", "creo_parts", "assemblies", "drawings", "documents", "other", "top_level_assemblies"):
        assert f'data-filter="{key}"' in app, key


@requires_git
def test_the_details_page_of_a_baseline_file_opens_the_baseline_model(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client, "Gearbox")
    baseline = _create(auth_client, product, "Design Review 01").json()
    member = auth_client.get(f"/api/baselines/{baseline['uuid']}/members").json()[0]
    base = f"/products/{product['uuid']}/objects/{member['object_uuid']}/versions/{member['version_uuid']}"

    page = auth_client.get(base, params={"baseline": baseline["uuid"]}).text
    assert 'id="detail-open-btn"' in page  # the same Open… as on a Files Details page
    assert f'data-baseline="{baseline["uuid"]}"' in page and f'data-product="{product["uuid"]}"' in page
    assert "data-workspace-folder=" in page and "data-relative-path=" in page
    assert "Open exactly this version of the file" in page
    assert 'id="toolbar-error"' in page  # where an open problem is shown on this page

    # outside a baseline an old version has nothing safe to open, so no Open…
    assert 'id="detail-open-btn"' not in auth_client.get(base).text
    # the live Details page keeps the normal Open…
    live = auth_client.get(f"/products/{product['uuid']}/objects/{member['object_uuid']}").text
    assert 'id="detail-open-btn"' in live and "data-baseline=" not in live


def test_both_screens_use_the_one_baseline_open():
    app = _read("src", "creopdm", "static", "js", "app.js")
    handler = app.split('document.querySelector("#detail-open-btn")?.addEventListener', 1)[1][:1200]
    assert "if (btn.dataset.baseline) {" in handler and "await openBaselineVersion(" in handler
    assert "async function openBaselineVersion(info, member)" in app and "    openBaselineVersion,\n" in app.replace("\r\n", "\n")
    shared = _read("src", "creopdm", "static", "js", "creo_workspace.js")
    assert "mod.openBaselineVersion = openBaselineVersion;" in shared
    module = _read("src", "creopdm", "static", "js", "baselines.js")
    assert "openBaselineFile" in module and "window.CreoJS" not in module  # no second copy of the open


def test_the_frozen_note_on_a_baseline_file_does_not_touch_the_open_button():
    css = _read("src", "creopdm", "static", "css", "app.css")
    assert "#version-banner { margin: 0.75rem 0 0.5rem; }" in css


def test_an_open_baseline_hides_the_product_gear():
    css = _read("src", "creopdm", "static", "css", "app.css")
    assert "body.is-baseline-browse #product-settings," in css
    assert "body.is-filter-off-tab #product-settings { display: none !important; }" in css
    page = _read("src", "creopdm", "templates", "app.html")
    assert 'id="product-settings"' in page  # the element the rule hides


def test_baseline_names_in_the_list_are_not_bold():
    css = _read("src", "creopdm", "static", "css", "app.css")
    rule = css.split(".baseline-open {", 1)[1].split("}", 1)[0]
    assert "font-weight: 400;" in rule and "font-weight: 700" not in rule


def test_baseline_rows_use_the_same_icon_inputs_as_the_files_list():
    """The icon table is keyed by ".mfg" (with the dot) and by type label first. The baseline rows
    passed "mfg" without the dot and no label, so an .mfg showed the generic file icon."""
    js = (ROOT / "src/creopdm/static/js/baselines.js").read_text(encoding="utf-8")
    assert "typeLabel: m.type_label, filename: m.filename, objectType: type" in js
    assert "typeIconHtml({ objectType: type, extension: ext })" not in js


def test_baseline_open_asks_the_server_for_the_same_decision_as_the_files_list():
    """A baseline file opens like the same file in the Files list: the server decides (Creo
    session / Multi-CAD / Creo View / Windows, or refused as non-openable), the browser has no
    list of its own. Opening an .mfg through the Windows association used to start whichever
    Creo Windows had registered (an older one)."""
    js = (ROOT / "src/creopdm/static/js/creo_workspace.js").read_text(encoding="utf-8")
    assert '"/api/creo/open-plan"' in js and "async function openPlanFor(filename)" in js
    assert "const planned = await openPlanFor(member.filename);" in js
    assert "plan.creo_object || plan.open_with_creo" in js
    # no fixed extension lists in the open path
    assert '["prt", "asm", "drw"]' not in js and "(prt|asm|drw)" not in js and "isCreoModelFile" not in js
    # the plan is asked before the baseline is downloaded to the PC
    assert js.index("openPlanFor(member.filename)") < js.index("probeCreoAgent();", js.index("async function openBaselineVersion"))


@requires_git
def test_open_plan_endpoint_matches_the_files_list_decision(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    cad = auth_ctx.config.settings.cad
    cad.model_extensions = [".prt", ".asm", ".drw", ".mfg"]
    cad.extra_extensions = [".creo", ".dat"]
    plan = lambda name: auth_client.post("/api/creo/open-plan", json={"filename": name})  # noqa: E731
    mfg = plan("as_nc.mfg")
    assert mfg.status_code == 200 and mfg.json()["creo_object"] is True  # opens in the running Creo
    assert plan("x.prt.3").json()["creo_object"] is True
    other = plan("notes.xyz").json()
    assert other["creo_object"] is False and other["open_with_creo"] is False
    refused = plan("WINDCHILL-424 ASSY.SLDASM.creo")
    assert refused.status_code == 400 and "non-openable file type" in refused.json()["error"]["message"]
    assert plan("values.DAT").status_code == 400
