from pathlib import Path

from creopdm.utils.files import remove_tree
from tests.conftest import requires_git


def _create_project(client, repo_parent: Path):
    location = repo_parent / "RobotArm"
    location.mkdir(parents=True, exist_ok=True)
    response = client.post(
        "/api/projects",
        json={
            "name": "Robot Arm",
            "number": "PRJ-0027",
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
    assert first.get("creo_release") in {None, ""}

    detail = client.get(f"/api/objects/{part['uuid']}")
    assert detail.status_code == 200
    page = client.get(f"/projects/{project['uuid']}/objects/{part['uuid']}")
    assert page.status_code == 200
    assert "File History" in page.text
    assert "shaft.prt.3" in page.text


@requires_git
def test_import_from_uploads_keeps_relative_paths(client, repo_parent):
    project, _location = _create_project(client, repo_parent)
    added = client.post(
        f"/api/projects/{project['uuid']}/objects/from-uploads",
        files=[
            ("files", ("shaft.prt", b"part-bytes", "application/octet-stream")),
            ("files", ("notes.txt", b"hello", "text/plain")),
        ],
        data={"relative_paths": ["CAD/shaft.prt", "notes.txt"], "comment": "Dropped"},
    )
    assert added.status_code == 200, added.text
    body = added.json()
    assert {item["filename"] for item in body["ok"]} == {"shaft.prt", "notes.txt"}
    assert body["failed"] == []
    listing = {item["filename"]: item["relative_path"] for item in client.get(f"/api/projects/{project['uuid']}/objects").json()}
    assert listing["shaft.prt"] == "CAD/shaft.prt"
    assert listing["notes.txt"] == "notes.txt"


@requires_git
def test_search_objects_includes_nested_folders(client, repo_parent):
    project, _location = _create_project(client, repo_parent)
    added = client.post(
        f"/api/projects/{project['uuid']}/objects/from-uploads",
        files=[
            ("files", ("shaft.prt", b"part-bytes", "application/octet-stream")),
            ("files", ("pin.prt", b"pin-bytes", "application/octet-stream")),
        ],
        data={"relative_paths": ["CAD/shaft.prt", "Incoming/lib/pin.prt"], "comment": "Nested"},
    )
    assert added.status_code == 200, added.text
    assert added.json()["failed"] == []
    by_name = client.get(f"/api/projects/{project['uuid']}/objects", params={"q": "pin"})
    assert by_name.status_code == 200, by_name.text
    assert {item["relative_path"] for item in by_name.json()} == {"Incoming/lib/pin.prt"}
    by_folder = client.get(f"/api/projects/{project['uuid']}/objects", params={"q": "Incoming"})
    assert {item["relative_path"] for item in by_folder.json()} == {"Incoming/lib/pin.prt"}
    home = client.get(f"/?project={project['uuid']}&folder=")
    assert home.status_code == 200, home.text
    assert ">pin.prt</button>" not in home.text
    assert 'id="search-scope"' in home.text
    assert "Showing matches from all folders." in home.text
    script = client.get("/static/js/app.js")
    assert script.status_code == 200
    assert "function searchAllFolders" in script.text
    assert "function updateMetricCounts" in script.text
    assert "function listedMetricRows" in script.text
    assert "/objects?q=" in script.text


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
def test_ignored_session_files_are_not_added(client, repo_parent, tmp_path):
    project, _location = _create_project(client, repo_parent)
    rejected = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("trail.txt", b"junk", "application/octet-stream")},
        data={"comment": "Should not store"},
    )
    assert rejected.status_code in {400, 422}, rejected.text
    trail = tmp_path / "proimpex.errors"
    trail.write_bytes(b"nope")
    part = tmp_path / "pin.prt"
    part.write_bytes(b"pin")
    imported = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(trail), str(part)], "comment": "Mixed add"},
    )
    assert imported.status_code == 200, imported.text
    names = {item["filename"] for item in imported.json()["ok"]}
    assert names == {"pin.prt"}
    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()
    assert {item["filename"] for item in listing} == {"pin.prt"}


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
    assert later.status_code == 201, later.text
    body = later.json()
    assert body["uuid"] == added.json()["uuid"]
    assert body["filename"] == "setup.inf.2"
    assert body["display_revision"] == "A.2"


