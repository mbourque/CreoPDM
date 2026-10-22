import io
import zipfile
from pathlib import Path

from creopdm.services.git_service import GitService
from creopdm.utils.files import set_file_writable
from tests.conftest import requires_git


def _create_part(client, repo_parent: Path):
    location = repo_parent / "RobotArm"
    product = client.post(
        "/api/products",
        json={"name": "Robot Arm"},
    ).json()
    created = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("shaft.prt", b"original-content", "application/octet-stream")},
        data={"comment": "Initial model"},
    )
    assert created.status_code == 201, created.text
    return product, created.json(), location


@requires_git
def test_checkout_blocked_when_product_in_review(client, repo_parent):
    """Minimum product lifecycle: In Review blocks checkout at the API and list flags."""
    product, obj, _location = _create_part(client, repo_parent)
    listed = client.get(f"/api/products/{product['uuid']}")
    assert listed.status_code == 200
    assert listed.json()["state"] == "IN_WORK"
    assert listed.json()["allows_mutation"] is True
    assert listed.json()["allows_content"] is True

    ctx = client.app.state.ctx
    with ctx.session_factory() as db:
        loaded = ctx.products.get_product(db, product["uuid"])
        loaded.state = "IN_REVIEW"
        db.commit()

    blocked = client.post(f"/api/objects/{obj['uuid']}/checkout")
    assert blocked.status_code == 400, blocked.text
    err = blocked.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert "In Review" in err["message"]

    again = client.get(f"/api/products/{product['uuid']}")
    assert again.json()["allows_mutation"] is False
    assert again.json()["allows_content"] is True
    assert again.json()["allows_edit_metadata"] is False
    assert again.json()["allows_checkout"] is False
    assert again.json()["allows_checkin"] is False
    assert again.json()["allows_download"] is True

    page = client.get(f"/?product={product['uuid']}")
    assert page.status_code == 200, page.text
    assert 'data-allows-mutation="0"' in page.text
    assert 'data-allows-content="1"' in page.text
    assert "product-access-banner" in page.text
    assert "This product is" in page.text
    assert "are blocked" not in page.text
    # The Details page keeps the same banner (it used to appear on the Files page only).
    detail = client.get(f"/products/{product['uuid']}/objects/{obj['uuid']}")
    assert detail.status_code == 200, detail.text
    assert 'id="product-access-banner"' in detail.text and "This product is" in detail.text
    assert 'id="product-state-badge"' in page.text
    assert 'data-state="IN_REVIEW"' in page.text
    assert "In Review" in page.text
    assert 'id="add-menu"' not in page.text
    assert 'id="checkin-menu"' not in page.text
    assert 'id="open-menu"' in page.text
    # Matrix Check Out column off → Undo / Force Undo / Checkout ▾ all hidden.
    assert 'id="checkout-menu"' not in page.text
    assert 'id="undo-btn"' not in page.text
    assert 'id="force-undo-btn"' not in page.text
    # Download still allowed → local Remove / Set WD remain.
    assert 'id="remove-menu"' in page.text
    assert 'id="set-creo-dir-btn"' in page.text
    assert 'data-state="locked"' in page.text
    # Role body flag may still be 1; list rows must not advertise checkout.
    assert page.text.count('data-can-checkout="1"') == 1
    assert 'data-can-checkout="0"' in page.text
    assert 'id="checked-out-help"' not in page.text
    assert "Open, Check In, and Undo Checkout still apply" not in page.text

    detail = client.get(f"/api/objects/{obj['uuid']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_checkout"] is False
    assert detail.json()["can_checkin"] is False
    assert detail.json()["checkout_status"] == "In Review"

    # Details header: product badge In Review — not file In Work + checkout In Review.
    detail_html = client.get(f"/products/{product['uuid']}/objects/{obj['uuid']}")
    assert detail_html.status_code == 200, detail_html.text
    meta = detail_html.text.split('class="detail-meta"', 1)[-1].split("</header>", 1)[0]
    assert 'id="product-state-badge"' in meta
    assert 'data-state="IN_REVIEW"' in meta
    assert "In Review" in meta
    assert "In Work" not in meta
    assert "checkout-state" not in meta


@requires_git
def test_locked_product_hides_open_and_blocks_download(client, repo_parent):
    """Locked is list-only: no Open/Export toolbar; content APIs reject."""
    product, obj, _location = _create_part(client, repo_parent)
    ctx = client.app.state.ctx
    with ctx.session_factory() as db:
        loaded = ctx.products.get_product(db, product["uuid"])
        loaded.state = "LOCKED"
        db.commit()

    page = client.get(f"/?product={product['uuid']}")
    assert page.status_code == 200, page.text
    assert 'data-allows-mutation="0"' in page.text
    assert 'data-allows-content="0"' in page.text
    assert 'data-state="LOCKED"' in page.text
    assert "Locked" in page.text
    assert "List files only" in page.text  # state Description on badge hover title
    assert 'id="open-menu"' not in page.text
    assert 'id="export-menu"' not in page.text
    assert 'id="add-menu"' not in page.text
    assert 'id="checkin-menu"' not in page.text
    assert 'id="checkout-menu"' not in page.text
    assert 'id="undo-btn"' not in page.text
    assert 'id="remove-menu"' not in page.text
    assert 'id="set-creo-dir-btn"' not in page.text

    content = client.get(f"/api/objects/{obj['uuid']}/content")
    assert content.status_code == 400, content.text
    assert "Locked" in content.json()["error"]["message"]

    opened = client.post(
        "/api/creo/open",
        json={"object_id": obj["uuid"], "launch": False, "include_dependencies": False},
    )
    assert opened.status_code == 400, opened.text
    assert "Locked" in opened.json()["error"]["message"]

    exported = client.post(f"/api/products/{product['uuid']}/export", json={})
    assert exported.status_code == 400, exported.text
    assert "Locked" in exported.json()["error"]["message"]


