import io
import zipfile
from pathlib import Path

from creopdm.services.git_service import GitService
from tests.conftest import requires_git


def _create_part(client, repo_parent: Path):
    location = repo_parent / "RobotArm"
    project = client.post(
        "/api/projects",
        json={"name": "Robot Arm"},
    ).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt", b"original-content", "application/octet-stream")},
        data={"comment": "Initial model"},
    )
    assert created.status_code == 201, created.text
    return project, created.json(), location


@requires_git
def test_checkout_then_second_user_denied(client, repo_parent, identity, data_dir):
    project, obj, _location = _create_part(client, repo_parent)
    git = GitService()
    vault = data_dir / "vaults" / project["uuid"]
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
def test_undo_checkout(client, repo_parent):
    _project, obj, _location = _create_part(client, repo_parent)
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    undone = client.post(f"/api/objects/{obj['uuid']}/undo-checkout")
    assert undone.status_code == 200, undone.text
    payload = undone.json()
    assert payload["owned_by_me"] is False
    assert payload["can_checkout"] is True
    assert payload["checkout_status"] == "Available"


@requires_git
def test_agent_cache_archive_zip(client, repo_parent):
    project, obj1, _location = _create_part(client, repo_parent)
    created2 = client.post(
        f"/api/projects/{project['uuid']}/objects",
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
    assert body["project_id"] == project["uuid"]
    assert len(body["items"]) == 2
    by_name = {item["disk_name"]: item for item in body["items"]}
    assert "shaft.prt" in by_name
    assert "bracket.prt" in by_name
    assert len(by_name["shaft.prt"]["content_hash"]) == 64
    assert by_name["shaft.prt"]["file_size"] == len(b"original-content")


@requires_git
def test_heartbeat_and_batch_heartbeat(client, repo_parent):
    _project, obj, _location = _create_part(client, repo_parent)
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200

    single = client.post(f"/api/objects/{obj['uuid']}/heartbeat")
    assert single.status_code == 204, single.text

    batch = client.post("/api/objects/batch/heartbeat")
    assert batch.status_code == 204, batch.text


@requires_git
def test_heartbeat_soft_fails_when_database_locked(client, repo_parent, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from creopdm.services.checkout_service import CheckoutService

    _project, obj, _location = _create_part(client, repo_parent)
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
    project = client.post(
        "/api/projects",
        json={"name": "Batch Arm"},
    ).json()
    part = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt", b"part", "application/octet-stream")},
        data={"comment": "Part"},
    ).json()
    notes = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"comment": "Notes"},
    ).json()
    assembly = client.post(
        f"/api/projects/{project['uuid']}/objects",
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
    workspace = data_dir / "vaults" / project["uuid"]
    assert (workspace / "shaft.prt").is_file()
    assert (workspace / "notes.txt").is_file()
    assert (workspace / "arm.asm").is_file()


@requires_git
def test_batch_undo_checkout_releases_all_selected_files(client, repo_parent):
    location = repo_parent / "UndoArm"
    project = client.post(
        "/api/projects",
        json={"name": "Undo Arm"},
    ).json()
    part = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt", b"part", "application/octet-stream")},
        data={"comment": "Part"},
    ).json()
    notes = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"comment": "Notes"},
    ).json()
    assembly = client.post(
        f"/api/projects/{project['uuid']}/objects",
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
    project, obj, _location = _create_part(client, repo_parent)
    copied = data_dir / "vaults" / project["uuid"] / "shaft.prt"
    assert copied.is_file()
    listed = client.get(f"/api/objects/{obj['uuid']}").json()
    assert listed["owned_by_me"] is False
    assert listed["can_checkout"] is True
    assert listed["in_workspace"] is True
    again = client.post("/api/objects/batch/workspace", json={"object_ids": [obj["uuid"]]})
    assert again.status_code == 200
    assert again.json()["ok"] == []


@requires_git
def test_workspace_keeps_project_folders(client, repo_parent, data_dir):
    location = repo_parent / "FolderArm"
    project = client.post(
        "/api/projects",
        json={"name": "Folder Arm"},
    ).json()
    lib = location / "lib"
    nested = lib / "step"
    nested.mkdir(parents=True)
    pin = nested / "pin.prt"
    pin.write_bytes(b"pin-bytes")
    imported = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(pin)], "comment": "Nested library part", "base_folder": str(lib)},
    )
    assert imported.status_code == 200, imported.text
    obj = imported.json()["ok"][0]
    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()
    item = next(row for row in listing if row["uuid"] == obj["uuid"])
    assert item["relative_path"] == "lib/step/pin.prt"
    workspace = data_dir / "vaults" / project["uuid"]
    assert (workspace / "lib" / "step" / "pin.prt").is_file()
    assert (workspace / "lib" / "step" / "pin.prt").read_bytes() == b"pin-bytes"
    assert not (workspace / "pin.prt").exists()
    assert item["in_workspace"] is True