@requires_git
def test_choose_files_starts_in_project_folder(client, repo_parent):
    project, location = _create_project(client, repo_parent)
    folder = client.get(f"/api/projects/{project['uuid']}/workspace/add-folder")
    assert folder.status_code == 200, folder.text
    payload = folder.json()
    assert payload["initial_directory"]
    assert Path(payload["initial_directory"]).is_dir()

    leftover = location / "CAD"
    leftover.mkdir()
    again = client.get(f"/api/projects/{project['uuid']}/workspace/add-folder")
    assert Path(again.json()["initial_directory"]).is_dir()
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
    page = client.get(f"/?project={project['uuid']}")
    assert page.status_code == 200
    assert 'id="chosen-file-summary"' in page.text
    assert 'id="chosen-file-list"' not in page.text
    assert 'id="add-file-input"' in page.text
    assert 'id="add-folder-input"' in page.text
    assert 'webkitdirectory' in page.text
    script = client.get("/static/js/app.js")
    assert "function browseLocalFiles" in script.text
    assert "function useNativePicker" in script.text


@requires_git
def test_choose_files_omits_ignored_and_older_saves(client, repo_parent, monkeypatch):
    project, location = _create_project(client, repo_parent)
    pin = location / "pin.prt"
    trail = location / "trail.txt"
    older = location / "shaft.prt.1"
    newer = location / "shaft.prt.4"
    pin.write_bytes(b"pin")
    trail.write_bytes(b"nope")
    older.write_bytes(b"1")
    newer.write_bytes(b"4")
    monkeypatch.setattr(
        "creopdm.api.projects.pick_files",
        lambda initial_dir, title="Add files to the project": [pin, trail, older, newer],
    )
    response = client.post(f"/api/projects/{project['uuid']}/workspace/choose-files")
    assert response.status_code == 200, response.text
    body = response.json()
    names = {Path(path).name for path in body["selected"]}
    assert names == {"pin.prt", "shaft.prt.4"}
    assert body["ignored_count"] == 1


@requires_git
def test_choose_folder_lists_latest_files(client, repo_parent, monkeypatch, data_dir):
    project, location = _create_project(client, repo_parent)
    picked = location / "Incoming"
    nested = picked / "lib"
    nested.mkdir(parents=True)
    (picked / "shaft.prt.1").write_bytes(b"1")
    (picked / "shaft.prt.4").write_bytes(b"4")
    (nested / "pin.prt").write_bytes(b"pin")
    (picked / "trail.txt").write_bytes(b"nope")
    monkeypatch.setattr(
        "creopdm.api.projects.pick_folder",
        lambda initial_dir, title="Add a folder to the project": picked,
    )
    response = client.post(f"/api/projects/{project['uuid']}/workspace/choose-folder")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cancelled"] is False
    assert body["folder"] == str(picked)
    assert body["selected"] == []
    imported = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"folder": str(picked), "comment": "Folder add", "base_folder": str(picked)},
    )
    assert imported.status_code == 200, imported.text
    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()
    listed = {item["filename"]: item["relative_path"] for item in listing}
    assert listed == {"shaft.prt.4": "Incoming/shaft.prt.4", "pin.prt": "Incoming/lib/pin.prt"}
    page = client.get(f"/?project={project['uuid']}")
    assert page.status_code == 200, page.text
    assert 'class="folder-row"' in page.text
    assert 'class="folder-open"' in page.text
    assert 'data-folder="Incoming"' in page.text
    assert 'data-folder="Incoming/lib"' not in page.text
    assert "pin.prt" not in page.text
    assert 'id="metric-filters"' in page.text
    inside = client.get(f"/?project={project['uuid']}&folder=Incoming")
    assert inside.status_code == 200, inside.text
    assert 'data-folder="Incoming/lib"' in inside.text
    assert "shaft.prt.4" in inside.text
    assert 'id="metric-filters"' in inside.text
    assert 'data-filter="cad_models"' in inside.text
    assert "disabled" not in inside.text.split('data-filter="cad_models"')[1].split("</button>")[0]
    assert 'data-cad-models="' in inside.text
    assert ".prt" in inside.text.split('data-cad-models="')[1].split('"')[0]
    assert 'data-extension=".prt"' in inside.text
    assert 'data-filter="creo_parts"' in inside.text
    assert "disabled" not in inside.text.split('data-filter="creo_parts"')[1].split("</button>")[0]
    assert "disabled" not in inside.text.split('data-filter="assemblies"')[1].split("</button>")[0]
    assert "disabled" not in inside.text.split('data-filter="drawings"')[1].split("</button>")[0]
    assert "disabled" not in inside.text.split('data-filter="checked_out"')[1].split("</button>")[0]
    nested = client.get(f"/?project={project['uuid']}&folder=Incoming/lib")
    assert nested.status_code == 200, nested.text
    assert "pin.prt" in nested.text
    assert "Files" in nested.text
    reopened = client.get(f"/?project={project['uuid']}")
    assert reopened.status_code == 200, reopened.text
    assert "pin.prt" in reopened.text
    assert 'id="panel-files" data-folder="Incoming/lib"' in reopened.text
    root = client.get(f"/?project={project['uuid']}&folder=")
    assert root.status_code == 200, root.text
    assert 'id="panel-files" data-folder=""' in root.text
    assert 'data-folder="Incoming"' in root.text
    assert "pin.prt" not in root.text
    assert (location / "Incoming" / "shaft.prt.4").is_file()
    assert (location / "Incoming" / "lib" / "pin.prt").is_file()
    workspace = data_dir / "workspaces" / project["uuid"]
    assert (workspace / "Incoming" / "shaft.prt.4").is_file()
    assert (workspace / "Incoming" / "lib" / "pin.prt").is_file()