@requires_git
def test_released_product_hides_mutation_toolbar_keeps_delete(client, repo_parent):
    """Released (matrix blocks mutations) hides edit chrome; Delete product stays."""
    product, obj, _location = _create_part(client, repo_parent)
    ctx = client.app.state.ctx
    with ctx.session_factory() as db:
        loaded = ctx.products.get_product(db, product["uuid"])
        loaded.state = "RELEASED"
        db.commit()

    page = client.get(f"/?product={product['uuid']}")
    assert page.status_code == 200, page.text
    assert 'data-allows-mutation="0"' in page.text
    assert 'id="product-state-badge"' in page.text
    assert "Released" in page.text
    assert 'id="add-menu"' not in page.text
    assert 'id="checkin-menu"' not in page.text
    assert 'id="purge-workspace-btn"' not in page.text
    assert 'id="remove-product-btn"' not in page.text
    assert 'id="collect-metadata-btn"' not in page.text
    assert 'id="rebuild-metadata-btn"' not in page.text
    assert 'id="rebuild-where-used-btn"' not in page.text
    assert 'id="rename-product-btn"' not in page.text
    # Delete product stays available on locked products (purge vault + DB).
    assert 'id="delete-product-btn"' in page.text
    assert 'id="checkout-menu"' not in page.text
    assert 'id="undo-btn"' not in page.text
    # Role body flag may still be 1; list rows must not advertise checkout.
    assert page.text.count('data-can-checkout="1"') == 1
    assert 'data-can-checkout="0"' in page.text
    # Download still allowed → local Remove / Set WD remain.
    assert 'id="remove-menu"' in page.text
    assert 'id="discard-local-btn"' in page.text
    assert 'id="set-creo-dir-btn"' in page.text

    detail = client.get(f"/api/objects/{obj['uuid']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["can_checkout"] is False
    assert detail.json()["can_checkin"] is False
    assert detail.json()["checkout_status"] == "Released"
    assert 'data-state="locked"' in page.text

    deleted = client.delete(f"/api/products/{product['uuid']}")
    assert deleted.status_code == 204, deleted.text
    listing = client.get("/api/products")
    assert all(item["uuid"] != product["uuid"] for item in listing.json())


@requires_git
def test_archived_product_hidden_from_files_list(client, repo_parent):
    product, _obj, _location = _create_part(client, repo_parent)
    other = client.post("/api/products", json={"name": "Still Visible"}).json()
    ctx = client.app.state.ctx
    with ctx.session_factory() as db:
        loaded = ctx.products.get_product(db, product["uuid"])
        loaded.state = "ARCHIVED"
        db.commit()

    listed = client.get("/api/products")
    assert listed.status_code == 200, listed.text
    uuids = {p["uuid"] for p in listed.json()}
    assert product["uuid"] not in uuids
    assert other["uuid"] in uuids

    home = client.get("/")
    assert home.status_code == 200, home.text
    # Sidebar product links only — name may still appear as a New-product placeholder.
    assert f'href="/?product={product["uuid"]}"' not in home.text
    assert f'href="/?product={other["uuid"]}"' in home.text
    assert "Still Visible" in home.text


@requires_git
def test_checkout_then_second_user_denied(client, repo_parent, identity, data_dir):
    product, obj, _location = _create_part(client, repo_parent)
    git = GitService()
    vault = data_dir / "vaults" / product["uuid"]
    head_before = git.get_head(vault)

    first = client.post(f"/api/objects/{obj['uuid']}/checkout")
    assert first.status_code == 200, first.text
    assert first.json()["owned_by_me"] is True
    assert first.json()["checkout_status"].startswith("Checked out by me")
    assert first.json()["can_checkin"] is True

    workspace = vault / "shaft.prt"
    assert workspace.is_file()
    original = workspace.read_bytes()

    identity.become("Bob", "ENG-PC-18")
    denied = client.post(f"/api/objects/{obj['uuid']}/checkout")
    assert denied.status_code == 409
    body = denied.json()["error"]
    assert body["code"] == "OBJECT_ALREADY_CHECKED_OUT"
    assert body["details"]["user"] == "Alice"
    assert body["details"]["machine"] == "ENG-PC-17"

    identity.become("Alice", "ENG-PC-17")
    still = client.get(f"/api/objects/{obj['uuid']}")
    assert still.json()["owned_by_me"] is True
    assert still.json()["checkout_user"] == "Alice"
    assert workspace.read_bytes() == original
    assert git.get_head(vault) == head_before


@requires_git
def test_details_shows_checkout_who_and_when_for_other_user(client, repo_parent, identity):
    """Details header hover + Overview must show who holds the lock and when."""
    product, obj, _location = _create_part(client, repo_parent)
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    identity.become("Bob", "ENG-PC-18")
    page = client.get(f"/products/{product['uuid']}/objects/{obj['uuid']}")
    assert page.status_code == 200, page.text
    assert "Checked out by Alice" in page.text
    assert "<td>Checked out by</td>" in page.text
    assert "<td>Checked out</td>" in page.text
    assert 'title="Checked out ' in page.text
    assert "(you)" not in page.text
    assert "inventory-table" in page.text


@requires_git
def test_undo_checkout(client, repo_parent):
    _product, obj, _location = _create_part(client, repo_parent)
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    undone = client.post(f"/api/objects/{obj['uuid']}/undo-checkout")
    assert undone.status_code == 200, undone.text
    payload = undone.json()
    assert payload["owned_by_me"] is False
    assert payload["can_checkout"] is True
    assert payload["checkout_status"] == "Available"


@requires_git
def test_force_undo_checkout_releases_other_users_checkout(client, repo_parent, identity, data_dir):
    """Force Undo Checkout: release another user's lock; no new vault version."""
    from creopdm.services.git_service import GitService

    product, obj, _location = _create_part(client, repo_parent)
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    vault_folder = product.get("vault_folder") or product["uuid"]
    vault = data_dir / "vaults" / vault_folder
    git = GitService()
    head_before = git.get_head(vault)

    identity.become("Bob", "ENG-PC-18")
    denied_undo = client.post(f"/api/objects/{obj['uuid']}/undo-checkout")
    assert denied_undo.status_code == 403, denied_undo.text
    assert denied_undo.json()["error"]["code"] == "CHECKOUT_OWNERSHIP"

    forced = client.post(f"/api/objects/{obj['uuid']}/force-undo-checkout")
    assert forced.status_code == 200, forced.text
    body = forced.json()
    assert body["owned_by_me"] is False
    assert body["can_checkout"] is True
    assert body["checkout_status"] == "Available"
    assert not body.get("checkout_user")
    assert git.get_head(vault) == head_before

    again = client.post(f"/api/objects/{obj['uuid']}/force-undo-checkout")
    assert again.status_code == 403, again.text
    assert again.json()["error"]["code"] == "CHECKOUT_OWNERSHIP"


@requires_git
def test_agent_cache_archive_zip(client, repo_parent):
    product, obj1, _location = _create_part(client, repo_parent)
    created2 = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("bracket.prt", b"bracket-content", "application/octet-stream")},
        data={"comment": "Second part"},
    )
    assert created2.status_code == 201, created2.text
    obj2 = created2.json()
    archive = client.post(
        "/api/objects/batch/agent-cache-archive",
        json={"object_ids": [obj1["uuid"], obj2["uuid"]]},
    )
    assert archive.status_code == 200, archive.text
    assert archive.headers.get("x-creopdm-file-count") == "2"
    assert "application/zip" in archive.headers.get("content-type", "")
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
        names = set(zf.namelist())
        shaft_bytes = zf.read("shaft.prt")
        bracket_bytes = zf.read("bracket.prt")
    assert names == {"shaft.prt", "bracket.prt"}
    assert shaft_bytes == b"original-content"
    assert bracket_bytes == b"bracket-content"

    manifest = client.post(
        "/api/objects/batch/agent-cache-manifest",
        json={"object_ids": [obj1["uuid"], obj2["uuid"]]},
    )
    assert manifest.status_code == 200, manifest.text
    body = manifest.json()
    assert body["product_id"] == product["uuid"]
    assert len(body["items"]) == 2
    by_name = {item["disk_name"]: item for item in body["items"]}
    assert "shaft.prt" in by_name
    assert "bracket.prt" in by_name
    assert by_name["shaft.prt"]["relative_path"] == "shaft.prt"
    assert len(by_name["shaft.prt"]["content_hash"]) == 64
    assert by_name["shaft.prt"]["file_size"] == len(b"original-content")


