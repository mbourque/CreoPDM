from pathlib import Path
import re
import stat

from tests.conftest import requires_git


def _create_part(client, repo_parent: Path):
    location = repo_parent / "RobotArm"
    project = client.post(
        "/api/projects",
        json={"name": "Robot Arm"},
    ).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt", b"v1-content", "application/octet-stream")},
        data={"comment": "Initial model"},
    )
    assert created.status_code == 201, created.text
    return project, created.json()


def _advance_to_iteration(client, object_id: str, target: int) -> None:
    current = client.get(f"/api/objects/{object_id}").json()["iteration"]
    while current < target:
        assert client.post(f"/api/objects/{object_id}/checkout").status_code == 200
        response = client.post(
            f"/api/objects/{object_id}/checkin",
            json={"comment": f"Prepare iteration {current + 1}"},
        )
        assert response.status_code == 200, response.text
        current = response.json()["iteration"]


@requires_git
def test_checkin_increments_iteration_and_releases_lock(client, repo_parent, data_dir):
    project, obj = _create_part(client, repo_parent)
    _advance_to_iteration(client, obj["uuid"], 3)
    current = client.get(f"/api/objects/{obj['uuid']}").json()
    assert current["display_revision"] == "A.3"

    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    workspace = data_dir / "vaults" / project["uuid"] / "shaft.prt"
    workspace.write_bytes(b"bearing-diameter-25mm")

    preview = client.get(f"/api/objects/{obj['uuid']}/checkin-preview")
    assert preview.status_code == 200
    assert preview.json()["current_display"] == "A.3"
    assert preview.json()["next_display"] == "A.4"
    assert preview.json()["file_modified"] is True

    missing = client.post(f"/api/objects/{obj['uuid']}/checkin", json={"comment": "   "})
    assert missing.status_code == 422

    checked_in = client.post(
        f"/api/objects/{obj['uuid']}/checkin",
        json={"comment": "Increased bearing diameter to 25 mm"},
    )
    assert checked_in.status_code == 200, checked_in.text
    payload = checked_in.json()
    assert payload["display_revision"] == "A.4"
    assert payload["iteration"] == 4
    assert payload["can_checkout"] is True
    assert payload["owned_by_me"] is False
    assert payload["current_version"]["comment"] == "Increased bearing diameter to 25 mm"
    assert payload["current_version"]["content_hash"]
    assert not (workspace.stat().st_mode & stat.S_IWRITE)

    history = client.get(f"/api/objects/{obj['uuid']}/history")
    assert history.status_code == 200
    versions = history.json()
    assert versions[0]["iteration"] == 4
    assert versions[0]["comment"] == "Increased bearing diameter to 25 mm"
    assert versions[0]["filename"] == "shaft.prt"
    assert versions[0]["relative_path"] == "shaft.prt"
    comments = [item["comment"] for item in versions]
    assert "Increased bearing diameter to 25 mm" in comments

    page = client.get(f"/projects/{project['uuid']}/objects/{obj['uuid']}")
    assert page.status_code == 200
    assert page.text.index("A.4") < page.text.index("A.3")
    assert page.text.count("shaft.prt") >= 4


@requires_git
def test_checkin_can_add_new_workspace_file(client, repo_parent, data_dir):
    project, obj = _create_part(client, repo_parent)
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    workspace = data_dir / "vaults" / project["uuid"]
    (workspace / "pin.prt").write_bytes(b"new-pin")

    preview = client.get(f"/api/objects/{obj['uuid']}/checkin-preview")
    assert preview.status_code == 200, preview.text
    names = {item["filename"] for item in preview.json()["new_files"]}
    assert "pin.prt" in names
    pin = next(item for item in preview.json()["new_files"] if item["filename"] == "pin.prt")
    assert pin["same_folder"] is True
    assert pin["relative_path"] == "pin.prt"
    home = client.get(f"/?project={project['uuid']}")
    assert 'id="checkin-new-pick"' in home.text
    assert 'value="none"' in home.text
    assert 'value="all"' in home.text
    script = client.get("/static/js/app.js")
    assert 'input.checked = selectedNew.has(item.relative_path);' in script.text
    assert "function applyNewFilePick" in script.text
    assert "function syncNewFilePick" in script.text
    assert "function selectionIsAddOnly" in script.text
    assert 'checkinBtn.textContent = addOnly ? "Add" : "Check In";' in script.text
    assert 'title.textContent = addOnly ? "Add files" : "Check In";' in script.text
    assert "dataset.addPaths" in script.text
    assert "function pushLocalWorkspaceToVault" in script.text
    assert "Syncing local workspace to vault…" in script.text
    assert "${agentBase()}/push" in script.text
    assert "const succeeded = batchOk === null ? true : batchOk;" in script.text
    assert 'rememberWatchView({ tab: "files", ids: [] })' in script.text
    assert "window.location.replace(next)" in script.text
    assert 'url.searchParams.set("r", String(Date.now()))' in script.text

    checked_in = client.post(
        f"/api/objects/{obj['uuid']}/checkin",
        json={
            "comment": "Added pin created in Creo",
            "add_relative_paths": ["pin.prt"],
        },
    )
    assert checked_in.status_code == 200, checked_in.text
    listing = client.get(f"/api/projects/{project['uuid']}/objects")
    files = {item["filename"]: item for item in listing.json()}
    assert "shaft.prt" in files
    assert "pin.prt" in files
    assert files["pin.prt"]["display_revision"] == "A.1"
    assert (data_dir / "vaults" / project["uuid"] / "pin.prt").is_file()