@requires_git
def test_choose_folder_cancel_keeps_empty_selection(client, repo_parent, monkeypatch):
    project, _location = _create_project(client, repo_parent)
    monkeypatch.setattr(
        "creopdm.api.projects.pick_folder",
        lambda initial_dir, title="Add a folder to the project": None,
    )
    response = client.post(f"/api/projects/{project['uuid']}/workspace/choose-folder")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cancelled"] is True
    assert body["selected"] == []


@requires_git
def test_choose_folder_does_not_scan_files(client, repo_parent, monkeypatch, tmp_path):
    project, _location = _create_project(client, repo_parent)
    picked = tmp_path / "BigUpload"
    picked.mkdir()
    (picked / "shaft.prt.1").write_bytes(b"model")
    scanned = []
    monkeypatch.setattr(
        "creopdm.api.projects.pick_folder",
        lambda initial_dir, title="Add a folder to the project": picked,
    )
    monkeypatch.setattr(
        "creopdm.api.projects.CreoFileManager.list_latest_in_folder",
        lambda *args, **kwargs: scanned.append(True) or [],
    )
    response = client.post(f"/api/projects/{project['uuid']}/workspace/choose-folder")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["folder"] == str(picked)
    assert body["selected"] == []
    assert scanned == []


@requires_git
def test_from_disk_folder_rejects_empty_directory(client, repo_parent, tmp_path):
    project, _location = _create_project(client, repo_parent)
    empty = tmp_path / "EmptyBox"
    empty.mkdir()
    imported = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"folder": str(empty), "comment": "Nothing here"},
    )
    assert imported.status_code == 400, imported.text


@requires_git
def test_choose_folder_from_outside_location(client, repo_parent, tmp_path, monkeypatch, data_dir):
    project, _location = _create_project(client, repo_parent)
    outside = tmp_path / "Elsewhere"
    nested = outside / "lib"
    nested.mkdir(parents=True)
    (outside / "pin.prt").write_bytes(b"from-elsewhere")
    (nested / "bushing.prt").write_bytes(b"nested")
    monkeypatch.setattr(
        "creopdm.api.projects.pick_folder",
        lambda initial_dir, title="Add a folder to the project": outside,
    )
    response = client.post(f"/api/projects/{project['uuid']}/workspace/choose-folder")
    assert response.status_code == 200, response.text
    body = response.json()
    assert not body["warning"]
    assert body["folder"] == str(outside)
    imported = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"folder": str(outside), "comment": "Outside folder", "base_folder": str(outside)},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["failed"] == []
    listing = {item["filename"]: item["relative_path"] for item in client.get(f"/api/projects/{project['uuid']}/objects").json()}
    assert listing == {"pin.prt": "Elsewhere/pin.prt", "bushing.prt": "Elsewhere/lib/bushing.prt"}
    workspace = data_dir / "workspaces" / project["uuid"]
    assert (workspace / "Elsewhere" / "pin.prt").read_bytes() == b"from-elsewhere"
    assert (workspace / "Elsewhere" / "lib" / "bushing.prt").read_bytes() == b"nested"


@requires_git
def test_from_disk_adds_file_outside_project_location(client, repo_parent, tmp_path, data_dir):
    project, _location = _create_project(client, repo_parent)
    outsider = tmp_path / "foreign.prt"
    outsider.write_bytes(b"from-elsewhere")
    imported = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(outsider)], "comment": "Library part"},
    )
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert not body["failed"]
    assert body["ok"][0]["filename"] == "foreign.prt"
    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()
    assert listing[0]["relative_path"] == "foreign.prt"
    assert listing[0]["filename"] == "foreign.prt"
    assert (data_dir / "workspaces" / project["uuid"] / "foreign.prt").read_bytes() == b"from-elsewhere"
    assert outsider.is_file()


