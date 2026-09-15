from pathlib import Path

from creopdm.utils.classify import extra_cad_set
from tests.conftest import requires_git


def test_get_and_update_settings(client, tmp_path):
    response = client.get("/api/settings")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["creo_open_mode"] in {"executable", "association"}
    assert payload["workspace_root"]
    assert payload["default_workspace_root"]
    defaults = payload["default_cad_extensions"]
    assert ".ncl" in defaults
    assert ".m_p" in defaults
    assert ".frm" in defaults
    assert ".bin" in defaults
    assert ".mrd" in defaults
    assert ".xpr" in defaults
    assert extra_cad_set(payload["cad_extensions"]) == extra_cad_set(defaults)

    fake_creo = tmp_path / "parametric.exe"
    fake_creo.write_bytes(b"fake")
    workspace = tmp_path / "MyWorkspace"
    updated = client.put(
        "/api/settings",
        json={
            "creo_open_mode": "association",
            "creo_executable": str(fake_creo),
            "workspace_root": str(workspace),
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["creo_open_mode"] == "association"
    assert Path(body["creo_executable"]) == fake_creo
    assert Path(body["workspace_root"]) == workspace.resolve()
    assert workspace.is_dir()

    page = client.get("/settings")
    assert page.status_code == 200
    assert "Open Creo models with" in page.text
    assert "Workspace" in page.text
    assert "CAD file types" in page.text


@requires_git
def test_cad_extensions_setting_changes_classification(client, repo_parent):
    saved = client.put(
        "/api/settings",
        json={"creo_open_mode": "executable", "cad_extensions": [".xyz", "ABC"]},
    )
    assert saved.status_code == 200, saved.text
    assert ".xyz" in saved.json()["cad_extensions"]
    assert ".abc" in saved.json()["cad_extensions"]

    location = repo_parent / "CadExt"
    project = client.post(
        "/api/projects",
        json={"name": "Cad Ext", "repository_path": str(location)},
    )
    assert project.status_code == 201, project.text
    created = client.post(
        f"/api/projects/{project.json()['uuid']}/objects",
        files={"file": ("blob.xyz", b"cad-ish", "application/octet-stream")},
        data={"comment": "Custom CAD"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["object_type"] == "CAD"
    assert created.json()["relative_path"] == "blob.xyz"


@requires_git
def test_custom_workspace_used_on_checkout(client, repo_parent, tmp_path):
    workspace = tmp_path / "VaultCopies"
    saved = client.put(
        "/api/settings",
        json={"creo_open_mode": "executable", "workspace_root": str(workspace)},
    )
    assert saved.status_code == 200, saved.text

    location = repo_parent / "WorkspaceProj"
    project = client.post(
        "/api/projects",
        json={"name": "Workspace Proj", "repository_path": str(location)},
    ).json()
    created = client.post(
        f"/api/projects/{project['uuid']}/objects",
        files={"file": ("shaft.prt", b"original-content", "application/octet-stream")},
        data={"comment": "Initial model"},
    )
    assert created.status_code == 201, created.text
    obj = created.json()
    checked = client.post(f"/api/objects/{obj['uuid']}/checkout")
    assert checked.status_code == 200, checked.text
    copied = workspace / project["uuid"] / "shaft.prt"
    assert copied.is_file()
    assert copied.read_bytes() == b"original-content"