@requires_git
def test_workspace_watch_stamp_changes_when_creo_saves(client, repo_parent, data_dir):
    project, obj = _create_part(client, repo_parent)
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    first = client.get(f"/api/projects/{project['uuid']}/workspace-watch")
    assert first.status_code == 200, first.text
    before = first.json()
    assert before["stamp"]
    workspace = data_dir / "vaults" / project["uuid"]
    (workspace / "shaft.prt.2").write_bytes(b"creo-save")
    second = client.get(f"/api/projects/{project['uuid']}/workspace-watch")
    assert second.status_code == 200, second.text
    after = second.json()
    assert after["stamp"] != before["stamp"]
    assert after["pending_saves"] >= 1
    listing = client.get(f"/api/objects/{obj['uuid']}")
    assert listing.status_code == 200
    assert listing.json()["modified_locally"] is True
    assert listing.json()["can_checkin"] is True


@requires_git
def test_checkin_keeps_creo_numbered_filename(client, repo_parent, data_dir):
    project, obj = _create_part(client, repo_parent)
    assert obj["filename"] == "shaft.prt"
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    workspace = data_dir / "vaults" / project["uuid"]
    (workspace / "shaft.prt.4").write_bytes(b"creo-save-4")

    preview = client.get(f"/api/objects/{obj['uuid']}/checkin-preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["filename"] == "shaft.prt.4"
    assert preview.json()["file_modified"] is True

    checked = client.post(
        f"/api/objects/{obj['uuid']}/checkin",
        json={"comment": "Saved numbered file from Creo"},
    )
    assert checked.status_code == 200, checked.text
    payload = checked.json()
    assert payload["filename"] == "shaft.prt.4"
    assert payload["relative_path"] == "shaft.prt.4"
    assert (data_dir / "vaults" / project["uuid"] / "shaft.prt.4").is_file()

    history = client.get(f"/api/objects/{obj['uuid']}/history").json()
    assert history[0]["filename"] == "shaft.prt.4"
    assert history[0]["relative_path"] == "shaft.prt.4"
    assert history[-1]["filename"] == "shaft.prt"
    assert history[-1]["relative_path"] == "shaft.prt"
    page = client.get(f"/projects/{project['uuid']}/objects/{obj['uuid']}")
    assert page.status_code == 200
    assert "shaft.prt.4" in page.text
    assert "from shaft.prt" in page.text


@requires_git
def test_checkin_uses_later_numbered_save_of_checked_out_file(client, repo_parent, data_dir):
    location = repo_parent / "RobotArm"
    project = client.post(
        "/api/projects",
        json={"name": "Robot Arm"},
    ).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt.3", b"v3-content", "application/octet-stream")},
        data={"comment": "Imported numbered save"},
    )
    assert created.status_code == 201, created.text
    obj = created.json()
    assert obj["filename"] == "shaft.prt.3"
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    workspace = data_dir / "vaults" / project["uuid"]
    assert (workspace / "shaft.prt.3").read_bytes() == b"v3-content"
    (workspace / "shaft.prt.4").write_bytes(b"creo-save-4")
    (workspace / "trail.txt.5").write_bytes(b"trail")
    (workspace / "747912f5-13ee-41f0-90d7-537c290.idx").write_bytes(b"idx")
    (workspace / "pin.prt").write_bytes(b"new-pin")

    preview = client.get(f"/api/objects/{obj['uuid']}/checkin-preview")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["filename"] == "shaft.prt.4"
    assert body["file_modified"] is True
    names = {item["filename"] for item in body["new_files"]}
    assert "shaft.prt.4" not in names
    assert "trail.txt.5" not in names
    assert "747912f5-13ee-41f0-90d7-537c290.idx" not in names
    assert "pin.prt" in names

    page = client.get(f"/projects/{project['uuid']}/objects/{obj['uuid']}")
    assert page.status_code == 200
    assert "not checked in" in page.text
    assert "shaft.prt.4" in page.text
    assert "from shaft.prt.3" in page.text
    assert "Newer Creo save in the vault" in page.text

    checked = client.post(
        f"/api/objects/{obj['uuid']}/checkin",
        json={"comment": "Saved next Creo iteration"},
    )
    assert checked.status_code == 200, checked.text
    payload = checked.json()
    assert payload["filename"] == "shaft.prt.4"
    assert payload["relative_path"] == "shaft.prt.4"
    vault = data_dir / "vaults" / project["uuid"]
    assert (vault / "shaft.prt.4").read_bytes() == b"creo-save-4"
    page = client.get(f"/projects/{project['uuid']}/objects/{obj['uuid']}")
    assert page.status_code == 200
    assert "shaft.prt.4" in page.text
    assert "from shaft.prt.3" in page.text
    assert "not checked in" not in page.text
    assert "Newer Creo save in the vault" not in page.text