@requires_git
def test_choose_folder_inside_project_keeps_repo_relative_path(client, repo_parent, monkeypatch):
    project, location = _create_project(client, repo_parent)
    lib = location / "lib"
    lib.mkdir()
    (lib / "pin.prt").write_bytes(b"pin")
    monkeypatch.setattr(
        "creopdm.api.projects.pick_folder",
        lambda initial_dir, title="Add a folder to the project": lib,
    )
    chosen = client.post(f"/api/projects/{project['uuid']}/workspace/choose-folder")
    assert chosen.status_code == 200, chosen.text
    imported = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={
            "folder": str(lib),
            "comment": "Existing lib",
            "base_folder": str(lib),
        },
    )
    assert imported.status_code == 200, imported.text
    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()
    assert listing[0]["relative_path"] == "lib/pin.prt"
    page = client.get(f"/?project={project['uuid']}")
    assert 'data-folder="lib"' in page.text
    assert (location / "lib" / "pin.prt").read_bytes() == b"pin"


@requires_git
def test_from_disk_adds_only_latest_numbered_revision(client, repo_parent):
    project, location = _create_project(client, repo_parent)
    older = location / "parallels.prt"
    older.write_bytes(b"old-generic")
    first = location / "parallels.prt.1"
    first.write_bytes(b"rev-1")
    latest = location / "parallels.prt.3"
    latest.write_bytes(b"rev-3")
    notes = location / "notes.pdf"
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
def test_import_from_vault_after_git_deleted_keeps_file(client, repo_parent, data_dir):
    project, location = _create_project(client, repo_parent)
    pin = location / "keep.prt.1"
    pin.write_bytes(b"do-not-delete")
    vault = data_dir / "workspaces" / project["uuid"]
    assert remove_tree(vault / ".git"), "Could not delete .git to simulate a removed repository"
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
    assert (vault / ".git").exists()
    assert not (location / ".git").exists()


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
    assert second.status_code == 201, second.text
    body = second.json()
    assert body["uuid"] == first.json()["uuid"]
    assert body["filename"] == "base.prt.4"
    assert body["relative_path"] == "base.prt.4"
    assert body["display_revision"] == "A.2"
    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()
    assert len(listing) == 1
    assert listing[0]["filename"] == "base.prt.4"
    older = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("base.prt.2", b"older-save", "application/octet-stream")},
        data={"comment": "Older save"},
    )
    assert older.status_code == 409
    assert older.json()["error"]["code"] == "DUPLICATE_OBJECT"


@requires_git
def test_from_disk_later_numbered_save_updates_workspace(client, repo_parent, tmp_path, data_dir):
    project, _location = _create_project(client, repo_parent)
    first = tmp_path / "bridgeport_mill.prt.4"
    first.write_bytes(b"save-4")
    added = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(first)], "comment": "Initial mill"},
    )
    assert added.status_code == 200, added.text
    assert added.json()["ok"][0]["filename"] == "bridgeport_mill.prt.4"
    later = tmp_path / "elsewhere" / "bridgeport_mill.prt.6"
    later.parent.mkdir()
    later.write_bytes(b"save-6")
    updated = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(later)], "comment": "Later mill save"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["failed"] == []
    assert updated.json()["ok"][0]["filename"] == "bridgeport_mill.prt.6"
    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()
    assert len(listing) == 1
    assert listing[0]["filename"] == "bridgeport_mill.prt.6"
    assert listing[0]["display_revision"] == "A.2"
    workspace = data_dir / "workspaces" / project["uuid"]
    assert (workspace / "bridgeport_mill.prt.6").is_file()
    assert (workspace / "bridgeport_mill.prt.6").read_bytes() == b"save-6"