@requires_git
def test_agent_cache_archive_preserves_nested_paths(client, repo_parent):
    location = repo_parent / "NestedCacheZip"
    product = client.post("/api/products", json={"name": "Nested Cache Zip"}).json()
    lib = location / "lib"
    nested = lib / "step"
    nested.mkdir(parents=True)
    pin = nested / "pin.prt"
    pin.write_bytes(b"nested-pin-bytes")
    imported = client.post(
        f"/api/products/{product['uuid']}/objects/from-disk",
        json={"paths": [str(pin)], "comment": "Nested", "base_folder": str(lib)},
    )
    assert imported.status_code == 200, imported.text
    obj = imported.json()["ok"][0]
    archive = client.post(
        "/api/objects/batch/agent-cache-archive",
        json={"object_ids": [obj["uuid"]]},
    )
    assert archive.status_code == 200, archive.text
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zf:
        assert zf.namelist() == ["lib/step/pin.prt"]
        assert zf.read("lib/step/pin.prt") == b"nested-pin-bytes"
    manifest = client.post(
        "/api/objects/batch/agent-cache-manifest",
        json={"object_ids": [obj["uuid"]]},
    ).json()
    assert manifest["items"][0]["relative_path"] == "lib/step/pin.prt"
    assert manifest["items"][0]["disk_name"] == "pin.prt"


@requires_git
def test_heartbeat_and_batch_heartbeat(client, repo_parent):
    _product, obj, _location = _create_part(client, repo_parent)
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200

    single = client.post(f"/api/objects/{obj['uuid']}/heartbeat")
    assert single.status_code == 204, single.text

    batch = client.post("/api/objects/batch/heartbeat")
    assert batch.status_code == 204, batch.text