@requires_git
def test_force_checkin_records_workspace_save_without_checkout(client, repo_parent, data_dir):
    location = repo_parent / "ForceArm"
    project = client.post(
        "/api/projects",
        json={"name": "Force Arm"},
    ).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt.3", b"v3", "application/octet-stream")},
        data={"comment": "Initial"},
    ).json()
    assert client.post(f"/api/objects/{created['uuid']}/checkout").status_code == 200
    workspace = data_dir / "vaults" / project["uuid"]
    (workspace / "shaft.prt.4").write_bytes(b"save-4")
    assert client.post(
        f"/api/objects/{created['uuid']}/checkin",
        json={"comment": "Recorded .4"},
    ).status_code == 200
    (workspace / "shaft.prt.5").write_bytes(b"save-5")

    listing = client.get(f"/api/objects/{created['uuid']}").json()
    assert listing["owned_by_me"] is False
    assert listing["can_checkout"] is True
    assert listing["can_checkin"] is True
    assert listing["checkout_status"] == "Modified locally"

    preview = client.get(f"/api/objects/{created['uuid']}/checkin-preview").json()
    assert preview["filename"] == "shaft.prt.5"
    assert preview["force_checkin"] is True
    assert preview["can_checkin"] is True
    assert "not checked out" in preview["warning"]

    checked = client.post(
        f"/api/objects/{created['uuid']}/checkin",
        json={"comment": "Force record .5"},
    )
    assert checked.status_code == 200, checked.text
    payload = checked.json()
    assert payload["filename"] == "shaft.prt.5"
    assert payload["owned_by_me"] is False
    assert payload["can_checkin"] is False
    assert (workspace / "shaft.prt.5").read_bytes() == b"save-5"


@requires_git
def test_checkin_after_undo_checkout_records_numbered_save(client, repo_parent, data_dir):
    project, obj = _create_part(client, repo_parent)
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    workspace = data_dir / "vaults" / project["uuid"]
    (workspace / "shaft.prt.2").write_bytes(b"creo-save")
    undone = client.post(f"/api/objects/{obj['uuid']}/undo-checkout")
    assert undone.status_code == 200, undone.text
    listing = undone.json()
    assert listing["owned_by_me"] is False
    assert listing["can_checkin"] is True
    page = client.get(f"/projects/{project['uuid']}/objects/{obj['uuid']}")
    assert page.status_code == 200
    match = re.search(r'<button[^>]*id="checkin-btn"[^>]*>', page.text)
    assert match, page.text
    assert "disabled" not in match.group(0)
    checked = client.post(
        f"/api/objects/{obj['uuid']}/checkin",
        json={"comment": "Keep the Creo save after undo"},
    )
    assert checked.status_code == 200, checked.text
    payload = checked.json()
    assert payload["filename"] == "shaft.prt.2"
    assert payload["current_version"]["comment"] == "Keep the Creo save after undo"


