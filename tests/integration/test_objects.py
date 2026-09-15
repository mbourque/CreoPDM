from pathlib import Path

from creopdm.utils.files import remove_tree
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
    assert part["relative_path"] == "shaft.prt.3"
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
    assert doc["relative_path"] == "spec.pdf"

    listing = client.get(f"/api/projects/{project['uuid']}/objects")
    names = {item["filename"] for item in listing.json()}
    assert names == {"shaft.prt.3", "spec.pdf"}

    history = client.get(f"/api/objects/{part['uuid']}/history")
    assert history.status_code == 200
    first = history.json()[0]
    assert first["iteration"] == 1
    assert first["filename"] == "shaft.prt.3"
    assert first["relative_path"] == "shaft.prt.3"

    detail = client.get(f"/api/objects/{part['uuid']}")
    assert detail.status_code == 200
    page = client.get(f"/projects/{project['uuid']}/objects/{part['uuid']}")
    assert page.status_code == 200
    assert "File History" in page.text
    assert "shaft.prt.3" in page.text


@requires_git
def test_extra_cad_extensions_go_to_cad_folder(client, repo_parent, tmp_path):
    project, _location = _create_project(client, repo_parent)
    dxf = tmp_path / "outline.dxf"
    dxf.write_bytes(b"dxf-bytes")
    ncl = tmp_path / "rough.ncl"
    ncl.write_bytes(b"ncl-bytes")
    added = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("outline.dxf", dxf.read_bytes(), "application/octet-stream")},
        data={"comment": "DXF outline"},
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["object_type"] == "CAD"
    assert body["relative_path"] == "outline.dxf"
    toolpath = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("rough.ncl", ncl.read_bytes(), "application/octet-stream")},
        data={"comment": "NCL path"},
    )
    assert toolpath.status_code == 201, toolpath.text
    assert toolpath.json()["relative_path"] == "rough.ncl"


@requires_git
def test_numbered_extra_cad_goes_to_cad_folder(client, repo_parent, tmp_path):
    project, _location = _create_project(client, repo_parent)
    inf = tmp_path / "setup.inf.1"
    inf.write_bytes(b"inf-bytes")
    added = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("setup.inf.1", inf.read_bytes(), "application/octet-stream")},
        data={"comment": "Creo info file"},
    )
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["filename"] == "setup.inf.1"
    assert body["object_type"] == "CAD"
    assert body["relative_path"] == "setup.inf.1"
    later = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("setup.inf.2", b"later-inf", "application/octet-stream")},
        data={"comment": "Later info save"},
    )
    assert later.status_code == 409
    assert later.json()["error"]["code"] == "DUPLICATE_OBJECT"


@requires_git
def test_choose_files_starts_in_project_folder(client, repo_parent):
    project, location = _create_project(client, repo_parent)
    folder = client.get(f"/api/projects/{project['uuid']}/workspace/add-folder")
    assert folder.status_code == 200, folder.text
    payload = folder.json()
    assert payload["initial_directory"]
    assert Path(payload["initial_directory"]).is_relative_to(location.resolve())
    assert Path(payload["initial_directory"]).resolve() == location.resolve()

    leftover = location / "CAD"
    leftover.mkdir()
    again = client.get(f"/api/projects/{project['uuid']}/workspace/add-folder")
    assert Path(again.json()["initial_directory"]).resolve() == location.resolve()
    assert leftover.is_dir()

    pin = location / "pin.prt.6"
    pin.write_bytes(b"vault-pin")
    imported = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(pin)], "comment": "From project folder"},
    )
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert len(body["ok"]) == 1
    assert body["ok"][0]["filename"] == "pin.prt.6"
    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()
    assert any(item["filename"] == "pin.prt.6" and item["relative_path"] == "pin.prt.6" for item in listing)
    assert pin.is_file()
    assert pin.read_bytes() == b"vault-pin"