@requires_git
def test_heartbeat_soft_fails_when_database_locked(client, repo_parent, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from creopdm.services.checkout_service import CheckoutService

    _product, obj, _location = _create_part(client, repo_parent)
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200

    def boom(_self, _session, _object_uuid):
        raise OperationalError("UPDATE", {}, Exception("database is locked"))

    monkeypatch.setattr(CheckoutService, "heartbeat", boom)
    assert client.post(f"/api/objects/{obj['uuid']}/heartbeat").status_code == 204

    def boom_mine(_self, _session):
        raise OperationalError("UPDATE", {}, Exception("database is locked"))

    monkeypatch.setattr(CheckoutService, "heartbeat_mine", boom_mine)
    assert client.post("/api/objects/batch/heartbeat").status_code == 204


@requires_git
def test_batch_checkout_copies_all_selected_files(client, repo_parent, data_dir):
    location = repo_parent / "BatchArm"
    product = client.post(
        "/api/products",
        json={"name": "Batch Arm"},
    ).json()
    part = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("shaft.prt", b"part", "application/octet-stream")},
        data={"comment": "Part"},
    ).json()
    notes = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"comment": "Notes"},
    ).json()
    assembly = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("arm.asm", b"asm", "application/octet-stream")},
        data={"comment": "Assembly"},
    ).json()

    result = client.post(
        "/api/objects/batch/checkout",
        json={"object_ids": [part["uuid"], notes["uuid"], assembly["uuid"]]},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert len(body["ok"]) == 3
    assert body["failed"] == []
    workspace = data_dir / "vaults" / product["uuid"]
    assert (workspace / "shaft.prt").is_file()
    assert (workspace / "notes.txt").is_file()
    assert (workspace / "arm.asm").is_file()


@requires_git
def test_batch_undo_checkout_releases_all_selected_files(client, repo_parent):
    location = repo_parent / "UndoArm"
    product = client.post(
        "/api/products",
        json={"name": "Undo Arm"},
    ).json()
    part = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("shaft.prt", b"part", "application/octet-stream")},
        data={"comment": "Part"},
    ).json()
    notes = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"comment": "Notes"},
    ).json()
    assembly = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("arm.asm", b"asm", "application/octet-stream")},
        data={"comment": "Assembly"},
    ).json()
    ids = [part["uuid"], notes["uuid"], assembly["uuid"]]
    assert client.post("/api/objects/batch/checkout", json={"object_ids": ids}).status_code == 200

    result = client.post("/api/objects/batch/undo-checkout", json={"object_ids": ids})
    assert result.status_code == 200, result.text
    body = result.json()
    assert len(body["ok"]) == 3
    assert body["failed"] == []
    for object_id in ids:
        listed = client.get(f"/api/objects/{object_id}").json()
        assert listed["owned_by_me"] is False
        assert listed["checkout_status"] == "Available"


@requires_git
def test_batch_workspace_without_checkout(client, repo_parent, data_dir):
    product, obj, _location = _create_part(client, repo_parent)
    copied = data_dir / "vaults" / product["uuid"] / "shaft.prt"
    assert copied.is_file()
    listed = client.get(f"/api/objects/{obj['uuid']}").json()
    assert listed["owned_by_me"] is False
    assert listed["can_checkout"] is True
    assert listed["in_workspace"] is True
    again = client.post("/api/objects/batch/workspace", json={"object_ids": [obj["uuid"]]})
    assert again.status_code == 200
    assert again.json()["ok"] == []


@requires_git
def test_workspace_keeps_product_folders(client, repo_parent, data_dir):
    location = repo_parent / "FolderArm"
    product = client.post(
        "/api/products",
        json={"name": "Folder Arm"},
    ).json()
    lib = location / "lib"
    nested = lib / "step"
    nested.mkdir(parents=True)
    pin = nested / "pin.prt"
    pin.write_bytes(b"pin-bytes")
    imported = client.post(
        f"/api/products/{product['uuid']}/objects/from-disk",
        json={"paths": [str(pin)], "comment": "Nested library part", "base_folder": str(lib)},
    )
    assert imported.status_code == 200, imported.text
    obj = imported.json()["ok"][0]
    listing = client.get(f"/api/products/{product['uuid']}/objects").json()
    item = next(row for row in listing if row["uuid"] == obj["uuid"])
    assert item["relative_path"] == "lib/step/pin.prt"
    workspace = data_dir / "vaults" / product["uuid"]
    assert (workspace / "lib" / "step" / "pin.prt").is_file()
    assert (workspace / "lib" / "step" / "pin.prt").read_bytes() == b"pin-bytes"
    assert not (workspace / "pin.prt").exists()
    assert item["in_workspace"] is True