@requires_git
def test_project_checkouts_lists_active_locks(client, repo_parent, identity):
    project, obj, _location = _create_part(client, repo_parent)
    empty = client.get(f"/api/projects/{project['uuid']}/checkouts")
    assert empty.status_code == 200, empty.text
    assert empty.json() == []
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    listed = client.get(f"/api/projects/{project['uuid']}/checkouts")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert len(body) == 1
    assert body[0]["uuid"] == obj["uuid"]
    assert body[0]["filename"] == "shaft.prt"
    assert body[0]["owned_by_me"] is True
    assert body[0]["checkout_user"] == "Alice"
    home_out = client.get(f"/?project={project['uuid']}")
    assert home_out.status_code == 200
    assert "Files checked out · 1" in home_out.text
    identity.become("Bob", "ENG-PC-18")
    as_bob = client.get(f"/api/projects/{project['uuid']}/checkouts")
    assert as_bob.status_code == 200, as_bob.text
    assert as_bob.json()[0]["owned_by_me"] is False
    assert as_bob.json()[0]["checkout_user"] == "Alice"
    identity.become("Alice", "ENG-PC-17")
    assert client.post(f"/api/objects/{obj['uuid']}/undo-checkout").status_code == 200
    assert client.get(f"/api/projects/{project['uuid']}/checkouts").json() == []
    home = client.get(f"/?project={project['uuid']}")
    assert home.status_code == 200
    assert 'id="checked-out-table"' in home.text
    assert "Files checked out ·" not in home.text
    script = client.get("/static/js/app.js")
    assert "function loadCheckedOutTab" in script.text
    assert "function listAgentCacheFiles" in script.text
    assert "function pushLocalNewPathsToVault" in script.text
    assert "function countLocalNewWorkspaceFiles" in script.text
    assert "function countLocalWorkspacePending" in script.text
    assert "newerLocal" in script.text
    assert "New file (local)" in script.text
    assert "function setCheckedOutTabCount" in script.text
    assert "function listedMetricRows" in script.text
    assert "function refreshTabMetrics" in script.text
    assert "function metricKey" in script.text
    assert "function markRowSelected" in script.text
    assert "function onMetricChip" in script.text
    assert "stopImmediatePropagation" in script.text
    assert "function rowFilename" in script.text
    assert "function setRowHidden" in script.text
    assert "function setToolbarActionVisible" in script.text
    assert "Keep the control in layout" in script.text
    assert "function closeRemoveMenu" in script.text
    assert "Remove ▾" in home.text
    assert 'id="remove-menu-btn"' in home.text
    assert 'id="discard-local-btn"' in home.text
    assert 'id="purge-versions-btn"' in home.text
    assert 'id="purge-workspace-btn"' in home.text
    assert "function deleteLocalWorkspacePaths" in script.text
    assert "function purgeLocalVersionsOlderThanVault" in script.text
    assert "function formatPurgeConfirmDetails" in script.text
    assert "function newerLocalCacheSaves" in script.text
    assert "function materializeCheckedOutToAgentCache" in script.text
    assert "BULK_AGENT_CACHE_ZIP_THRESHOLD" in script.text
    assert "/materialize-zip" in script.text
    assert "Checking local cache for ${total} files" in script.text
    assert "already local" in script.text
    assert "BULK_SLOW_WARN_THRESHOLD" in script.text
    assert "confirmLargeBulk" in script.text
    assert "keepBusy: true" in script.text
    assert "Refreshing…" in script.text
    assert "include_companions: false" in script.text
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
    assert 'selected.every((row) => row.dataset.canCheckout === "1")' in script.text
    assert 'selected.every((row) => row.dataset.canCheckin === "1")' in script.text
    assert 'selected.every((row) => row.dataset.owned === "1")' in script.text
    assert 'return row.classList.contains("is-row-hidden")' in script.text
    assert "/checkouts" in script.text
    assert "queue-row" in script.text
    assert "#changes-table" in script.text
    assert ".object-row, .folder-row, .queue-row" in script.text
    assert 'link.className = "object-open"' in script.text
    assert "dataset.relativePath" in script.text
    css = client.get("/static/css/app.css")
    assert css.status_code == 200
    assert ".grid tr.is-selected td" in css.text
    assert css.text.index(".grid tr.is-pending td") < css.text.rindex(".grid tr.is-selected td")
    assert "#changes-table td" in css.text
    assert "vertical-align: top" in css.text
    assert "span.object-open" in css.text
    assert "background: transparent !important" in css.text
    assert "appearance: none" in css.text.split(".metric {")[1].split("}")[0]
    assert ".toolbar-menu" in css.text
    assert "overflow: visible" in css.text.split(".toolbar-actions")[1].split("}")[0]
    assert "tr.is-row-hidden" in css.text
    assert "dialog:not([open])" in css.text
    assert ".tab-panel:not([hidden])" in css.text


