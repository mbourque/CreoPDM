from pathlib import Path

from tests.conftest import requires_git


def _create_project(client, repo_parent: Path):
    location = repo_parent / "RobotArm"
    response = client.post(
        "/api/projects",
        json={
            "name": "Robot Arm",
            "number": "PRJ-0027",
            "repository_path": str(location),
        },
    )
    assert response.status_code == 201, response.text
    return response.json(), location


@requires_git
def test_import_creo_and_document_files(client, repo_parent, tmp_path):
    project, _location = _create_project(client, repo_parent)
    prt = tmp_path / "shaft.prt.3"
    prt.write_bytes(b"FAKE CREO PART")
    pdf = tmp_path / "spec.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    part_resp = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt.3", prt.read_bytes(), "application/octet-stream")},
        data={"comment": "Initial shaft"},
    )
    assert part_resp.status_code == 201, part_resp.text
    part = part_resp.json()
    assert part["filename"] == "shaft.prt.3"
    assert part["object_type"] == "CREO_PART"
    assert part["display_revision"] == "A.1"
    assert part["relative_path"] == "CAD/shaft.prt.3"
    assert part["current_version"]["content_hash"]
    assert part["current_version"]["comment"] == "Initial shaft"

    doc_resp = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("spec.pdf", pdf.read_bytes(), "application/pdf")},
        data={"comment": "Requirements"},
    )
    assert doc_resp.status_code == 201, doc_resp.text
    doc = doc_resp.json()
    assert doc["object_type"] == "PDF"
    assert doc["relative_path"] == "Documents/spec.pdf"

    listing = client.get(f"/api/projects/{project['uuid']}/objects")
    names = {item["filename"] for item in listing.json()}
    assert names == {"shaft.prt.3", "spec.pdf"}

    history = client.get(f"/api/objects/{part['uuid']}/history")
    assert history.status_code == 200
    first = history.json()[0]
    assert first["iteration"] == 1
    assert first["filename"] == "shaft.prt.3"
    assert first["relative_path"] == "CAD/shaft.prt.3"

    detail = client.get(f"/api/objects/{part['uuid']}")
    assert detail.status_code == 200
    page = client.get(f"/projects/{project['uuid']}/objects/{part['uuid']}")
    assert page.status_code == 200
    assert "File History" in page.text
    assert "CAD/shaft.prt.3" in page.text


@requires_git
def test_choose_files_starts_in_workspace(client, repo_parent, data_dir):
    project, _location = _create_project(client, repo_parent)
    folder = client.get(f"/api/projects/{project['uuid']}/workspace/add-folder")
    assert folder.status_code == 200, folder.text
    payload = folder.json()
    assert payload["initial_directory"]
    workspace = data_dir / "workspaces" / project["uuid"]
    assert str(workspace) in payload["workspace_root"]
    assert payload["initial_directory"].rstrip("\\/").endswith("CAD")

    cad = workspace / "CAD"
    cad.mkdir(parents=True, exist_ok=True)
    pin = cad / "pin.prt.6"
    pin.write_bytes(b"workspace-pin")
    imported = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(pin)], "comment": "From workspace"},
    )
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert len(body["ok"]) == 1
    assert body["ok"][0]["filename"] == "pin.prt.6"
    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()
    assert any(item["filename"] == "pin.prt.6" and item["relative_path"] == "CAD/pin.prt.6" for item in listing)


@requires_git
def test_duplicate_object_rejected(client, repo_parent, tmp_path):
    project, _location = _create_project(client, repo_parent)
    payload = b"part-bytes"
    first = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("base.prt", payload, "application/octet-stream")},
        data={"comment": "Add base"},
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("base.prt", payload, "application/octet-stream")},
        data={"comment": "Add base again"},
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "DUPLICATE_OBJECT"


@requires_git
def test_numbered_creo_file_is_same_object(client, repo_parent):
    project, _location = _create_project(client, repo_parent)
    first = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("base.prt.3", b"part-bytes", "application/octet-stream")},
        data={"comment": "Add base"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["filename"] == "base.prt.3"
    second = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("base.prt.4", b"later-save", "application/octet-stream")},
        data={"comment": "Add later save"},
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "DUPLICATE_OBJECT"