@requires_git
def test_product_checkouts_lists_active_locks(client, repo_parent, identity):
    product, obj, _location = _create_part(client, repo_parent)
    empty = client.get(f"/api/products/{product['uuid']}/checkouts")
    assert empty.status_code == 200, empty.text
    assert empty.json() == []
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    listed = client.get(f"/api/products/{product['uuid']}/checkouts")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert len(body) == 1
    assert body[0]["uuid"] == obj["uuid"]
    assert body[0]["filename"] == "shaft.prt"
    assert body[0]["owned_by_me"] is True
    assert body[0]["checkout_user"] == "Alice"
    home_out = client.get(f"/?product={product['uuid']}")
    assert home_out.status_code == 200
    assert "Checked out · 1" in home_out.text
    identity.become("Bob", "ENG-PC-18")
    as_bob = client.get(f"/api/products/{product['uuid']}/checkouts")
    assert as_bob.status_code == 200, as_bob.text
    assert as_bob.json()[0]["owned_by_me"] is False
    assert as_bob.json()[0]["checkout_user"] == "Alice"
    identity.become("Alice", "ENG-PC-17")
    assert client.post(f"/api/objects/{obj['uuid']}/undo-checkout").status_code == 200
    assert client.get(f"/api/products/{product['uuid']}/checkouts").json() == []
    home = client.get(f"/?product={product['uuid']}")
    assert home.status_code == 200
    assert 'id="checked-out-table"' in home.text
    assert "Checked out ·" not in home.text
    from tests.client_js import app_js_with_modules

    script = app_js_with_modules(client.get("/static/js/app.js"))
    assert "function loadCheckedOutTab" in script.text
    assert "function listAgentCacheFiles" in script.text
    assert "function pushLocalNewPathsToVault" in script.text
    assert "function countLocalNewWorkspaceFiles" in script.text
    assert "function countLocalWorkspacePending" in script.text
    assert "newerLocal" in script.text
    assert "loadChangesTab({ quiet: true, forceNetwork: true })" in script.text
    assert "loadModifiedTab({ quiet: true, forceNetwork: true })" in script.text
    assert "lastChangesPending" in script.text
    assert "lastModifiedPending" in script.text
    assert "New file (local)" in script.text
    assert "function setCheckedOutTabCount" in script.text
    assert "function loadModifiedTab" in script.text
    assert "function listedMetricRows" in script.text
    assert "function refreshTabMetrics" in script.text
    assert "function metricKey" in script.text
    assert "function markRowSelected" in script.text
    assert "function onMetricChip" in script.text
    assert "stopImmediatePropagation" in script.text
    assert "function rowFilename" in script.text
    assert "function setRowHidden" in script.text
    assert "function setToolbarActionVisible" in script.text
    assert "Hide inactive toolbar actions and fly-up items so the bar stays compact." in script.text
    assert "button.hidden = !visible" in script.text
    assert "Keep the control in layout" not in script.text
    assert "function closeRemoveMenu" in script.text
    assert "Remove ▾" in home.text
    assert 'id="remove-menu-btn"' in home.text
    assert 'id="checkout-menu-btn"' in home.text
    assert "Checkout ▾" in home.text
    assert 'id="checkout-product-btn"' in home.text
    assert "Checkout selected" in home.text
    assert "Checkout product" in home.text
    assert 'id="undo-btn"' in home.text
    assert home.text.index('id="checkout-menu"') < home.text.index('id="undo-btn"')
    assert home.text.index('id="undo-btn"') < home.text.index('id="checkin-menu"')
    assert "data-checkoutable" in home.text
    assert "setCheckoutableCount" in script.text
    assert "Nothing left to check out in this product" in script.text
    assert "count_checkoutable_for_product" in open(
        "src/creopdm/services/checkout_service.py", encoding="utf-8"
    ).read()
    assert 'id="checkin-menu-btn"' in home.text
    assert "Check In ▾" in home.text
    assert 'id="checkin-product-btn"' in home.text
    assert ">Check in product…<" in home.text
    assert ">Check in selected…<" in home.text
    assert home.text.index('id="checkin-product-btn"') < home.text.index('id="checkin-btn"')
    assert "function beginCheckin" in script.text
    assert "function runCheckoutObjects" in script.text
    assert 'beginCheckin("product")' in script.text
    assert 'id="discard-local-btn"' in home.text
    assert 'id="purge-versions-btn"' in home.text
    assert 'id="delete-workspace-btn"' in home.text
    assert ">Clear workspace…<" in home.text
    assert 'id="purge-workspace-btn"' in home.text
    assert "function deleteLocalWorkspacePaths" in script.text
    assert "function deleteLocalProductWorkspace" in script.text
    assert "function purgeLocalVersionsOlderThanVault" in script.text
    assert "Local-only new files that were never added" in script.text
    assert "Vault copies and the product file list are not changed" in script.text
    assert 'title: "Clear workspace"' in script.text
    assert "empty workspace folder stays" in script.text
    assert "function formatPurgeConfirmDetails" in script.text
    assert "function newerLocalCacheSaves" in script.text
    assert "function materializeCheckedOutToAgentCache" in script.text
    assert "BULK_AGENT_CACHE_ZIP_THRESHOLD" in script.text
    assert "/materialize-zip" in script.text
    assert "Checking local index (${unique.length} files)" in script.text or (
        "Checking local workspace for ${total} files" in script.text
    )
    assert "already local" in script.text
    assert "BULK_SLOW_WARN_THRESHOLD" in script.text
    assert "confirmLargeBulk" in script.text
    assert "keepBusy: true" in script.text
    assert "Refreshing…" in script.text
    assert "include_dependencies: false" in script.text
    assert "Downloading checked-out files…" in script.text
    assert "Checking out…" in script.text
    assert "Cancelling checkout…" in script.text
    assert "UNDO_CHUNK" in script.text
    assert "Undo checkout of" in script.text
    assert "window.confirm(confirmMsg)" in script.text
    assert "function setBusyMessage" in script.text
    assert "/api/objects/batch/heartbeat" in script.text
    assert "Nothing to purge — no older local saves below the vault revision" in script.text
    assert "workspace/purge-floors" in script.text
    assert "/purge-versions" in script.text
    assert "dry_run: Boolean(dryRun)" in script.text
    assert "Recycle Bin" in script.text
    assert 'id="danger-confirm-details"' in home.text
    assert "data-purgeable=" in home.text
    assert "toolbar-menu-panel" in home.text
    assert "roleCanCheckout" in script.text
    assert "roleCanCheckin" in script.text
    assert "rowOffersCheckout(row)" in script.text
    assert "selected.every((row) => rowOffersCheckout(row))" in script.text
    assert "function selectionCanCheckin" in script.text
    assert 'row.dataset.canCheckin === "1"' in script.text
    assert (
        'selected.every((row) => rowCheckoutKind(row) === "mine" || dataFlag(row, "owned"))'
        in script.text
    )
    assert 'return row.classList.contains("is-row-hidden")' in script.text
    assert "/checkouts" in script.text
    assert "queue-row" in script.text
    assert "#changes-table" in script.text
    assert ".object-row, .folder-row, .queue-row" in script.text
    assert "function openPdmObjectFromUi" in script.text
    assert "function promptOpenCheckout" in script.text
    assert "function applyCheckedOutOnRows" in script.text
    assert "function applyUndoCheckoutOnRows" in script.text
    assert "Paint before openModel" in script.text
    assert "window.location.assign(next)" in script.text
    reload_body = script.text.split("function reloadPage(")[1].split("function reloadPageAfterDialog(")[0]
    assert "isSoftNavUrl(next)" in reload_body
    assert 'softNavigate(next, "replace")' in reload_body
    assert "if (!inCreoBrowser())" in reload_body
    assert "checkout-dependencies" in script.text
    assert "Only skip the chooser when the Checkout column says it is already mine" in script.text
    assert "Do not trust data-owned alone" in script.text
    assert "skip a one-option dialog" in script.text
    assert "Working directory only applies inside Creo's embedded browser" in script.text
    assert "Check out this file and its dependencies" in home.text
    assert 'id="open-checkout-dialog"' in home.text
    assert "Open without checking out" in home.text
    assert 'id="open-checkout-set-wd"' in home.text
    assert "Set Creo working directory" in home.text
    assert "setWorkingDirectory" in script.text
    assert "open-checkout-set-wd" in script.text
    assert 'link.className = "object-open"' in script.text
    assert "dataset.relativePath" in script.text
    assert "do not Activate it" in home.text
    assert "collapses Creo's embedded browser" in home.text
    css = client.get("/static/css/app.css")
    assert css.status_code == 200
    assert ".grid tr.is-selected td" in css.text
    assert css.text.index(".grid tr.is-pending td") < css.text.rindex(".grid tr.is-selected td")
    assert "#changes-table td" in css.text
    assert "vertical-align: top" in css.text
    assert "span.object-open" in css.text
    assert "background: transparent !important" in css.text
    assert "appearance: none" in css.text.split("\n.metric {")[1].split("}")[0]
    assert ".toolbar-menu" in css.text
    assert "overflow: visible" in css.text.split(".toolbar-actions")[1].split("}")[0]
    assert "tr.is-row-hidden" in css.text
    assert "dialog:not([open])" in css.text
    assert ".tab-panel:not([hidden])" in css.text


