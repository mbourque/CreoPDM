"""Discard changes…: the explicit way out of a file that keeps reading Modified."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import requires_git


def _part(client):
    product = client.post("/api/products", json={"name": "Discard Product"}).json()
    created = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("shaft.prt", b"v1-content", "application/octet-stream")},
        data={"comment": "Initial model"},
    )
    assert created.status_code == 201, created.text
    return product, created.json()


@requires_git
def test_undo_checkout_keeps_a_save_and_discard_changes_drops_it(client, data_dir):
    product, obj = _part(client)
    vault = Path(data_dir) / "vaults" / product["uuid"]
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    (vault / "shaft.prt").write_bytes(b"edited-and-staged")
    (vault / "shaft.prt.2").write_bytes(b"creo-save-2")

    # Undo Checkout releases the lock but keeps the save (it can still be checked in).
    undone = client.post(f"/api/objects/{obj['uuid']}/undo-checkout")
    assert undone.status_code == 200, undone.text
    assert undone.json()["modified_locally"] is True
    assert (vault / "shaft.prt.2").exists()

    discarded = client.post(f"/api/objects/{obj['uuid']}/discard-changes")
    assert discarded.status_code == 200, discarded.text
    body = discarded.json()
    assert body["modified_locally"] is False
    assert body["can_checkin"] is False
    assert (vault / "shaft.prt").read_bytes() == b"v1-content"
    assert not (vault / "shaft.prt.2").exists()
    assert body["display_revision"] == "A.1"  # no new version

    # Nothing left to discard: a clear refusal, not a silent success.
    again = client.post(f"/api/objects/{obj['uuid']}/discard-changes")
    assert again.status_code == 400, again.text
    assert "no unsaved changes" in again.json()["error"]["message"]

    # The audit trail records it.
    ctx = client.app.state.ctx
    with ctx.session_factory() as db:
        events = ctx.activities.list_events(db, q="shaft.prt")
        assert any(e.action == "CHANGES_DISCARDED" for e in events)


@requires_git
def test_discard_changes_is_refused_while_checked_out(client, data_dir):
    product, obj = _part(client)
    vault = Path(data_dir) / "vaults" / product["uuid"]
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    (vault / "shaft.prt").write_bytes(b"edited")
    blocked = client.post(f"/api/objects/{obj['uuid']}/discard-changes")
    assert blocked.status_code == 409, blocked.text
    assert "Undo the checkout first" in blocked.json()["error"]["message"]
    assert (vault / "shaft.prt").read_bytes() == b"edited"


@requires_git
def test_discard_changes_ui_is_wired(client):
    from tests.client_js import app_js_with_modules

    script = app_js_with_modules(client.get("/static/js/app.js")).text
    assert "/discard-changes" in script and "discardVaultChanges" in script
    assert 'action === "discard-changes"' in script
    # Live row state, not a render-time flag (Undo Checkout repaints rows in place).
    assert "canDiscardChanges:" in script and 'row.dataset.modifiedLocally === "1"' in script
    assert "data-can-discard" not in script
    # A "Newer local save" row on the Modified tab can be removed from the local workspace.
    assert "function rowOffersDiscardChanges" in script
    assert "function isLocalSaveQueueRow" in script and "isLocalSave: isLocalSaveQueueRow(row)" in script
    menu = client.get("/static/js/files_context_menu.js").text
    assert 'action: "discard-changes"' in menu and "canDiscardChanges" in menu
    assert "row.isNewFile || row.isLocalSave" in menu