@requires_git
def test_from_disk_adds_only_latest_numbered_revision(client, repo_parent, tmp_path):
    project, location = _create_project(client, repo_parent)
    older = location / "parallels.prt"
    older.write_bytes(b"old-generic")
    first = location / "parallels.prt.1"
    first.write_bytes(b"rev-1")
    latest = location / "parallels.prt.3"
    latest.write_bytes(b"rev-3")
    notes = tmp_path / "notes.pdf"
    notes.write_bytes(b"%PDF-notes")
    imported = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={
            "paths": [str(older), str(first), str(latest), str(notes)],
            "comment": "Latest saves only",
        },
    )
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert not body["failed"]
    added = {item["filename"] for item in body["ok"]}
    assert added == {"parallels.prt.3", "notes.pdf"}
    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()
    names = {item["filename"] for item in listing}
    assert names == {"parallels.prt.3", "notes.pdf"}
    assert older.is_file() and first.is_file() and latest.is_file()
    assert older.read_bytes() == b"old-generic"
    assert first.read_bytes() == b"rev-1"


@requires_git
def test_import_from_vault_after_git_deleted_keeps_file(client, repo_parent):
    project, location = _create_project(client, repo_parent)
    pin = location / "keep.prt.1"
    pin.write_bytes(b"do-not-delete")
    assert remove_tree(location / ".git"), "Could not delete .git to simulate a removed repository"
    imported = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(pin)], "comment": "Re-add after git removed"},
    )
    assert imported.status_code == 200, imported.text
    assert pin.is_file()
    assert pin.read_bytes() == b"do-not-delete"
    body = imported.json()
    assert not body["failed"]
    assert len(body["ok"]) == 1
    assert (location / ".git").exists()


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
    workspace = data_dir / "workspaces" / project["uuid"] / "shaft.prt"
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
    vault = Path(project["repository_path"]) / "shaft.prt"
    assert vault.is_file()
    assert vault.read_bytes() == b"vault-bytes"


@requires_git
def test_batch_purge_workspace_keeps_originals(client, repo_parent, data_dir):
    project, location = _create_project(client, repo_parent)
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
    ids = [part["uuid"], notes["uuid"]]
    assert client.post("/api/objects/batch/checkout", json={"object_ids": ids}).status_code == 200
    workspace = data_dir / "workspaces" / project["uuid"]
    assert (workspace / "shaft.prt").is_file()
    assert (workspace / "notes.txt").is_file()

    result = client.post("/api/objects/batch/purge-workspace", json={"object_ids": ids})
    assert result.status_code == 200, result.text
    body = result.json()
    assert len(body["ok"]) == 2
    assert body["failed"] == []
    assert not (workspace / "shaft.prt").exists()
    assert not (workspace / "notes.txt").exists()
    listing = {item["uuid"]: item for item in client.get(f"/api/projects/{project['uuid']}/objects").json()}
    assert listing[part["uuid"]]["owned_by_me"] is False
    assert listing[notes["uuid"]]["owned_by_me"] is False
    assert (location / "shaft.prt").is_file()
    assert (location / "notes.txt").is_file()


@requires_git
def test_remove_from_project_keeps_original_file(client, repo_parent, data_dir):
    project, location = _create_project(client, repo_parent)
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("spec.pdf", b"%PDF-1.4 fake", "application/pdf")},
        data={"comment": "Spec"},
    )
    assert created.status_code == 201, created.text
    obj = created.json()
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    workspace = data_dir / "workspaces" / project["uuid"] / "spec.pdf"
    assert workspace.is_file()
    vault = location / "spec.pdf"
    assert vault.is_file()

    removed = client.delete(f"/api/objects/{obj['uuid']}")
    assert removed.status_code == 204, removed.text
    assert not workspace.exists()
    assert vault.is_file()
    assert vault.read_bytes() == b"%PDF-1.4 fake"
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

    workspace = data_dir / "workspaces" / project["uuid"] / "pin.prt"
    assert workspace.is_file()
    assert (location / "pin.prt").is_file()
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
    assert (location / "arm.prt").is_file()
    assert (location / "notes.txt").is_file()