@requires_git
def test_checkout_many_continues_after_oserror(client, app, repo_parent):
    """One OSError in a checkout batch is a failed row; the other file still checks out."""
    product = client.post("/api/products", json={"name": "Batch Arm"}).json()
    first = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("shaft.prt", b"shaft", "application/octet-stream")},
        data={"comment": "Shaft"},
    ).json()
    second = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("pin.prt", b"pin", "application/octet-stream")},
        data={"comment": "Pin"},
    ).json()
    workspaces = app.state.ctx.workspaces
    real = workspaces.checkout_workspace_path
    first_filename = first["filename"]

    def wrapped(product, obj, context=None):
        if obj.filename == first_filename:
            raise OSError("disk locked")
        return real(product, obj, context)

    workspaces.checkout_workspace_path = wrapped
    try:
        result = client.post(
            "/api/objects/batch/checkout",
            json={"object_ids": [first["uuid"], second["uuid"]]},
        )
    finally:
        workspaces.checkout_workspace_path = real
    assert result.status_code == 200, result.text
    body = result.json()
    failed = {item["uuid"]: item for item in body["failed"]}
    ok = {item["uuid"]: item for item in body["ok"]}
    assert failed[first["uuid"]]["code"] == "APPLICATION_ERROR"
    assert ok[second["uuid"]]["status"] == "checked_out"
    shaft = client.get(f"/api/objects/{first['uuid']}").json()
    pin = client.get(f"/api/objects/{second['uuid']}").json()
    assert shaft["owned_by_me"] is False
    assert pin["owned_by_me"] is True


def _add_part(client, product, name: str, data: bytes):
    created = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": (name, data, "application/octet-stream")},
        data={"comment": name},
    )
    assert created.status_code == 201, created.text
    return created.json()