@requires_git
def test_path_traversal_on_import_rejected(client, repo_parent):
    project, _location = _create_project(client, repo_parent)
    response = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("evil.prt", b"nope", "application/octet-stream")},
        data={"comment": "bad", "relative_path": "../outside.prt"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_PATH"


@requires_git
def test_project_status_counts(client, repo_parent, tmp_path):
    project, _location = _create_project(client, repo_parent)
    client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("arm.asm", b"asm", "application/octet-stream")},
        data={"comment": "assembly"},
    )
    status = client.get(f"/api/projects/{project['uuid']}/status")
    assert status.status_code == 200
    body = status.json()
    assert body["files"] == 1
    assert body["assemblies"] == 1


@requires_git
def test_creo_status_is_disconnected(client):
    response = client.get("/api/creo/status")
    assert response.status_code == 200
    body = response.json()
    assert body["label"] in {"Not Connected", "Installed", "Connected"}


@requires_git
def test_purge_workspace_keeps_vault_file(client, repo_parent, data_dir):
    project, _location = _create_project(client, repo_parent)
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt", b"vault-bytes", "application/octet-stream")},
        data={"comment": "Initial model"},
    )
    assert created.status_code == 201, created.text
    obj = created.json()
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    workspace = data_dir / "workspaces" / project["uuid"] / "CAD" / "shaft.prt"
    extra = workspace.with_name("shaft.prt.4")
    extra.write_bytes(b"later-save")
    assert workspace.is_file()

    purged = client.post(f"/api/objects/{obj['uuid']}/purge-workspace")
    assert purged.status_code == 204, purged.text
    assert not workspace.exists()
    assert not extra.exists()

    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()
    assert any(item["uuid"] == obj["uuid"] for item in listing)
    detail = client.get(f"/api/objects/{obj['uuid']}")
    assert detail.status_code == 200
    assert detail.json()["owned_by_me"] is False
    vault = Path(project["repository_path"]) / "CAD" / "shaft.prt"
    assert vault.is_file()
    assert vault.read_bytes() == b"vault-bytes"


@requires_git
def test_remove_from_project_deletes_vault_and_metadata(client, repo_parent, data_dir):
    project, location = _create_project(client, repo_parent)
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("spec.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"comment": "Spec"},
    )
    assert created.status_code == 201, created.text
    obj = created.json()
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    workspace = data_dir / "workspaces" / project["uuid"] / "Documents" / "spec.pdf"
    assert workspace.is_file()
    vault = location / "Documents" / "spec.pdf"
    assert vault.is_file()

    removed = client.delete(f"/api/objects/{obj['uuid']}")
    assert removed.status_code == 204, removed.text
    assert not workspace.exists()
    assert not vault.exists()
    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()
    assert listing == []
    missing = client.get(f"/api/objects/{obj['uuid']}")
    assert missing.status_code == 404


@requires_git
def test_cannot_remove_file_checked_out_by_someone_else(client, repo_parent, identity, data_dir):
    project, location = _create_project(client, repo_parent)
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("pin.prt", b"pin", "application/octet-stream")},
        data={"comment": "Pin"},
    )
    obj = created.json()
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200

    identity.become("Bob", "ENG-PC-18")
    denied_purge = client.post(f"/api/objects/{obj['uuid']}/purge-workspace")
    assert denied_purge.status_code == 403
    assert denied_purge.json()["error"]["code"] == "CHECKOUT_OWNERSHIP"
    denied_delete = client.delete(f"/api/objects/{obj['uuid']}")
    assert denied_delete.status_code == 403
    assert denied_delete.json()["error"]["code"] == "CHECKOUT_OWNERSHIP"

    workspace = data_dir / "workspaces" / project["uuid"] / "CAD" / "pin.prt"
    assert workspace.is_file()
    assert (location / "CAD" / "pin.prt").is_file()
    still = client.get(f"/api/objects/{obj['uuid']}")
    assert still.status_code == 200
    assert still.json()["checkout_user"] == "Alice"


@requires_git
def test_batch_remove_from_project(client, repo_parent):
    project, location = _create_project(client, repo_parent)
    part = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("arm.prt", b"part", "application/octet-stream")},
        data={"comment": "Part"},
    ).json()
    notes = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"comment": "Notes"},
    ).json()
    result = client.post(
        "/api/objects/batch/remove",
        json={"object_ids": [part["uuid"], notes["uuid"]]},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert len(body["ok"]) == 2
    assert body["failed"] == []
    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()
    assert listing == []
    assert not (location / "CAD" / "arm.prt").exists()
    assert not (location / "Documents" / "notes.txt").exists()
