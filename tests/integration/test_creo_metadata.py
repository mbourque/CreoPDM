"""Creo.JS metadata API and where-used graph."""

from pathlib import Path

from tests.conftest import requires_git


def _create_project(client, repo_parent: Path):
    location = repo_parent / "MetaArm"
    location.mkdir(parents=True, exist_ok=True)
    response = client.post(
        "/api/projects",
        json={"name": "Meta Arm", "number": "PRJ-META"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_part(client, project_uuid: str, tmp_path: Path, name: str):
    path = tmp_path / name
    path.write_bytes(b"FAKE CREO PART")
    response = client.post(
        f"/api/projects/{project_uuid}/objects",
        files={"file": (name, path.read_bytes(), "application/octet-stream")},
        data={"comment": f"Add {name}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


@requires_git
def test_post_get_creo_metadata_and_where_used(client, repo_parent, tmp_path):
    project = _create_project(client, repo_parent)
    shaft = _add_part(client, project["uuid"], tmp_path, "shaft.prt.1")
    frame = _add_part(client, project["uuid"], tmp_path, "frame.asm.1")

    payload = {
        "identity": {
            "file_name": "frame.asm",
            "common_name": "Main Frame",
            "full_name": "FRAME",
            "instance_name": "FRAME",
            "generic_name": "",
            "origin": "C:/cache/frame.asm.1",
            "model_type": "MDL_ASSEMBLY",
            "is_modified": False,
        },
        "parameters": [
            {
                "name": "DESCRIPTION",
                "value": "Frame assembly",
                "data_type": "STRING",
                "units": None,
                "description": "Title",
                "is_designated": True,
            }
        ],
        "materials": {"current": None, "names": []},
        "dependencies": [
            {"filename": "shaft.prt.1", "quantity": 2, "dependency_type": "ASSEMBLY_MEMBER"}
        ],
        "bom": [
            {
                "filename": "shaft.prt",
                "quantity": 2,
                "dependency_type": "ASSEMBLY_MEMBER",
                "children": [],
            }
        ],
    }
    posted = client.post(f"/api/objects/{frame['uuid']}/creo-metadata", json=payload)
    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert body["captured"] is True
    assert body["identity"]["common_name"] == "Main Frame"
    assert body["parameters"][0]["name"] == "DESCRIPTION"
    assert body["parameters"][0]["is_designated"] is True
    assert len(body["dependencies"]) == 1
    assert body["dependencies"][0]["filename"] == "shaft.prt.1"
    assert body["dependencies"][0]["quantity"] == 2.0

    fetched = client.get(f"/api/objects/{frame['uuid']}/creo-metadata")
    assert fetched.status_code == 200
    assert fetched.json()["parameters"][0]["value"] == "Frame assembly"

    where = client.get(f"/api/objects/{shaft['uuid']}/where-used")
    assert where.status_code == 200, where.text
    items = where.json()["items"]
    assert len(items) == 1
    assert items[0]["object_id"] == frame["uuid"]
    assert items[0]["filename"] == "frame.asm.1"
    assert items[0]["quantity"] == 2.0

    detail = client.get(f"/projects/{project['uuid']}/objects/{frame['uuid']}")
    assert detail.status_code == 200
    text = detail.text
    assert 'data-tab="parameters"' in text
    assert 'data-tab="parameters" disabled' not in text
    assert "Main Frame" in text
    assert "DESCRIPTION" in text
    assert 'data-tab="structure"' in text
    assert 'data-tab="bom"' in text
    assert 'data-tab="where-used"' in text

    shaft_detail = client.get(f"/projects/{project['uuid']}/objects/{shaft['uuid']}")
    assert shaft_detail.status_code == 200
    assert "frame.asm.1" in shaft_detail.text


@requires_git
def test_creo_metadata_unresolved_child_skipped(client, repo_parent, tmp_path):
    project = _create_project(client, repo_parent)
    frame = _add_part(client, project["uuid"], tmp_path, "frame.asm.2")
    posted = client.post(
        f"/api/objects/{frame['uuid']}/creo-metadata",
        json={
            "identity": {"common_name": "Frame"},
            "dependencies": [
                {"filename": "missing.prt", "quantity": 1, "dependency_type": "ASSEMBLY_MEMBER"}
            ],
            "bom": [{"filename": "missing.prt", "quantity": 1, "children": []}],
        },
    )
    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert body["dependencies"] == []
    assert body["bom"][0]["filename"] == "missing.prt"