@requires_git
def test_batch_checkout_response_carries_plan_items(client, repo_parent):
    """Checkout returns hash identities so the agent skips files it already has."""
    product = client.post("/api/products", json={"name": "Plan Arm"}).json()
    first = _add_part(client, product, "shaft.prt", b"shaft")
    second = _add_part(client, product, "pin.prt", b"pin")
    result = client.post(
        "/api/objects/batch/checkout",
        json={"object_ids": [first["uuid"], second["uuid"]]},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    plan = {item["object_id"]: item for item in body["plan_items"]}
    assert set(plan) == {first["uuid"], second["uuid"]}
    for created in (first, second):
        item = plan[created["uuid"]]
        assert item["content_hash"] == created["current_version"]["content_hash"]
        assert item["file_size"] == created["current_version"]["file_size"]
        assert item["disk_name"] == created["filename"]


@requires_git
def test_checkoutable_ids_lists_only_available_files(client, repo_parent):
    """Light list for Checkout product: no Files presentation, only free IN_WORK files."""
    product = client.post("/api/products", json={"name": "Free Arm"}).json()
    held = _add_part(client, product, "shaft.prt", b"shaft")
    free = _add_part(client, product, "pin.prt", b"pin")
    assert client.post(f"/api/objects/{held['uuid']}/checkout").status_code == 200
    listed = client.get(f"/api/products/{product['uuid']}/checkoutable-ids")
    assert listed.status_code == 200, listed.text
    assert listed.json()["object_ids"] == [free["uuid"]]

    ctx = client.app.state.ctx
    with ctx.session_factory() as db:
        loaded = ctx.products.get_product(db, product["uuid"])
        loaded.state = "IN_REVIEW"
        db.commit()
    blocked = client.get(f"/api/products/{product['uuid']}/checkoutable-ids")
    assert blocked.status_code == 200
    assert blocked.json()["object_ids"] == []


@requires_git
def test_batch_checkout_does_not_hash_clean_tips(client, repo_parent, monkeypatch):
    """Clean tips are only made writable: no SHA-256 reads during a bulk checkout."""
    from creopdm.services import workspace_service

    product = client.post("/api/products", json={"name": "Clean Arm"}).json()
    ids = [_add_part(client, product, f"part{n}.prt", f"p{n}".encode())["uuid"] for n in range(3)]
    calls: list[str] = []
    real = workspace_service.calculate_sha256

    def counting(path):
        calls.append(str(path))
        return real(path)

    monkeypatch.setattr(workspace_service, "calculate_sha256", counting)
    result = client.post("/api/objects/batch/checkout", json={"object_ids": ids})
    assert result.status_code == 200, result.text
    assert len(result.json()["ok"]) == 3
    assert calls == []


@requires_git
def test_batch_checkout_keeps_locally_modified_tip(client, repo_parent, data_dir):
    """A modified working copy is checked out as-is, never overwritten with vault bytes."""
    product = client.post("/api/products", json={"name": "Edit Arm"}).json()
    edited = _add_part(client, product, "shaft.prt", b"original")
    other = _add_part(client, product, "pin.prt", b"pin")
    vault = data_dir / "vaults" / product["uuid"]
    # Added files are read-only until checked out; edit it the way a Creo save would.
    set_file_writable(vault / "shaft.prt")
    (vault / "shaft.prt").write_bytes(b"local-edits")
    result = client.post(
        "/api/objects/batch/checkout",
        json={"object_ids": [edited["uuid"], other["uuid"]]},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["failed"] == []
    assert {item["uuid"] for item in body["ok"]} == {edited["uuid"], other["uuid"]}
    assert (vault / "shaft.prt").read_bytes() == b"local-edits"
    assert client.get(f"/api/objects/{edited['uuid']}").json()["owned_by_me"] is True


@requires_git
def test_batch_checkout_restores_missing_working_copy(client, repo_parent, data_dir):
    """A tip deleted from the vault folder is restored from Git, then checked out."""
    product = client.post("/api/products", json={"name": "Gone Arm"}).json()
    gone = _add_part(client, product, "shaft.prt", b"original")
    vault = data_dir / "vaults" / product["uuid"]
    # Read-only files cannot be deleted on Windows.
    set_file_writable(vault / "shaft.prt")
    (vault / "shaft.prt").unlink()
    result = client.post("/api/objects/batch/checkout", json={"object_ids": [gone["uuid"]]})
    assert result.status_code == 200, result.text
    assert result.json()["failed"] == []
    assert (vault / "shaft.prt").read_bytes() == b"original"


@requires_git
def test_batch_checkout_unique_index_race_fails_only_that_item(client, app, repo_parent):
    """Another process holding a row must fail that file, not the whole batch."""
    from creopdm.constants import CheckoutStatus
    from creopdm.models.checkout import Checkout
    from creopdm.models.object import EngineeringObject
    from sqlalchemy import select

    product = client.post("/api/products", json={"name": "Race Arm"}).json()
    taken = _add_part(client, product, "shaft.prt", b"shaft")
    free = _add_part(client, product, "pin.prt", b"pin")
    ctx = app.state.ctx
    with ctx.session_factory() as db:
        row = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == taken["uuid"]))
        db.add(
            Checkout(
                object_id=row.id,
                user_name="someone-else",
                machine_name="other-pc",
                workspace_path="x",
                status=CheckoutStatus.ACTIVE.value,
            )
        )
        db.commit()
    real = ctx.checkouts.active_map
    # Simulate the check-then-insert race: the active row is invisible to the batch.
    ctx.checkouts.active_map = lambda session, object_ids: {}
    try:
        result = client.post(
            "/api/objects/batch/checkout",
            json={"object_ids": [taken["uuid"], free["uuid"]]},
        )
    finally:
        ctx.checkouts.active_map = real
    assert result.status_code == 200, result.text
    body = result.json()
    assert [item["uuid"] for item in body["failed"]] == [taken["uuid"]]
    assert body["failed"][0]["code"] == "OBJECT_ALREADY_CHECKED_OUT"
    assert [item["uuid"] for item in body["ok"]] == [free["uuid"]]
    assert client.get(f"/api/objects/{free['uuid']}").json()["owned_by_me"] is True


