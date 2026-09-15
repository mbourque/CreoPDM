from pathlib import Path
import stat

from tests.conftest import requires_git


def _create_part(client, repo_parent: Path):
    location = repo_parent / "RobotArm"
    project = client.post(
        "/api/projects",
        json={"name": "Robot Arm", "repository_path": str(location)},
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
    workspace = data_dir / "workspaces" / project["uuid"] / "shaft.prt"
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
    workspace = data_dir / "workspaces" / project["uuid"]
    (workspace / "pin.prt").write_bytes(b"new-pin")

    preview = client.get(f"/api/objects/{obj['uuid']}/checkin-preview")
    assert preview.status_code == 200, preview.text
    names = {item["filename"] for item in preview.json()["new_files"]}
    assert "pin.prt" in names
    pin = next(item for item in preview.json()["new_files"] if item["filename"] == "pin.prt")
    assert pin["same_folder"] is True
    assert pin["relative_path"] == "pin.prt"

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
    assert (Path(project["repository_path"]) / "pin.prt").is_file()


@requires_git
def test_checkin_keeps_creo_numbered_filename(client, repo_parent, data_dir):
    project, obj = _create_part(client, repo_parent)
    assert obj["filename"] == "shaft.prt"
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    workspace = data_dir / "workspaces" / project["uuid"]
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
    assert (Path(project["repository_path"]) / "shaft.prt.4").is_file()

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
        json={"name": "Robot Arm", "repository_path": str(location)},
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
    workspace = data_dir / "workspaces" / project["uuid"]
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
    assert "Newer Creo save in the workspace" in page.text

    checked = client.post(
        f"/api/objects/{obj['uuid']}/checkin",
        json={"comment": "Saved next Creo iteration"},
    )
    assert checked.status_code == 200, checked.text
    payload = checked.json()
    assert payload["filename"] == "shaft.prt.4"
    assert payload["relative_path"] == "shaft.prt.4"
    vault = Path(project["repository_path"])
    assert (vault / "shaft.prt.4").read_bytes() == b"creo-save-4"
    page = client.get(f"/projects/{project['uuid']}/objects/{obj['uuid']}")
    assert page.status_code == 200
    assert "shaft.prt.4" in page.text
    assert "from shaft.prt.3" in page.text
    assert "not checked in" not in page.text
    assert "Newer Creo save in the workspace" not in page.text


@requires_git
def test_force_checkin_records_workspace_save_without_checkout(client, repo_parent, data_dir):
    location = repo_parent / "ForceArm"
    project = client.post(
        "/api/projects",
        json={"name": "Force Arm", "repository_path": str(location)},
    ).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt.3", b"v3", "application/octet-stream")},
        data={"comment": "Initial"},
    ).json()
    assert client.post(f"/api/objects/{created['uuid']}/checkout").status_code == 200
    workspace = data_dir / "workspaces" / project["uuid"]
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
    assert (Path(project["repository_path"]) / "shaft.prt.5").read_bytes() == b"save-5"


@requires_git
def test_checkout_keeps_newer_workspace_save(client, repo_parent, data_dir):
    location = repo_parent / "KeepLocal"
    project = client.post(
        "/api/projects",
        json={"name": "Keep Local", "repository_path": str(location)},
    ).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("pin.prt.1", b"v1", "application/octet-stream")},
        data={"comment": "Initial"},
    ).json()
    assert client.post(f"/api/objects/{created['uuid']}/checkout").status_code == 200
    workspace = data_dir / "workspaces" / project["uuid"]
    assert client.post(
        f"/api/objects/{created['uuid']}/checkin",
        json={"comment": "Done"},
    ).status_code == 200
    (workspace / "pin.prt.2").write_bytes(b"kept-local")
    checked_out = client.post(f"/api/objects/{created['uuid']}/checkout")
    assert checked_out.status_code == 200, checked_out.text
    assert (workspace / "pin.prt.2").read_bytes() == b"kept-local"