@requires_git
def test_from_disk_later_save_while_checked_out_stays_working_copy(client, repo_parent, tmp_path, data_dir):
    project, _location = _create_project(client, repo_parent)
    first = tmp_path / "bridgeport_mill.prt.4"
    first.write_bytes(b"save-4")
    added = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(first)], "comment": "Initial mill"},
    )
    assert added.status_code == 200, added.text
    obj = client.get(f"/api/projects/{project['uuid']}/objects").json()[0]
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    later = tmp_path / "bridgeport_mill.prt.6"
    later.write_bytes(b"save-6")
    updated = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(later)], "comment": "Later mill save"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["failed"] == []
    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()[0]
    assert listing["filename"] == "bridgeport_mill.prt.4"
    assert listing["owned_by_me"] is True
    workspace = data_dir / "workspaces" / project["uuid"]
    assert (workspace / "bridgeport_mill.prt.6").read_bytes() == b"save-6"
    checked = client.post(
        f"/api/objects/{obj['uuid']}/checkin",
        json={"comment": "Record later mill save"},
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["filename"] == "bridgeport_mill.prt.6"
    assert checked.json()["owned_by_me"] is False


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
    assert body["cad_models"] == 1
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
    assert (data_dir / "workspaces" / project["uuid"] / ".git").exists()
    restored = client.post("/api/objects/batch/workspace", json={"object_ids": [obj["uuid"]]})
    assert restored.status_code == 200, restored.text
    assert workspace.is_file()
    assert workspace.read_bytes() == b"vault-bytes"


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
    assert not (location / "shaft.prt").exists()
    assert not (location / "notes.txt").exists()
    assert (workspace / ".git").exists()


@requires_git
def test_remove_from_project_keeps_original_file(client, repo_parent, data_dir):
    project, location = _create_project(client, repo_parent)
    spec = location / "spec.pdf"
    spec.write_bytes(b"%PDF-1.4 fake")
    created = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(spec)], "comment": "Spec"},
    )
    assert created.status_code == 200, created.text
    obj = created.json()["ok"][0]
    assert client.post(f"/api/objects/{obj['uuid']}/checkout").status_code == 200
    workspace = data_dir / "workspaces" / project["uuid"] / "spec.pdf"
    assert workspace.is_file()
    assert spec.is_file()

    removed = client.delete(f"/api/objects/{obj['uuid']}")
    assert removed.status_code == 204, removed.text
    assert not workspace.exists()
    assert spec.is_file()
    assert spec.read_bytes() == b"%PDF-1.4 fake"
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
    assert not (location / "pin.prt").exists()
    still = client.get(f"/api/objects/{obj['uuid']}")
    assert still.status_code == 200
    assert still.json()["checkout_user"] == "Alice"


@requires_git
def test_batch_remove_from_project(client, repo_parent, data_dir):
    project, location = _create_project(client, repo_parent)
    (location / "arm.prt").write_bytes(b"part")
    (location / "notes.txt").write_bytes(b"hello")
    added = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(location / "arm.prt"), str(location / "notes.txt")], "comment": "Add"},
    )
    assert added.status_code == 200, added.text
    ids = [item["uuid"] for item in added.json()["ok"]]
    result = client.post(
        "/api/objects/batch/remove",
        json={"object_ids": ids},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert len(body["ok"]) == 2
    assert body["failed"] == []
    listing = client.get(f"/api/projects/{project['uuid']}/objects").json()
    assert listing == []
    assert (location / "arm.prt").is_file()
    assert (location / "notes.txt").is_file()
    from creopdm.services.git_service import GitService

    vault = data_dir / "workspaces" / project["uuid"]
    messages = [entry.message for entry in GitService().get_history(vault)]
    unregister = [item for item in messages if item.startswith("Unregister")]
    assert unregister == ["Unregister 2 files"]


@requires_git
def test_remove_from_project_prunes_empty_workspace_folder(client, repo_parent, data_dir):
    project, location = _create_project(client, repo_parent)
    picked = location / "html_tutorials"
    nested = picked / "css"
    nested.mkdir(parents=True)
    (picked / "index.html").write_bytes(b"home")
    (nested / "site.css").write_bytes(b"body{}")
    added = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={
            "paths": [str(picked / "index.html"), str(nested / "site.css")],
            "comment": "Tutorials",
            "base_folder": str(picked),
        },
    )
    assert added.status_code == 200, added.text
    ids = [item["uuid"] for item in added.json()["ok"]]
    workspace = data_dir / "workspaces" / project["uuid"]
    assert (workspace / "html_tutorials" / "index.html").is_file()
    removed = client.post("/api/objects/batch/remove", json={"object_ids": ids})
    assert removed.status_code == 200, removed.text
    assert removed.json()["failed"] == []
    assert not (workspace / "html_tutorials").exists()
    assert (workspace / ".git").exists()
    assert (picked / "index.html").is_file()
    assert (nested / "site.css").is_file()