@requires_git
def test_checkout_keeps_newer_workspace_save(client, repo_parent, data_dir):
    location = repo_parent / "KeepLocal"
    project = client.post(
        "/api/projects",
        json={"name": "Keep Local"},
    ).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("pin.prt.1", b"v1", "application/octet-stream")},
        data={"comment": "Initial"},
    ).json()
    assert client.post(f"/api/objects/{created['uuid']}/checkout").status_code == 200
    workspace = data_dir / "vaults" / project["uuid"]
    assert client.post(
        f"/api/objects/{created['uuid']}/checkin",
        json={"comment": "Done"},
    ).status_code == 200
    (workspace / "pin.prt.2").write_bytes(b"kept-local")
    checked_out = client.post(f"/api/objects/{created['uuid']}/checkout")
    assert checked_out.status_code == 200, checked_out.text
    assert (workspace / "pin.prt.2").read_bytes() == b"kept-local"


@requires_git
def test_project_would_checkin_lists_saves_and_new_files(client, repo_parent, data_dir):
    location = repo_parent / "QueueArm"
    project = client.post(
        "/api/projects",
        json={"name": "Queue Arm"},
    ).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt.3", b"v3", "application/octet-stream")},
        data={"comment": "Initial"},
    ).json()
    assert client.post(f"/api/objects/{created['uuid']}/checkout").status_code == 200
    workspace = data_dir / "vaults" / project["uuid"]
    (workspace / "shaft.prt.4").write_bytes(b"save-4")
    (workspace / "bushing.prt").write_bytes(b"new-bushing")
    page = client.get(f"/?project={project['uuid']}")
    assert page.status_code == 200, page.text
    assert "Files checked out · 1" in page.text
    assert "New files" in page.text
    assert "Files checked out" in page.text
    assert page.text.index("Files checked out") < page.text.index("New files")
    assert 'data-tab="checked-out"' in page.text
    assert 'id="checked-out-table"' in page.text
    assert "New files · 2" not in page.text
    assert "Newer Creo save" not in page.text
    match = re.search(r'<button[^>]*id="checkin-btn"[^>]*>', page.text)
    assert match, page.text
    assert "hidden" in match.group(0)
    assert "disabled" in match.group(0)
    assert "Delete project" in page.text
    assert "Forget project" not in page.text
    assert 'id="project-settings-btn"' in page.text
    assert 'id="delete-project-btn"' in page.text
    assert 'id="rename-project-btn"' in page.text
    assert 'id="delete-project-dialog"' in page.text
    assert "project-settings-menu" in page.text
    assert 'id="danger-confirm-dialog"' in page.text
    assert 'data-project-name="Queue Arm"' in page.text
    queue = client.get(f"/api/projects/{project['uuid']}/checkin-queue")
    assert queue.status_code == 200, queue.text
    body = queue.json()
    saves = {item["filename"] for item in body["saves"]}
    created_names = {item["filename"] for item in body["new_files"]}
    assert "shaft.prt.4" in saves
    assert "bushing.prt" in created_names
    bushing = next(item for item in body["new_files"] if item["filename"] == "bushing.prt")
    assert bushing.get("saved_at")
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", str(bushing["saved_at"]))
    script = client.get("/static/js/app.js")
    assert script.status_code == 200
    assert 'btn.className = "object-open"' in script.text
    assert "relative_path: spec.relativePath" in script.text
    assert "confirmByProjectName" in script.text
    assert "Type the project name exactly to confirm." in script.text
    assert "rowHistoryHref" in script.text
    assert "objects/${meta.uuid}#history" in script.text
    assert script.text.count('addEventListener("dblclick", onFileTableDblclick)') >= 3