@requires_git
def test_batch_undo_does_not_hash_and_keeps_newer_save(client, repo_parent, data_dir, monkeypatch):
    """Bulk undo only releases locks: no SHA-256 reads, and a newer Creo save stays for check-in."""
    from creopdm.services import workspace_service

    product = client.post("/api/products", json={"name": "Undo Bulk Arm"}).json()
    ids = [_add_part(client, product, f"part{n}.prt", f"p{n}".encode())["uuid"] for n in range(3)]
    assert client.post("/api/objects/batch/checkout", json={"object_ids": ids}).status_code == 200
    vault = data_dir / "vaults" / product["uuid"]
    (vault / "part0.prt.2").write_bytes(b"creo-save")
    calls: list[str] = []
    real = workspace_service.calculate_sha256

    def counting(path):
        calls.append(str(path))
        return real(path)

    monkeypatch.setattr(workspace_service, "calculate_sha256", counting)
    result = client.post("/api/objects/batch/undo-checkout", json={"object_ids": ids})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["failed"] == []
    assert [item["status"] for item in body["ok"]] == ["cancelled"] * 3
    assert [item["uuid"] for item in body["ok"]] == ids
    assert calls == []
    assert (vault / "part0.prt.2").read_bytes() == b"creo-save"
    for object_id in ids:
        assert client.get(f"/api/objects/{object_id}").json()["owned_by_me"] is False


@requires_git
def test_batch_undo_reports_each_state(client, repo_parent, identity):
    """Mine is cancelled, never-checked-out is already available, someone else's is refused."""
    product = client.post("/api/products", json={"name": "Undo State Arm"}).json()
    mine = _add_part(client, product, "mine.prt", b"mine")
    theirs = _add_part(client, product, "theirs.prt", b"theirs")
    idle = _add_part(client, product, "idle.prt", b"idle")
    assert client.post(f"/api/objects/{mine['uuid']}/checkout").status_code == 200
    identity.become("Bob", "ENG-PC-18")
    assert client.post(f"/api/objects/{theirs['uuid']}/checkout").status_code == 200
    result = client.post(
        "/api/objects/batch/undo-checkout",
        json={"object_ids": [mine["uuid"], theirs["uuid"], idle["uuid"]]},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    statuses = {item["uuid"]: item["status"] for item in body["ok"]}
    assert statuses == {theirs["uuid"]: "cancelled", idle["uuid"]: "already_available"}
    assert [item["uuid"] for item in body["failed"]] == [mine["uuid"]]
    assert body["failed"][0]["code"] == "CHECKOUT_OWNERSHIP"


@requires_git
def test_batch_force_undo_releases_other_users_files(client, repo_parent, identity, data_dir):
    """Bulk Force Undo: no new version, previous owner reported per file."""
    product = client.post("/api/products", json={"name": "Force Bulk Arm"}).json()
    first = _add_part(client, product, "first.prt", b"first")
    second = _add_part(client, product, "second.prt", b"second")
    idle = _add_part(client, product, "idle.prt", b"idle")
    assert (
        client.post(
            "/api/objects/batch/checkout", json={"object_ids": [first["uuid"], second["uuid"]]}
        ).status_code
        == 200
    )
    owner = client.get(f"/api/objects/{first['uuid']}").json()["checkout_user"]
    vault = data_dir / "vaults" / (product.get("vault_folder") or product["uuid"])
    git = GitService()
    head_before = git.get_head(vault)
    identity.become("Bob", "ENG-PC-18")
    result = client.post(
        "/api/objects/batch/force-undo-checkout",
        json={"object_ids": [first["uuid"], second["uuid"], idle["uuid"]]},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["failed"] == []
    rows = {item["uuid"]: item for item in body["ok"]}
    assert rows[first["uuid"]]["status"] == "force_cancelled"
    assert rows[second["uuid"]]["status"] == "force_cancelled"
    assert rows[idle["uuid"]]["status"] == "already_available"
    assert git.get_head(vault) == head_before
    # previous_user is not in the API response (it feeds the owner email); the audit
    # trail records who held each lock.
    import json

    from creopdm.constants import ActivityAction
    from creopdm.models.activity import Activity
    from sqlalchemy import select

    with client.app.state.ctx.session_factory() as db:
        overrides = list(
            db.scalars(
                select(Activity).where(Activity.action == ActivityAction.CHECKOUT_OVERRIDE.value)
            ).all()
        )
    assert len(overrides) == 2
    for row in overrides:
        details = json.loads(row.details_json or "{}")
        assert details["previous_user"] == owner
        assert details["filename"] in {"first.prt", "second.prt"}


@requires_git
def test_batch_undo_blocked_by_product_state_fails_only_releases(client, repo_parent):
    """Gate failures apply to files that need releasing; already-available files stay ok."""
    product = client.post("/api/products", json={"name": "Undo Lock Arm"}).json()
    held = _add_part(client, product, "held.prt", b"held")
    idle = _add_part(client, product, "idle.prt", b"idle")
    assert client.post(f"/api/objects/{held['uuid']}/checkout").status_code == 200
    ctx = client.app.state.ctx
    with ctx.session_factory() as db:
        loaded = ctx.products.get_product(db, product["uuid"])
        loaded.state = "IN_REVIEW"
        db.commit()
    result = client.post(
        "/api/objects/batch/undo-checkout",
        json={"object_ids": [held["uuid"], idle["uuid"]]},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert [item["uuid"] for item in body["ok"]] == [idle["uuid"]]
    assert body["ok"][0]["status"] == "already_available"
    assert [item["uuid"] for item in body["failed"]] == [held["uuid"]]
    assert "In Review" in body["failed"][0]["message"]


