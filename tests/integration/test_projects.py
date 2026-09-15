from pathlib import Path

from tests.conftest import requires_git


def _create_project(client, repo_parent: Path, name: str = "Robot Arm", number: str = "PRJ-0027"):
    location = repo_parent / name.replace(" ", "")
    response = client.post(
        "/api/projects",
        json={
            "name": name,
            "number": number,
            "description": "Prototype robotic arm",
            "repository_path": str(location),
        },
    )
    assert response.status_code == 201, response.text
    return response.json(), location


@requires_git
def test_create_list_and_get_project(client, repo_parent):
    payload, location = _create_project(client, repo_parent)
    assert payload["name"] == "Robot Arm"
    assert payload["number"] == "PRJ-0027"
    assert payload["default_branch"] == "main"
    assert payload["remote_mode"] == "LOCAL_ONLY"
    assert (location / ".git").exists()
    assert (location / ".creopdm" / "project.json").exists()
    assert (location / "CAD").is_dir()

    listing = client.get("/api/projects")
    assert listing.status_code == 200
    assert any(item["uuid"] == payload["uuid"] for item in listing.json())

    fetched = client.get(f"/api/projects/{payload['uuid']}")
    assert fetched.status_code == 200
    assert Path(fetched.json()["repository_path"]) == location.resolve()


@requires_git
def test_open_workspace_launches_explorer(client, repo_parent, monkeypatch):
    opened: list[Path] = []
    monkeypatch.setattr(
        "creopdm.api.projects.open_windows_folder",
        lambda path: opened.append(path),
    )
    payload, _location = _create_project(client, repo_parent)
    response = client.post(f"/api/projects/{payload['uuid']}/workspace/open")
    assert response.status_code == 204, response.text
    assert len(opened) == 1
    assert opened[0].is_dir()
    assert payload["uuid"] in str(opened[0])


@requires_git
def test_duplicate_project_location_rejected(client, repo_parent):
    payload, location = _create_project(client, repo_parent)
    again = client.post(
        "/api/projects",
        json={
            "name": "Copy",
            "repository_path": str(location),
        },
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "DUPLICATE_PROJECT"


@requires_git
def test_delete_project_is_soft(client, repo_parent):
    payload, location = _create_project(client, repo_parent, name="Pump")
    deleted = client.delete(f"/api/projects/{payload['uuid']}")
    assert deleted.status_code == 204
    listing = client.get("/api/projects")
    assert all(item["uuid"] != payload["uuid"] for item in listing.json())
    assert location.exists()
