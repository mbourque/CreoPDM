"""Administration -> Baselines: all baselines, integrity check (Stories 47-49, 51), archive."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from creopdm.app import build_context, create_app
from creopdm.auth_constants import (
    BUILTIN_PERMISSIONS,
    PERMISSION_BASELINES_ADMIN,
    STARTER_ROLE_PERMISSION_KEYS,
    BuiltinRole,
)
from creopdm.config import ConfigManager
from creopdm.models.baseline import Baseline, BaselineMember
from creopdm.models.object import EngineeringObject
from creopdm.models.version import ObjectVersion
from tests.conftest import requires_git
from tests.unit.test_auth import _login
from tests.unit.test_baselines import (
    _baseline_row,
    _create,
    _members,
    _product,
    _signed_in_admin,
    _vault,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _check(auth_client, uuid, deep=False):
    response = auth_client.post(f"/api/baselines/{uuid}/integrity", params={"deep": str(deep).lower()})
    assert response.status_code == 200, response.text
    return response.json()


def _tamper_version(auth_ctx, version_uuid, **fields):
    with auth_ctx.session_factory() as db:
        version = db.scalar(select(ObjectVersion).where(ObjectVersion.uuid == version_uuid))
        for name, value in fields.items():
            setattr(version, name, value)
        db.commit()


# ---- permission and page --------------------------------------------------------------------


def test_baselines_admin_permission_is_for_administrators_only():
    assert PERMISSION_BASELINES_ADMIN in {key for key, _ in BUILTIN_PERMISSIONS}
    assert PERMISSION_BASELINES_ADMIN in STARTER_ROLE_PERMISSION_KEYS[BuiltinRole.ADMINISTRATOR.value]
    for role in (BuiltinRole.PDM_MANAGER, BuiltinRole.ENGINEER, BuiltinRole.VIEWER):
        assert PERMISSION_BASELINES_ADMIN not in STARTER_ROLE_PERMISSION_KEYS[role.value]


def test_admin_endpoints_and_page_need_the_baselines_admin_permission(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    baseline = _create(auth_client, product).json()
    assert auth_client.get("/api/admin/baselines").status_code == 200
    assert auth_client.get("/admin/baselines").status_code == 200
    assert "/admin/baselines" in auth_client.get("/admin/products").text  # the Manage products tile
    assert "/admin/baselines" not in auth_client.get("/admin").text

    for user, password in (("eng", "EngPass1"), ("view", "ViewPass1")):
        _login(auth_client, user, password)
        assert auth_client.get("/api/admin/baselines").status_code == 403
        assert auth_client.post("/api/admin/baselines/integrity").status_code == 403
        assert auth_client.post(f"/api/baselines/{baseline['uuid']}/integrity").status_code == 403
        assert auth_client.post(f"/api/baselines/{baseline['uuid']}/archive").status_code == 403
        assert auth_client.post(f"/api/baselines/{baseline['uuid']}/restore").status_code == 403
        assert auth_client.get("/admin/baselines").status_code == 403


# ---- global list ----------------------------------------------------------------------------


def test_admin_list_shows_every_product_with_counts_and_filters(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    gearbox, _g = _product(auth_client, "Gearbox")
    rig, _r = _product(auth_client, "Rig", ("a.prt",))
    _create(auth_client, gearbox, "Design Review 01")
    _create(auth_client, gearbox, "Gearbox-R1", baseline_type="RELEASE")
    _create(auth_client, rig, "Rig baseline")

    data = auth_client.get("/api/admin/baselines").json()
    assert data["summary"] == {"total": 3, "finalized": 3, "archived": 0, "release": 1, "manual": 2}
    assert [i["name"] for i in data["items"]] == ["Rig baseline", "Gearbox-R1", "Design Review 01"]
    assert {i["product_name"] for i in data["items"]} == {"Gearbox", "Rig"}
    assert data["items"][1]["baseline_type"] == "RELEASE" and data["items"][1]["member_count"] == 3

    def names(**params):
        return [i["name"] for i in auth_client.get("/api/admin/baselines", params=params).json()["items"]]

    assert names(type="RELEASE") == ["Gearbox-R1"]
    assert names(q="rig") == ["Rig baseline"]  # matches the baseline or product name
    assert names(q="gearbox") == ["Gearbox-R1", "Design Review 01"]
    assert names(status="ARCHIVED") == []


# ---- archive / restore ----------------------------------------------------------------------


@requires_git
def test_archive_hides_nothing_deletes_nothing_and_can_be_restored(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    baseline = _create(auth_client, product).json()
    before = {n: m["version_uuid"] for n, m in _members(auth_client, baseline["uuid"]).items()}

    archived = auth_client.post(f"/api/baselines/{baseline['uuid']}/archive")
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "ARCHIVED"
    # Hidden from the everyday list, but still there when asked for, readable, and unchanged.
    assert auth_client.get(f"/api/products/{product['uuid']}/baselines").json() == []
    listed = auth_client.get(
        f"/api/products/{product['uuid']}/baselines", params={"include_archived": "true"}
    ).json()
    assert [b["status"] for b in listed] == ["ARCHIVED"]
    assert auth_client.get(f"/api/baselines/{baseline['uuid']}").json()["status"] == "ARCHIVED"
    assert {n: m["version_uuid"] for n, m in _members(auth_client, baseline["uuid"]).items()} == before
    assert auth_client.get("/api/admin/baselines", params={"status": "ARCHIVED"}).json()["summary"]["archived"] == 1
    # An archived baseline still protects what it holds.
    refused = auth_client.delete(f"/api/objects/{objects['shaft.prt']['uuid']}")
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "VERSION_REFERENCED_BY_BASELINE"
    # No Delete exists, and archiving twice is refused.
    assert auth_client.delete(f"/api/baselines/{baseline['uuid']}").status_code in (404, 405)
    assert auth_client.post(f"/api/baselines/{baseline['uuid']}/archive").status_code in (400, 409, 422)

    restored = auth_client.post(f"/api/baselines/{baseline['uuid']}/restore")
    assert restored.status_code == 200 and restored.json()["status"] == "FINALIZED"
    assert auth_client.post(f"/api/baselines/{baseline['uuid']}/restore").status_code in (400, 409, 422)

    with auth_ctx.session_factory() as db:
        events = auth_ctx.activities.list_events(db, q="Design Review 01")
        actions = {e.action for e in events}
        assert {"BASELINE_ARCHIVED", "BASELINE_RESTORED"} <= actions
        assert db.scalar(select(func.count()).select_from(BaselineMember)) == 3


# ---- integrity ------------------------------------------------------------------------------


@requires_git
def test_a_healthy_baseline_checks_clean_quick_and_deep(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    baseline = _create(auth_client, product).json()

    quick = _check(auth_client, baseline["uuid"])
    assert quick["status"] == "HEALTHY" and quick["problem_count"] == 0
    assert (quick["members"], quick["versions_ok"], quick["content_ok"]) == (3, 3, 3)
    assert quick["hashes_ok"] is None and quick["deep"] is False
    assert quick["commit"] == "OK" and quick["stored_commit"] == baseline["git_commit_sha"]
    assert quick["tag_state"] == "NO_TAG"

    deep = _check(auth_client, baseline["uuid"], deep=True)
    assert deep["status"] == "HEALTHY" and deep["hashes_ok"] == 3 and deep["deep"] is True


@requires_git
def test_missing_content_is_an_error_naming_the_member_and_changes_nothing(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    baseline = _create(auth_client, product).json()
    members = _members(auth_client, baseline["uuid"])
    _tamper_version(auth_ctx, members["shaft.prt"]["version_uuid"], git_commit_hash="0" * 40)

    report = _check(auth_client, baseline["uuid"])
    assert report["status"] == "ERROR" and report["content_ok"] == 2
    assert [(p["code"], p["file"], p["version"]) for p in report["problems"]] == [
        ("CONTENT_MISSING", "shaft.prt", "A.1")
    ]
    # Reported only: membership untouched, nothing substituted.
    after = _members(auth_client, baseline["uuid"])
    assert {n: m["version_uuid"] for n, m in after.items()} == {
        n: m["version_uuid"] for n, m in members.items()
    }


@requires_git
def test_corrupt_content_is_found_by_the_deep_check(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    baseline = _create(auth_client, product).json()
    members = _members(auth_client, baseline["uuid"])
    _tamper_version(auth_ctx, members["gear.prt"]["version_uuid"], content_hash="f" * 64)

    assert _check(auth_client, baseline["uuid"])["status"] == "HEALTHY"  # present, same size
    deep = _check(auth_client, baseline["uuid"], deep=True)
    assert deep["status"] == "ERROR" and deep["hashes_ok"] == 2
    assert [(p["code"], p["file"]) for p in deep["problems"]] == [("CORRUPT", "gear.prt")]
    assert "SHA-256" in deep["problems"][0]["reason"]


@requires_git
def test_a_missing_repository_commit_is_an_error(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    baseline = _create(auth_client, product).json()
    with auth_ctx.session_factory() as db:
        # A direct statement stands in for a damaged repository (the ORM refuses this edit).
        db.execute(update(Baseline).where(Baseline.uuid == baseline["uuid"]).values(git_commit_sha="1" * 40))
        db.commit()
    report = _check(auth_client, baseline["uuid"])
    assert report["status"] == "ERROR" and report["commit"] == "MISSING"
    assert [p["code"] for p in report["problems"]] == ["COMMIT_MISSING"]


@requires_git
def test_a_missing_or_moved_tag_is_a_warning_not_an_error(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    baseline = _create(auth_client, product, git_tag="baseline/admin-check").json()
    assert _check(auth_client, baseline["uuid"])["status"] == "HEALTHY"
    auth_ctx.git._run(["tag", "-d", "baseline/admin-check"], cwd=_vault(auth_ctx, product))
    report = _check(auth_client, baseline["uuid"])
    assert report["status"] == "WARNING" and report["tag_state"] == "MISSING"
    assert report["problem_count"] == 0 and "no longer exists" in report["tag_warning"]


@requires_git
def test_the_quick_check_of_everything_reports_each_baseline(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    good = _create(auth_client, product, "Good").json()
    bad = _create(auth_client, product, "Bad").json()
    members = _members(auth_client, bad["uuid"])
    _tamper_version(auth_ctx, members["housing.prt"]["version_uuid"], git_commit_hash="0" * 40)
    # (The Good baseline shares that version row, so it is affected too: both report the error.)
    reports = auth_client.post("/api/admin/baselines/integrity").json()
    assert {r["name"] for r in reports} == {"Good", "Bad"}
    assert all(r["deep"] is False for r in reports)
    assert {r["status"] for r in reports} == {"ERROR"}
    assert good["uuid"] in {r["baseline_uuid"] for r in reports}
    with auth_ctx.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Baseline)) == 2  # read only


# ---- UI wiring ------------------------------------------------------------------------------


def test_admin_baselines_page_is_wired():
    template = (ROOT / "src" / "creopdm" / "templates" / "admin_baselines.html").read_text(encoding="utf-8")
    for needle in (
        'id="baseline-admin-table"',
        'id="baseline-admin-check-all"',
        'id="baseline-integrity-dialog"',
        'id="baseline-integrity-deep"',
        'class="metric baseline-pill" data-pill="archived"',  # the counts are filters
        'data-pill="error"',
        "no Delete",
    ):
        assert needle in template
    # The app swaps only <main.shell> on a soft navigation and never runs <script> tags in it, so the
    # page must be a lazy module that app.js starts after every swap (not a <script> in the page).
    assert "<script" not in template
    # The name links to the product only for an account that can open it (the Files page sends
    # an admin-only account straight back to Administration).
    assert 'data-can-open-product="{% if can_view_products and can_view_baselines %}1' in template
    assert "canOpenProduct" in (ROOT / "src" / "creopdm" / "static" / "js" / "admin_baselines.js").read_text(encoding="utf-8")
    # Baselines is a tile of Manage products, not of the Administration hub.
    products_hub = (ROOT / "src" / "creopdm" / "templates" / "admin_products_hub.html").read_text(encoding="utf-8")
    assert "can_admin_baselines" in products_hub and "/admin/baselines" in products_hub
    admin_hub = (ROOT / "src" / "creopdm" / "templates" / "admin.html").read_text(encoding="utf-8")
    assert 'href="/admin/baselines"' not in admin_hub and "can_admin_baselines or" in admin_hub
    script = (ROOT / "src" / "creopdm" / "static" / "js" / "admin_baselines.js").read_text(encoding="utf-8")
    assert "window.__creopdmModules.admin_baselines" in script and "init() {" in script
    app_py = (ROOT / "src" / "creopdm" / "app.py").read_text(encoding="utf-8")
    assert '"admin_baselines"' in app_py
    boot = (ROOT / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'if ($("#admin-baselines-page"))' in boot and 'initJobModule("admin_baselines"' in boot
    assert "/api/admin/baselines" in script and "/integrity" in script
    assert "data-archive" in script and "data-restore" in script and "deep=" in script
    assert "function applyPill" in script and "function syncPills" in script and "healthFilter" in script
    # Clicking the active pill again switches it off (and keeps the search text).
    assert "const switchingOff = name !== \"total\" && name === activePill();" in script
    app_js = (ROOT / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'window.location.hash === "#baselines"' in app_js  # the admin link opens the tab


# ---- archived baselines are hidden from everyday use but stay readable and protected ----------


@requires_git
def test_archived_baselines_leave_the_product_tab_but_stay_readable_and_reserve_their_name(
    auth_client, auth_ctx
):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    keep = _create(auth_client, product, "Keep").json()
    hide = _create(auth_client, product, "Hide me").json()
    base = f"/api/products/{product['uuid']}/baselines"

    assert [b["name"] for b in auth_client.get(base).json()] == ["Hide me", "Keep"]
    assert auth_client.post(f"/api/baselines/{hide['uuid']}/archive").status_code == 200

    # Hidden by default, back with include_archived (what the "Show archived" box asks for).
    assert [b["name"] for b in auth_client.get(base).json()] == ["Keep"]
    shown = auth_client.get(base, params={"include_archived": "true"}).json()
    assert [(b["name"], b["status"]) for b in shown] == [("Hide me", "ARCHIVED"), ("Keep", "FINALIZED")]

    # The tab count and the product page ignore it: one baseline in everyday use.
    with auth_ctx.session_factory() as db:
        product_id = _baseline_row(db, keep["uuid"]).product_id
        assert auth_ctx.baselines.count_for_product(db, product_id) == 1
    assert "Baselines · 1" in auth_client.get(f"/?product={product['uuid']}").text

    # Still readable, comparable and downloadable by its uuid, and it still reserves its name.
    assert auth_client.get(f"/api/baselines/{hide['uuid']}").status_code == 200
    assert len(_members(auth_client, hide["uuid"])) == 3
    assert auth_client.get(f"/api/baselines/{hide['uuid']}/compare", params={"to": keep["uuid"]}).status_code == 200
    assert auth_client.get(f"/api/baselines/{hide['uuid']}/workspace-manifest").status_code == 200
    assert _create(auth_client, product, "Hide me").status_code == 409

    # Restoring brings it back.
    assert auth_client.post(f"/api/baselines/{hide['uuid']}/restore").status_code == 200
    assert [b["name"] for b in auth_client.get(base).json()] == ["Hide me", "Keep"]


def test_show_archived_toggle_is_wired():
    template = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    assert 'id="baselines-show-archived"' in template
    module = (ROOT / "src" / "creopdm" / "static" / "js" / "baselines.js").read_text(encoding="utf-8")
    assert "?include_archived=true" in module and "baselines-show-archived" in module
    # The tab and pill count only baselines in everyday use; comparing may use archived ones.
    assert 'item.status !== "ARCHIVED"' in module and ", archived" in module
