"""Where Used stays current when an assembly or drawing is checked in, without a full rebuild."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.models.dependency import Dependency
from creopdm.models.object import EngineeringObject
from tests.conftest import requires_git
from tests.unit.test_baselines import _check_in, _signed_in_admin


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _add(auth_client, product, name, data):
    added = auth_client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": (name, data, "application/octet-stream")},
        data={"comment": "Initial"},
    )
    assert added.status_code == 201, added.text
    return added.json()


def _wait_index(auth_client, product):
    auth_client.post(f"/api/products/{product['uuid']}/rebuild-where-used")
    deadline = time.time() + 20
    while time.time() < deadline:
        if auth_client.get(f"/api/products/{product['uuid']}/rebuild-where-used").json()["state"] in {"done", "error"}:
            return
        time.sleep(0.1)
    raise AssertionError("Where Used did not finish")


def _children(auth_ctx, parent_uuid):
    with auth_ctx.session_factory() as db:
        parent = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == parent_uuid))
        rows = db.scalars(select(Dependency).where(Dependency.parent_object_id == parent.id)).all()
        return sorted(db.get(EngineeringObject, row.child_object_id).filename for row in rows)


@requires_git
def test_a_check_in_rereads_just_that_assembly(auth_client, auth_ctx, monkeypatch):
    _signed_in_admin(auth_client, auth_ctx)
    product = auth_client.post("/api/products", json={"name": "Press"}).json()
    top = _add(auth_client, product, "press_top.asm", b"press_top.asm uses frame_one.prt")
    _add(auth_client, product, "frame_one.prt", b"frame_one.prt")
    _add(auth_client, product, "frame_two.prt", b"frame_two.prt")
    _wait_index(auth_client, product)
    assert _children(auth_ctx, top["uuid"]) == ["frame_one.prt"]

    # The full rebuild must not run for a check-in: only the checked-in file is re-read.
    def no_full_rebuild(*_a, **_k):
        raise AssertionError("a check-in must not rebuild the whole product")

    monkeypatch.setattr(auth_ctx.metadata, "rebuild_where_used_from_vault", no_full_rebuild)
    _check_in(
        auth_client, auth_ctx, product, top,
        b"press_top.asm uses frame_two.prt and frame_one.prt", comment="add frame two",
    )
    assert _children(auth_ctx, top["uuid"]) == ["frame_one.prt", "frame_two.prt"]

    # ... and a removed component leaves with it.
    _check_in(auth_client, auth_ctx, product, top, b"press_top.asm uses frame_two.prt", comment="drop one")
    assert _children(auth_ctx, top["uuid"]) == ["frame_two.prt"]


@requires_git
def test_a_check_in_before_where_used_was_ever_built_does_not_invent_a_partial_index(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product = auth_client.post("/api/products", json={"name": "Press"}).json()
    top = _add(auth_client, product, "press_top.asm", b"press_top.asm uses frame_one.prt")
    _add(auth_client, product, "frame_one.prt", b"frame_one.prt")
    _check_in(auth_client, auth_ctx, product, top, b"press_top.asm uses frame_one.prt v2", comment="edit")
    assert _children(auth_ctx, top["uuid"]) == []  # nothing indexed: the full build is still to come
    with auth_ctx.session_factory() as db:
        assert auth_ctx.metadata.where_used_index_present(db, _product_id(db, product)) is False


def _product_id(db, product):
    from creopdm.models.product import Product

    return db.scalar(select(Product.id).where(Product.uuid == product["uuid"]))


@requires_git
def test_a_failing_refresh_never_fails_the_check_in(auth_client, auth_ctx, monkeypatch):
    _signed_in_admin(auth_client, auth_ctx)
    product = auth_client.post("/api/products", json={"name": "Press"}).json()
    top = _add(auth_client, product, "press_top.asm", b"press_top.asm")

    def boom(*_a, **_k):
        raise RuntimeError("vault unreadable")

    monkeypatch.setattr(auth_ctx.metadata, "refresh_where_used_for_parents", boom)
    done = _check_in(auth_client, auth_ctx, product, top, b"press_top.asm v2", comment="edit")
    assert done["iteration"] == 2


@requires_git
def test_a_revert_carries_the_metadata_of_the_restored_version(auth_client, auth_ctx):
    """Reverting restores the same bytes, so the new version keeps that version's Creo metadata."""
    _signed_in_admin(auth_client, auth_ctx)
    product = auth_client.post("/api/products", json={"name": "Press"}).json()
    shaft = _add(auth_client, product, "shaft.prt", b"shaft-v1")
    posted = auth_client.post(
        f"/api/objects/{shaft['uuid']}/creo-metadata",
        json={"identity": {"model_type": "PART", "common_name": "Shaft"},
              "parameters": [{"name": "DIAMETER", "value": "25"}]},
    )
    assert posted.status_code == 200, posted.text
    first = auth_client.get(f"/api/objects/{shaft['uuid']}").json()["current_version"]["uuid"]
    _check_in(auth_client, auth_ctx, product, shaft, b"shaft-v2", comment="edit")  # A.2: nothing collected yet
    reverted = auth_client.post(f"/api/objects/{shaft['uuid']}/versions/{first}/revert", json={"confirm_password": "AdminPass1"})
    assert reverted.status_code == 200, reverted.text
    meta = auth_client.get(f"/api/objects/{shaft['uuid']}/creo-metadata").json()
    assert meta["identity"]["common_name"] == "Shaft"
    assert [p["name"] for p in meta["parameters"]] == ["DIAMETER"]