@requires_git
def test_batch_add_from_disk_one_commit(client, repo_parent, data_dir):
    project, location = _create_project(client, repo_parent)
    (location / "arm.prt").write_bytes(b"part")
    (location / "notes.txt").write_bytes(b"hello")
    added = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(location / "arm.prt"), str(location / "notes.txt")]},
    )
    assert added.status_code == 200, added.text
    body = added.json()
    assert {item["filename"] for item in body["ok"]} == {"arm.prt", "notes.txt"}
    assert body["failed"] == []
    listing = {item["filename"]: item for item in client.get(f"/api/projects/{project['uuid']}/objects").json()}
    assert set(listing) == {"arm.prt", "notes.txt"}
    assert (location / "arm.prt").is_file()
    assert (location / "notes.txt").is_file()
    from creopdm.services.git_service import GitService

    vault = data_dir / "workspaces" / project["uuid"]
    messages = [entry.message for entry in GitService().get_history(vault)]
    assert [item for item in messages if item.startswith("Add")] == ["Add 2 files"]


@requires_git
def test_batch_add_later_save_same_commit(client, repo_parent, tmp_path, data_dir):
    project, _location = _create_project(client, repo_parent)
    first = tmp_path / "bridgeport_mill.prt.4"
    first.write_bytes(b"save-4")
    added = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(first)], "comment": "Initial mill"},
    )
    assert added.status_code == 200, added.text
    later = tmp_path / "bridgeport_mill.prt.6"
    later.write_bytes(b"save-6")
    notes = tmp_path / "notes.txt"
    notes.write_bytes(b"hello")
    batch = client.post(
        f"/api/projects/{project['uuid']}/objects/from-disk",
        json={"paths": [str(later), str(notes)], "comment": "Batch later"},
    )
    assert batch.status_code == 200, batch.text
    assert batch.json()["failed"] == []
    listing = {item["filename"]: item for item in client.get(f"/api/projects/{project['uuid']}/objects").json()}
    assert listing["bridgeport_mill.prt.6"]["display_revision"] == "A.2"
    assert listing["bridgeport_mill.prt.6"]["uuid"] == added.json()["ok"][0]["uuid"]
    assert "notes.txt" in listing
    assert later.is_file()
    assert notes.is_file()
    from creopdm.services.git_service import GitService

    vault = data_dir / "workspaces" / project["uuid"]
    messages = [entry.message for entry in GitService().get_history(vault)]
    assert messages.count("Batch later") == 1
    assert messages[0] == "Batch later"


_CREO_UGC_HEADER = (
    "#UGC:2 ASSEMBLY 2784 2280 800 1 1 15 4400 2026163 000002d0 \\\n"
    "#- VERS 0 0                                                          \\\n"
    "#- CMNM 00ebridgeport.asm                                            \\\n"
    "#-END_OF_UGC_HEADER\n"
    "#Creo  TM  13  (c) 2026 by PTC Inc.  All Rights Reserved. 13.4.1.0\n"
    "#UGC_TOC 2 32 81 17#############################################################"
).encode("ascii") + b"\x00binary"


@requires_git
def test_creo_release_stored_for_prt_asm_drw_only(client, repo_parent):
    project, _location = _create_project(client, repo_parent)
    asm = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("bridgeport.asm.1", _CREO_UGC_HEADER, "application/octet-stream")},
        data={"comment": "Add mill assembly"},
    )
    assert asm.status_code == 201, asm.text
    body = asm.json()
    assert body["creo_release"] == "13.4.1.0"
    assert body["current_version"]["creo_release"] == "13.4.1.0"

    frm = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("a0.frm", _CREO_UGC_HEADER, "application/octet-stream")},
        data={"comment": "Drawing format"},
    )
    assert frm.status_code == 201, frm.text
    assert frm.json()["creo_release"] is None

    pdf = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("spec.pdf", _CREO_UGC_HEADER, "application/pdf")},
        data={"comment": "Not a model"},
    )
    assert pdf.status_code == 201, pdf.text
    assert pdf.json()["creo_release"] is None

    files_page = client.get(f"/?project={project['uuid']}")
    assert files_page.status_code == 200
    assert "13.4.1.0" in files_page.text
    detail = client.get(f"/projects/{project['uuid']}/objects/{body['uuid']}")
    assert detail.status_code == 200
    assert "13.4.1.0" in detail.text
    history = client.get(f"/api/objects/{body['uuid']}/history").json()
    assert history[0]["creo_release"] == "13.4.1.0"
