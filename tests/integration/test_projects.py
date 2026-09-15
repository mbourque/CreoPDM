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
    assert not (location / "CAD").exists()
    ignore = (location / ".gitignore").read_text(encoding="utf-8")
    assert "*.tst" in ignore
    for ext in (".inf", ".idx", ".log", ".crc", ".dat", ".out"):
        assert f"*{ext}\n" not in ignore and not ignore.endswith(f"*{ext}")

    listing = client.get("/api/projects")
    assert listing.status_code == 200
    assert any(item["uuid"] == payload["uuid"] for item in listing.json())

    fetched = client.get(f"/api/projects/{payload['uuid']}")
    assert fetched.status_code == 200
    assert Path(fetched.json()["repository_path"]) == location.resolve()


@requires_git
def test_create_project_requires_location(client, repo_parent):
    blank = client.post(
        "/api/projects",
        json={"name": "No Path", "repository_path": "   "},
    )
    assert blank.status_code in {400, 422}


@requires_git
def test_choose_location_uses_folder_picker(client, tmp_path, monkeypatch):
    chosen = tmp_path / "PickedProject"
    chosen.mkdir()
    monkeypatch.setattr(
        "creopdm.api.projects.pick_folder",
        lambda initial_dir, title="Choose project folder": chosen,
    )
    response = client.post("/api/projects/choose-location")
    assert response.status_code == 200, response.text
    assert Path(response.json()["path"]) == chosen


@requires_git
def test_rename_project_keeps_folder(client, repo_parent):
    payload, location = _create_project(client, repo_parent)
    renamed = client.patch(
        f"/api/projects/{payload['uuid']}",
        json={"name": "Robot Arm Mk2", "number": "PRJ-0099", "description": "Second build"},
    )
    assert renamed.status_code == 200, renamed.text
    body = renamed.json()
    assert body["name"] == "Robot Arm Mk2"
    assert body["number"] == "PRJ-0099"
    assert body["description"] == "Second build"
    assert Path(body["repository_path"]) == location.resolve()
    assert location.exists()
    marker = (location / ".creopdm" / "project.json").read_text(encoding="utf-8")
    assert "Robot Arm Mk2" in marker
    listing = client.get("/api/projects").json()
    names = {item["name"] for item in listing if item["uuid"] == payload["uuid"]}
    assert names == {"Robot Arm Mk2"}


@requires_git
def test_rename_project_requires_name(client, repo_parent):
    payload, _location = _create_project(client, repo_parent)
    blank = client.patch(f"/api/projects/{payload['uuid']}", json={"name": "   "})
    assert blank.status_code == 400


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
    assert (location / ".git").exists()


@requires_git
def test_forget_project_strips_git_and_keeps_cad(client, repo_parent):
    payload, location = _create_project(client, repo_parent, name="Ribbed")
    cad = location / "vise.prt.1"
    cad.write_bytes(b"keep-this-model")
    added = client.post(
        f"/api/projects/{payload['uuid']}/objects/from-disk",
        json={"paths": [str(cad)], "comment": "Test model"},
    )
    assert added.status_code == 200, added.text
    assert added.json()["ok"]

    denied = client.post(
        f"/api/projects/{payload['uuid']}/forget",
        json={"confirm_name": "wrong"},
    )
    assert denied.status_code == 400
    assert (location / ".git").exists()
    assert cad.is_file()

    forgotten = client.post(
        f"/api/projects/{payload['uuid']}/forget",
        json={"confirm_name": "Ribbed"},
    )
    assert forgotten.status_code == 200, forgotten.text
    listing = client.get("/api/projects")
    assert all(item["uuid"] != payload["uuid"] for item in listing.json())
    assert cad.is_file()
    assert cad.read_bytes() == b"keep-this-model"
    assert not (location / ".git").exists()
    assert not (location / ".gitignore").exists()
    assert not (location / ".creopdm").exists()
    assert not (location / "CAD").exists()

    again = client.post(
        "/api/projects",
        json={"name": "Ribbed again", "repository_path": str(location)},
    )
    assert again.status_code == 201, again.text
    assert cad.is_file()