@requires_git
def test_project_checkin_queue_adds_new_workspace_file_without_checkout(client, repo_parent, data_dir):
    location = repo_parent / "NewFileArm"
    project = client.post(
        "/api/projects",
        json={"name": "New File Arm"},
    ).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt", b"v1", "application/octet-stream")},
        data={"comment": "Initial"},
    )
    assert created.status_code == 201, created.text
    workspace = data_dir / "vaults" / project["uuid"]
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "bushing.prt").write_bytes(b"new-bushing")
    page = client.get(f"/?project={project['uuid']}")
    assert page.status_code == 200, page.text
    match = re.search(r'<button[^>]*id="checkin-btn"[^>]*>', page.text)
    assert match, page.text
    assert "hidden" in match.group(0)
    assert "disabled" in match.group(0)
    preview = client.get(f"/api/projects/{project['uuid']}/checkin-preview")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["queue_mode"] is True
    assert body["can_checkin"] is True
    names = {item["filename"] for item in body["new_files"]}
    assert names == {"bushing.prt"}
    added = client.post(
        f"/api/projects/{project['uuid']}/checkin-queue",
        json={"comment": "Add bushing from workspace", "add_relative_paths": ["bushing.prt"]},
    )
    assert added.status_code == 200, added.text
    payload = added.json()
    assert payload["failed"] == []
    assert payload["ok"][0]["filename"] == "bushing.prt"
    listing = client.get(f"/api/projects/{project['uuid']}/objects")
    assert listing.status_code == 200, listing.text
    listed = {item["filename"] for item in listing.json()}
    assert "bushing.prt" in listed
    assert "shaft.prt" in listed
    assert (workspace / "bushing.prt").read_bytes() == b"new-bushing"


@requires_git
def test_purge_workspace_paths_removes_new_files(client, repo_parent, data_dir):
    project = client.post(
        "/api/projects",
        json={"name": "Purge New Files"},
    ).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt", b"v1", "application/octet-stream")},
        data={"comment": "Initial"},
    )
    assert created.status_code == 201, created.text
    workspace = data_dir / "vaults" / project["uuid"]
    (workspace / "bushing.prt").write_bytes(b"new-bushing")
    (workspace / "bushing.prt.2").write_bytes(b"newer-bushing")
    (workspace / "pin.prt").write_bytes(b"new-pin")

    queue = client.get(f"/api/projects/{project['uuid']}/checkin-queue")
    assert queue.status_code == 200, queue.text
    names = {item["filename"] for item in queue.json()["new_files"]}
    assert "bushing.prt.2" in names
    assert "pin.prt" in names

    purged = client.post(
        f"/api/projects/{project['uuid']}/workspace/purge-paths",
        json={"relative_paths": ["bushing.prt.2"]},
    )
    assert purged.status_code == 200, purged.text
    body = purged.json()
    assert body["failed"] == []
    removed = {item["filename"] for item in body["ok"]}
    assert "bushing.prt" in removed
    assert "bushing.prt.2" in removed
    assert not (workspace / "bushing.prt").exists()
    assert not (workspace / "bushing.prt.2").exists()
    assert (workspace / "pin.prt").is_file()
    assert (workspace / "shaft.prt").is_file()

    denied = client.post(
        f"/api/projects/{project['uuid']}/workspace/purge-paths",
        json={"relative_paths": ["shaft.prt"]},
    )
    assert denied.status_code == 200, denied.text
    assert denied.json()["ok"] == []
    assert denied.json()["failed"]
    assert (workspace / "shaft.prt").is_file()

    script = client.get("/static/js/app.js")
    assert script.status_code == 200
    assert "workspace/purge-paths" in script.text
    assert "isNewFileQueueRow" in script.text


