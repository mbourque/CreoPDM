"""Baselines Stories 31-32: promoting a product to Released records release R<n> with its baseline."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from creopdm.app import build_context, create_app
from creopdm.auth_constants import BuiltinRole
from creopdm.config import ConfigManager
from creopdm.models.baseline import Baseline
from creopdm.models.product import Product
from creopdm.models.product_release import ProductRelease
from tests.conftest import requires_git
from tests.unit.test_auth import _login, _setup_admin_and_users

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _signed_in(auth_client, auth_ctx):
    _setup_admin_and_users(auth_client, auth_ctx, ("view", BuiltinRole.VIEWER.value))
    _login(auth_client, "admin", "AdminPass1")


def _product(auth_client, name="Gearbox", files=("shaft.prt", "housing.prt")):
    created = auth_client.post("/api/products", json={"name": name})
    assert created.status_code == 201, created.text
    product = created.json()
    for filename in files:
        added = auth_client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": (filename, f"{filename}-v1".encode(), "application/octet-stream")},
            data={"comment": "Initial model"},
        )
        assert added.status_code == 201, added.text
    return product


def _promote(auth_client, product, state, *, baseline=True, reopen=False):
    data = {"product_id": product["uuid"], "state": state, "confirm_password": "AdminPass1"}
    if baseline:
        data["release_baseline"] = "1"
    if reopen:
        data["reopen_files"] = "1"
    return auth_client.post("/admin/products/promote", data=data)


def _releases(auth_client, product):
    response = auth_client.get(f"/api/products/{product['uuid']}/releases")
    assert response.status_code == 200, response.text
    return response.json()


def _counts(auth_ctx):
    with auth_ctx.session_factory() as db:
        return (
            db.scalar(select(func.count()).select_from(ProductRelease)),
            db.scalar(select(func.count()).select_from(Baseline)),
        )


def _state(auth_ctx, product):
    with auth_ctx.session_factory() as db:
        return db.scalar(select(Product.state).where(Product.uuid == product["uuid"]))


@requires_git
def test_promoting_to_released_records_a_release_with_its_baseline(auth_client, auth_ctx):
    _signed_in(auth_client, auth_ctx)
    product = _product(auth_client)
    response = _promote(auth_client, product, "RELEASED")
    assert response.status_code == 200, response.text
    assert "Release R1 created with baseline Gearbox-R1" in response.text
    assert _state(auth_ctx, product) == "RELEASED"

    releases = _releases(auth_client, product)
    assert [r["label"] for r in releases] == ["R1"] and releases[0]["member_count"] == 2
    assert releases[0]["released_by"] == "admin" and releases[0]["baseline_name"] == "Gearbox-R1"

    # The release points at one finalized RELEASE baseline holding the files AS RELEASED.
    listed = auth_client.get(f"/api/products/{product['uuid']}/baselines").json()
    assert [(b["name"], b["baseline_type"], b["status"], b["release_label"]) for b in listed] == [
        ("Gearbox-R1", "RELEASE", "FINALIZED", "R1")
    ]
    assert listed[0]["uuid"] == releases[0]["baseline_uuid"]
    members = auth_client.get(f"/api/baselines/{listed[0]['uuid']}/members").json()
    assert {m["lifecycle_state"] for m in members} == {"RELEASED"}


@requires_git
def test_without_the_checkbox_the_product_is_released_with_no_baseline(auth_client, auth_ctx):
    _signed_in(auth_client, auth_ctx)
    product = _product(auth_client)
    response = _promote(auth_client, product, "RELEASED", baseline=False)
    assert response.status_code == 200, response.text
    assert _state(auth_ctx, product) == "RELEASED"
    assert _releases(auth_client, product) == [] and _counts(auth_ctx) == (0, 0)


@requires_git
def test_each_release_gets_its_own_number_and_baseline_and_old_ones_never_change(
    auth_client, auth_ctx
):
    _signed_in(auth_client, auth_ctx)
    product = _product(auth_client)
    assert _promote(auth_client, product, "RELEASED").status_code == 200
    first = _releases(auth_client, product)[0]
    first_members = auth_client.get(f"/api/baselines/{first['baseline_uuid']}/members").json()

    assert _promote(auth_client, product, "IN_WORK", baseline=False, reopen=True).status_code == 200
    assert _promote(auth_client, product, "RELEASED").status_code == 200
    releases = _releases(auth_client, product)
    assert [r["label"] for r in releases] == ["R2", "R1"]  # newest first
    assert {r["baseline_name"] for r in releases} == {"Gearbox-R1", "Gearbox-R2"}
    assert releases[0]["baseline_uuid"] != releases[1]["baseline_uuid"]
    # R1 still references exactly what it did.
    again = auth_client.get(f"/api/baselines/{first['baseline_uuid']}/members").json()
    assert [m["version_uuid"] for m in again] == [m["version_uuid"] for m in first_members]


@requires_git
def test_a_release_that_cannot_be_validated_is_refused_and_changes_nothing(auth_client, auth_ctx):
    _signed_in(auth_client, auth_ctx)
    product = _product(auth_client, "Rig", ("top.asm", "bolt.prt"))  # an assembly, no Where Used

    refused = _promote(auth_client, product, "RELEASED")
    assert refused.status_code == 400, refused.text
    assert "cannot be released" in refused.text and "Where Used" in refused.text
    # Nothing changed: still not Released, files not Released, no release, no baseline.
    assert _state(auth_ctx, product) != "RELEASED"
    assert _counts(auth_ctx) == (0, 0)
    detail = auth_client.get(f"/api/products/{product['uuid']}/objects").json()
    assert "RELEASED" not in {o["lifecycle_state"] for o in detail}

    # The override: untick the box and the product is released as before.
    assert _promote(auth_client, product, "RELEASED", baseline=False).status_code == 200
    assert _state(auth_ctx, product) == "RELEASED" and _counts(auth_ctx) == (0, 0)


@requires_git
def test_an_empty_product_is_released_without_a_baseline(auth_client, auth_ctx):
    _signed_in(auth_client, auth_ctx)
    product = _product(auth_client, "Empty", ())
    response = _promote(auth_client, product, "RELEASED")
    assert response.status_code == 200, response.text
    assert "no checked-in files to baseline" in response.text
    releases = _releases(auth_client, product)
    assert [r["label"] for r in releases] == ["R1"] and releases[0]["baseline_uuid"] is None
    assert _counts(auth_ctx) == (1, 0)


@requires_git
def test_an_old_release_is_rebuilt_through_its_baseline(auth_client, auth_ctx):
    _signed_in(auth_client, auth_ctx)
    product = _product(auth_client)
    assert _promote(auth_client, product, "RELEASED").status_code == 200
    baseline = _releases(auth_client, product)[0]["baseline_uuid"]
    manifest = auth_client.get(f"/api/baselines/{baseline}/workspace-manifest")
    assert manifest.status_code == 200, manifest.text
    assert {f["filename"] for f in manifest.json()["files"]} == {"shaft.prt", "housing.prt"}
    assert all(f["display_version"] == "A.1" for f in manifest.json()["files"])


@requires_git
def test_deleting_a_product_removes_its_releases_and_baselines(auth_client, auth_ctx):
    _signed_in(auth_client, auth_ctx)
    product = _product(auth_client)
    assert _promote(auth_client, product, "RELEASED").status_code == 200
    assert _counts(auth_ctx) == (1, 1)
    forgotten = auth_client.post(
        f"/api/products/{product['uuid']}/forget", json={"confirm_password": "AdminPass1"}
    )
    assert forgotten.status_code == 200, forgotten.text
    assert _counts(auth_ctx) == (0, 0)


def test_releases_need_the_view_permission_and_cannot_be_modified(auth_client, auth_ctx):
    _signed_in(auth_client, auth_ctx)
    product = _product(auth_client, files=())
    _login(auth_client, "view", "ViewPass1")
    assert auth_client.get(f"/api/products/{product['uuid']}/releases").status_code == 200
    for method in ("post", "put", "patch", "delete"):
        response = auth_client.request(method.upper(), f"/api/products/{product['uuid']}/releases")
        assert response.status_code in (404, 405)


def test_promote_page_offers_the_release_baseline_ticked_by_default():
    template = (ROOT / "src" / "creopdm" / "templates" / "admin_products_promote.html").read_text(encoding="utf-8")
    assert 'name="release_baseline" id="promote-release" value="1" checked' in template
    assert 'id="promote-release-wrap" hidden' in template
    script = (ROOT / "src" / "creopdm" / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    assert "syncReleaseChoice" in script and 'stateSel.value === "RELEASED"' in script
    module = (ROOT / "src" / "creopdm" / "static" / "js" / "baselines.js").read_text(encoding="utf-8")
    assert "release_label" in module and "baseline-release-badge" in module
