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
    workspace = data_dir / "workspaces" / project["uuid"] / "CAD" / "shaft.prt"
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
    assert versions[0]["relative_path"] == "CAD/shaft.prt"
    comments = [item["comment"] for item in versions]
    assert "Increased bearing diameter to 25 mm" in comments

    page = client.get(f"/projects/{project['uuid']}/objects/{obj['uuid']}")
    assert page.status_code == 200
    assert page.text.index("A.4") < page.text.index("A.3")
    assert page.text.count("CAD/shaft.prt") >= 4


@requires_git
def test_checkin_can_add_new_workspace_file(client, repo_parent, data_dir):
    project, obj = _create_part(client, repo_parent)
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    cad = data_dir / "workspaces" / project["uuid"] / "CAD"
    (cad / "pin.prt").write_bytes(b"new-pin")

    preview = client.get(f"/api/objects/{obj['uuid']}/checkin-preview")
    assert preview.status_code == 200, preview.text
    names = {item["filename"] for item in preview.json()["new_files"]}
    assert "pin.prt" in names
    pin = next(item for item in preview.json()["new_files"] if item["filename"] == "pin.prt")
    assert pin["same_folder"] is True
    assert pin["relative_path"] == "CAD/pin.prt"

    checked_in = client.post(
        f"/api/objects/{obj['uuid']}/checkin",
        json={
            "comment": "Added pin created in Creo",
            "add_relative_paths": ["CAD/pin.prt"],
        },
    )
    assert checked_in.status_code == 200, checked_in.text
    listing = client.get(f"/api/projects/{project['uuid']}/objects")
    files = {item["filename"]: item for item in listing.json()}
    assert "shaft.prt" in files
    assert "pin.prt" in files
    assert files["pin.prt"]["display_revision"] == "A.1"
    assert (Path(project["repository_path"]) / "CAD" / "pin.prt").is_file()


@requires_git
def test_checkin_keeps_creo_numbered_filename(client, repo_parent, data_dir):
    project, obj = _create_part(client, repo_parent)
    assert obj["filename"] == "shaft.prt"
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    cad = data_dir / "workspaces" / project["uuid"] / "CAD"
    (cad / "shaft.prt.4").write_bytes(b"creo-save-4")

    checked = client.post(
        f"/api/objects/{obj['uuid']}/checkin",
        json={"comment": "Saved numbered file from Creo"},
    )
    assert checked.status_code == 200, checked.text
    payload = checked.json()
    assert payload["filename"] == "shaft.prt.4"
    assert payload["relative_path"] == "CAD/shaft.prt.4"
    assert (Path(project["repository_path"]) / "CAD" / "shaft.prt.4").is_file()

    history = client.get(f"/api/objects/{obj['uuid']}/history").json()
    assert history[0]["filename"] == "shaft.prt.4"
    assert history[0]["relative_path"] == "CAD/shaft.prt.4"
    assert history[-1]["filename"] == "shaft.prt"
    assert history[-1]["relative_path"] == "CAD/shaft.prt"
