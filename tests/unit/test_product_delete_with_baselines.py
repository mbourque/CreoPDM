"""Deleting a product that has baselines: refused on the Files page, warned about on the admin page."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.models.activity import Activity
from creopdm.models.baseline import Baseline, BaselineMember
from creopdm.models.product import Product
from creopdm.models.product_release import ProductRelease
from tests.conftest import requires_git
from tests.unit.test_auth import _login
from tests.unit.test_baselines import _create, _product, _signed_in_admin

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "AdminPass1"


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _counts(auth_ctx):
    with auth_ctx.session_factory() as db:
        return tuple(
            int(db.scalar(select(func.count()).select_from(model)) or 0)
            for model in (Product, Baseline, BaselineMember, ProductRelease)
        )


def _admin_delete(auth_client, product, **extra):
    data = {"product_id": product["uuid"], "confirm_password": PASSWORD, "confirm": "1", **extra}
    return auth_client.post("/admin/products/delete", data=data)


# ---- the Files page (regular UI): refused -------------------------------------------------


@requires_git
def test_a_product_with_baselines_cannot_be_deleted_from_the_files_page(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client, "Gearbox")
    assert _create(auth_client, product, "Design Review 01").status_code == 201
    before = _counts(auth_ctx)

    refused = auth_client.post(f"/api/products/{product['uuid']}/forget", json={"confirm_password": PASSWORD})
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "PRODUCT_HAS_BASELINES"
    assert "Gearbox has 1 baseline (Design Review 01)" in error["message"]
    assert "only an administrator" in error["message"] and "Delete products" in error["message"]
    assert error["details"]["baselines"] == 1
    assert _counts(auth_ctx) == before  # nothing was deleted

    # Archived baselines still count: they still hold the versions.
    baseline = auth_client.get(f"/api/products/{product['uuid']}/baselines").json()[0]
    assert auth_client.post(
        f"/api/baselines/{baseline['uuid']}/archive", json={"confirm_password": PASSWORD}
    ).status_code == 200
    again = auth_client.post(f"/api/products/{product['uuid']}/forget", json={"confirm_password": PASSWORD})
    assert again.status_code == 409 and again.json()["error"]["code"] == "PRODUCT_HAS_BASELINES"


@requires_git
def test_a_product_without_baselines_is_deleted_from_the_files_page_as_before(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client, "Plain")
    deleted = auth_client.post(f"/api/products/{product['uuid']}/forget", json={"confirm_password": PASSWORD})
    assert deleted.status_code == 200, deleted.text
    assert _counts(auth_ctx)[0] == 0


# ---- Administration -> Delete products: warned, and one more confirmation ----------------------


@requires_git
def test_the_admin_page_names_the_baselines_it_will_erase(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    with_baselines, _o = _product(auth_client, "Gearbox")
    _product(auth_client, "Plain", ("a.prt",))
    assert _create(auth_client, with_baselines, "Design Review 01").status_code == 201
    assert _create(auth_client, with_baselines, "Gearbox-R1", baseline_type="RELEASE").status_code == 201

    page = auth_client.get("/admin/products/delete").text
    assert 'data-baselines="2"' in page and "Design Review 01, Gearbox-R1" in page
    assert 'id="delete-baselines-warning"' in page and 'name="confirm_baselines"' in page
    # Only the product that has baselines carries the data.
    assert page.count("data-baselines=") == 1


@requires_git
def test_the_admin_delete_needs_the_extra_confirmation_and_then_erases_everything(
    auth_client, auth_ctx
):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client, "Gearbox")
    assert _create(auth_client, product, "Design Review 01").status_code == 201
    before = _counts(auth_ctx)
    assert before[1] == 1 and before[2] == 3

    refused = _admin_delete(auth_client, product)  # the vault box ticked, the baselines box not
    assert refused.status_code == 400, refused.text
    assert "Gearbox has 1 baseline (Design Review 01)" in refused.text
    assert "erases them permanently" in refused.text
    assert _counts(auth_ctx) == before

    done = _admin_delete(auth_client, product, confirm_baselines="1")
    assert done.status_code == 200, done.text
    assert "Deleted product Gearbox" in done.text
    assert _counts(auth_ctx) == (0, 0, 0, 0)  # product, baselines, members, releases all gone

    # The audit row says what was erased with it.
    with auth_ctx.session_factory() as db:
        row = db.scalar(select(Activity).where(Activity.action == "PRODUCT_DELETED"))
        assert json.loads(row.details_json)["baselines_erased"] == 1
    audit = auth_client.get("/admin/utilities/audit", params={"action": "PRODUCT_DELETED"})
    assert "1 baseline erased" in audit.text


@requires_git
def test_the_admin_delete_of_a_product_without_baselines_needs_no_extra_confirmation(
    auth_client, auth_ctx
):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client, "Plain")
    done = _admin_delete(auth_client, product)
    assert done.status_code == 200 and "Deleted product Plain" in done.text


@requires_git
def test_a_release_without_baseline_files_still_warns(auth_client, auth_ctx):
    """A release record counts too, even when the product had nothing to baseline."""
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client, "Empty", ())
    promoted = auth_client.post(
        "/admin/products/promote",
        data={"product_id": product["uuid"], "state": "RELEASED", "release_baseline": "1",
              "confirm_password": PASSWORD},
    )
    assert promoted.status_code == 200, promoted.text
    refused = auth_client.post(f"/api/products/{product['uuid']}/forget", json={"confirm_password": PASSWORD})
    assert refused.status_code == 409 and refused.json()["error"]["details"]["releases"] == 1


# ---- wiring ---------------------------------------------------------------------------------


def test_the_delete_dialogs_are_wired_to_the_warning():
    admin = (ROOT / "src" / "creopdm" / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    assert "function bindDeleteBaselineWarning" in admin and "bindDeleteBaselineWarning();" in admin
    assert "box.required = show;" in admin  # the extra tick box is required only when it applies
    assert 'dataset.baselines || 0' in admin and "submit.disabled = baselines > 0;" in admin
    app = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    assert 'data-baselines="{{ baseline_total|default(0) }}"' in app and 'id="delete-product-submit"' in app


@requires_git
def test_the_files_page_still_opens_after_every_product_is_deleted(auth_client, auth_ctx):
    """Regression: with no product selected the Files page used to fail with INTERNAL_ERROR."""
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client, "Plain")
    assert _admin_delete(auth_client, product).status_code == 200
    assert auth_client.get("/").status_code == 200
    assert auth_client.get("/", params={"product": product["uuid"]}).status_code in (200, 303, 404)