@requires_git
def test_project_checkin_queue_records_pending_save_and_new_file(client, repo_parent, data_dir):
    location = repo_parent / "QueueCheckin"
    project = client.post(
        "/api/projects",
        json={"name": "Queue Checkin"},
    ).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt.3", b"v3", "application/octet-stream")},
        data={"comment": "Initial"},
    ).json()
    assert client.post(f"/api/objects/{created['uuid']}/checkout").status_code == 200
    workspace = data_dir / "vaults" / project["uuid"]
    (workspace / "shaft.prt.4").write_bytes(b"save-4")
    (workspace / "bushing.prt").write_bytes(b"new-bushing")
    preview = client.get(f"/api/projects/{project['uuid']}/checkin-preview")
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert created["uuid"] in body["object_ids"]
    assert "shaft.prt.4" in body["pending_files"]
    result = client.post(
        f"/api/projects/{project['uuid']}/checkin-queue",
        json={
            "comment": "Save numbered revision and add bushing",
            "object_ids": body["object_ids"],
            "add_relative_paths": ["bushing.prt"],
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["failed"] == []
    current = client.get(f"/api/objects/{created['uuid']}").json()
    assert current["filename"] == "shaft.prt.4"
    listing = {item["filename"] for item in client.get(f"/api/projects/{project['uuid']}/objects").json()}
    assert "bushing.prt" in listing
    assert (workspace / "shaft.prt.4").read_bytes() == b"save-4"


_CREO_UGC_HEADER = (
    "#UGC:2 PART 1 1 1 1 1 1 1 1 00000000 \\\n"
    "#-END_OF_UGC_HEADER\n"
    "#Creo  TM  13  (c) 2026 by PTC Inc.  All Rights Reserved. 13.4.1.0\n"
    "#UGC_TOC 2 32 81 17#############################################################"
).encode("ascii")

_CREO_UGC_HEADER_NEXT = (
    "#UGC:2 PART 1 1 1 1 1 1 1 1 00000000 \\\n"
    "#-END_OF_UGC_HEADER\n"
    "#Creo  TM  13  (c) 2026 by PTC Inc.  All Rights Reserved. 13.4.2.0\n"
    "#UGC_TOC 2 32 81 17#############################################################"
).encode("ascii")


@requires_git
def test_checkin_records_creo_release_from_workspace_file(client, repo_parent, data_dir):
    project = client.post("/api/projects", json={"name": "Robot Arm"}).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt.1", _CREO_UGC_HEADER, "application/octet-stream")},
        data={"comment": "Initial model"},
    )
    assert created.status_code == 201, created.text
    obj = created.json()
    assert obj["creo_release"] == "13.4.1.0"
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    workspace = data_dir / "vaults" / project["uuid"] / "shaft.prt.1"
    workspace.write_bytes(_CREO_UGC_HEADER_NEXT)
    checked = client.post(
        f"/api/objects/{obj['uuid']}/checkin",
        json={"comment": "Saved in a newer Creo build"},
    )
    assert checked.status_code == 200, checked.text
    payload = checked.json()
    assert payload["creo_release"] == "13.4.2.0"
    assert payload["current_version"]["creo_release"] == "13.4.2.0"
    history = client.get(f"/api/objects/{obj['uuid']}/history").json()
    assert [item["creo_release"] for item in history] == ["13.4.2.0", "13.4.1.0"]


@requires_git
def test_workspace_content_put_then_checkin(client, repo_parent, data_dir, identity):
    project, obj = _create_part(client, repo_parent)
    vault = data_dir / "vaults" / project["uuid"] / "shaft.prt"
    assert vault.read_bytes() == b"v1-content"

    denied = client.put(
        f"/api/objects/{obj['uuid']}/workspace-content",
        files={"file": ("shaft.prt", b"not-owned", "application/octet-stream")},
    )
    assert denied.status_code == 403, denied.text

    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    uploaded = client.put(
        f"/api/objects/{obj['uuid']}/workspace-content",
        files={"file": ("shaft.prt.4", b"from-agent-cache", "application/octet-stream")},
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["ok"] is True
    assert body["object_id"] == obj["uuid"]
    assert body["filename"] == "shaft.prt.4"
    assert body["bytes_written"] == len(b"from-agent-cache")
    staged = data_dir / "vaults" / project["uuid"] / "shaft.prt.4"
    assert staged.read_bytes() == b"from-agent-cache"

    wrong_name = client.put(
        f"/api/objects/{obj['uuid']}/workspace-content",
        files={"file": ("other.prt", b"nope", "application/octet-stream")},
    )
    assert wrong_name.status_code == 400, wrong_name.text

    identity.become("Bob", "ENG-PC-18")
    other_user = client.put(
        f"/api/objects/{obj['uuid']}/workspace-content",
        files={"file": ("shaft.prt", b"stolen", "application/octet-stream")},
    )
    assert other_user.status_code == 403, other_user.text
    identity.become("Alice", "ENG-PC-17")

    preview = client.get(f"/api/objects/{obj['uuid']}/checkin-preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["file_modified"] is True
    assert preview.json()["can_checkin"] is True

    checked = client.post(
        f"/api/objects/{obj['uuid']}/checkin",
        json={"comment": "Synced agent workspace into vault"},
    )
    assert checked.status_code == 200, checked.text
    payload = checked.json()
    assert payload["iteration"] == 2
    assert payload["owned_by_me"] is False
    assert payload["current_version"]["content_hash"]
    history = client.get(f"/api/objects/{obj['uuid']}/history").json()
    assert history[0]["comment"] == "Synced agent workspace into vault"
