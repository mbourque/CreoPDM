"""Locked product: every mutation API must reject (UI hide is not enough)."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import requires_git


def _create_part(client, repo_parent: Path):
    product = client.post("/api/products", json={"name": "Lock Matrix"}).json()
    created = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("shaft.prt", b"original-content", "application/octet-stream")},
        data={"comment": "Initial model"},
    )
    assert created.status_code == 201, created.text
    return product, created.json()


def _lock_on_hold(client, product_uuid: str) -> None:
    ctx = client.app.state.ctx
    with ctx.session_factory() as db:
        loaded = ctx.products.get_product(db, product_uuid)
        loaded.state = "ON_HOLD"
        db.commit()


def _assert_locked(response, *, hint: str) -> None:
    assert response.status_code == 400, f"{hint}: {response.status_code} {response.text}"
    body = response.json()["error"]
    assert body["code"] == "VALIDATION_ERROR", hint
    msg = body["message"].lower()
    assert "on hold" in msg or "read-only" in msg or "cannot" in msg, f"{hint}: {body['message']}"


@requires_git
def test_locked_product_rejects_all_mutation_apis(client, repo_parent):
    """Regression matrix: bypassing the toolbar must still fail server-side."""
    product, obj = _create_part(client, repo_parent)
    pid = product["uuid"]
    oid = obj["uuid"]

    # Check out while mutable so check-in / undo paths are meaningful after lock.
    checked = client.post(f"/api/objects/{oid}/checkout")
    assert checked.status_code == 200, checked.text

    _lock_on_hold(client, pid)

    _assert_locked(
        client.post(
            f"/api/products/{pid}/objects",
            files={"file": ("extra.prt", b"x", "application/octet-stream")},
            data={"comment": "Should block"},
        ),
        hint="add object",
    )
    _assert_locked(
        client.post(f"/api/products/{pid}/folders", json={"name": "Blocked", "parent_folder": ""}),
        hint="create folder",
    )
    _assert_locked(
        client.post(f"/api/objects/{oid}/checkout"),
        hint="checkout again",
    )
    _assert_locked(
        client.post(f"/api/objects/{oid}/checkin", json={"comment": "Should block"}),
        hint="checkin",
    )
    _assert_locked(
        client.delete(f"/api/objects/{oid}"),
        hint="remove object",
    )
    batch = client.post("/api/objects/batch/remove", json={"object_ids": [oid]})
    assert batch.status_code == 200, batch.text
    body = batch.json()
    assert body["ok"] == []
    assert body["failed"], "batch remove must fail when product is locked"
    assert body["failed"][0]["code"] == "VALIDATION_ERROR"
    assert "on hold" in body["failed"][0]["message"].lower()

    # Still checked out after failed batch remove (must not release locks on lock failure).
    still = client.get(f"/api/objects/{oid}")
    assert still.status_code == 200, still.text
    assert still.json()["owned_by_me"] is True

    _assert_locked(
        client.patch(f"/api/products/{pid}", json={"name": "Renamed Lock", "number": None, "description": None}),
        hint="rename product",
    )
    _assert_locked(
        client.post(
            f"/api/objects/{oid}/creo-metadata",
            json={"parameters": [], "identity": {}, "materials": {}, "units": {}},
        ),
        hint="creo metadata",
    )
    _assert_locked(
        client.post(
            f"/api/objects/{oid}/ai-snapshot",
            json={
                "capture_status": "ok",
                "snapshot": {"features": [], "dimensions": [], "parameters": []},
            },
        ),
        hint="ai snapshot",
    )
    _assert_locked(
        client.post(
            f"/api/products/{pid}/objects/from-zip",
            files={"file": ("pack.zip", b"PK\x05\x06" + b"\x00" * 18, "application/zip")},
            data={"parent_folder": ""},
        ),
        hint="from-zip",
    )

    # Undo checkout remains allowed on locked products (release lock only).
    undone = client.post(f"/api/objects/{oid}/undo-checkout")
    assert undone.status_code == 200, undone.text

    # Product delete/forget must still purge locked products (password confirm).
    forgotten = client.post(f"/api/products/{pid}/forget", json={"confirm_password": "test-confirm"})
    assert forgotten.status_code == 200, forgotten.text
    listing = client.get("/api/products")
    assert listing.status_code == 200
    assert all(item["uuid"] != pid for item in listing.json())
