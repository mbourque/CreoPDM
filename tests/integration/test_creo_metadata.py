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
                    "filename": "frame.asm",
                    "quantity": 1,
                    "dependency_type": "ASSEMBLY_ROOT",
                    "children": [
                        {
                            "filename": "shaft.prt",
                            "quantity": 2,
                            "dependency_type": "ASSEMBLY_MEMBER",
                            "children": [],
                        },
                        {
                            "filename": "top.asm",
                            "quantity": 1,
                            "dependency_type": "ASSEMBLY_MEMBER",
                            "children": [
                                {
                                    "filename": "pin.prt",
                                    "quantity": 4,
                                    "dependency_type": "ASSEMBLY_MEMBER",
                                    "children": [],
                                }
                            ],
                        },
                    ],
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
    assert "frame.asm" in text
    assert "top.asm" in text
    assert "pin.prt" in text
    assert "bom-tree-root" in text
    assert f'data-uuid="{shaft["uuid"]}"' in text
    assert 'class="object-open bom-name"' in text
    assert 'class="object-open mono bom-name"' not in text

    shaft_meta = client.post(
        f"/api/objects/{shaft['uuid']}/creo-metadata",
        json={
            "materials": {
                "current": "ALUMINUM_WROUGHT",
                "names": ["PTC_SYSTEM_MTRL_PROPS", "ALUMINUM_WROUGHT"],
            },
            "units": {
                "system_name": "mmNs",
                "length": "mm",
                "mass": "kg",
                "time": "sec",
                "temperature": "C",
            },
            "mass": {
                "mass": 1.25,
                "volume": 460.0,
                "surface_area": 320.0,
                "density": 0.0027,
                "gravity_center": [0.1, 0.2, 0.3],
                "principal_moments": [1.0, 2.0, 3.0],
            },
            "family_table": {
                "columns": ["D1", "LENGTH"],
                "rows": [
                    {"instance": "SHAFT_GENERIC", "cells": ["10", "100"]},
                    {"instance": "SHAFT_LONG", "cells": ["10", "200"]},
                ],
            },
            "features": [
                {"id": 1, "name": "FIRST_FEATURE", "type": "FIRST_FEAT", "subtype": ""},
                {"id": 39, "name": "Extrude 1", "type": "PROTRUSION", "subtype": "Extrude"},
            ],
        },
    )
    assert shaft_meta.status_code == 200, shaft_meta.text
    shaft_detail = client.get(f"/projects/{project['uuid']}/objects/{shaft['uuid']}")
    assert shaft_detail.status_code == 200
    assert "frame.asm.1" in shaft_detail.text
    assert "ALUMINUM_WROUGHT" in shaft_detail.text
    assert "(Assigned)" in shaft_detail.text
    assert 'class="is-assigned"' in shaft_detail.text
    assert 'data-tab="mass"' in shaft_detail.text
    assert 'data-tab="family"' in shaft_detail.text
    assert 'data-tab="features"' in shaft_detail.text
    assert 'data-tab="structure"' not in shaft_detail.text
    assert "mmNs" in shaft_detail.text
    assert "SHAFT_LONG" in shaft_detail.text
    assert "1.25" in shaft_detail.text
    assert "Extrude 1" in shaft_detail.text
    assert "Visible Creo features" in shaft_detail.text
    assert 'id="panel-features"' in shaft_detail.text


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


@requires_git
def test_where_used_from_nested_bom_and_family_table_name(client, repo_parent, tmp_path):
    project = _create_project(client, repo_parent)
    pin = _add_part(client, project["uuid"], tmp_path, "pin.prt.1")
    rivet = _add_part(client, project["uuid"], tmp_path, "SPLIT-RIVET.prt.1")
    frame = _add_part(client, project["uuid"], tmp_path, "frame.asm.1")

    posted = client.post(
        f"/api/objects/{frame['uuid']}/creo-metadata",
        json={
            "identity": {"common_name": "Frame"},
            # Non-empty ListDependencies-style list must not block nested BOM indexing.
            "dependencies": [
                {"filename": "pin.prt", "quantity": 1, "dependency_type": "ASSEMBLY_MEMBER"}
            ],
            "bom": [
                {
                    "filename": "frame.asm",
                    "quantity": 1,
                    "dependency_type": "ASSEMBLY_ROOT",
                    "children": [
                        {
                            "filename": "pin.prt",
                            "quantity": 4,
                            "dependency_type": "ASSEMBLY_MEMBER",
                            "children": [],
                        },
                        {
                            "filename": "INSTALLED<SPLIT-RIVET>.prt",
                            "quantity": 2,
                            "dependency_type": "ASSEMBLY_MEMBER",
                            "children": [],
                        },
                    ],
                }
            ],
        },
    )
    assert posted.status_code == 200, posted.text
    deps = posted.json()["dependencies"]
    child_names = {item["filename"] for item in deps}
    assert "pin.prt.1" in child_names
    assert "SPLIT-RIVET.prt.1" in child_names

    pin_where = client.get(f"/api/objects/{pin['uuid']}/where-used")
    assert pin_where.status_code == 200, pin_where.text
    pin_items = pin_where.json()["items"]
    assert len(pin_items) == 1
    assert pin_items[0]["object_id"] == frame["uuid"]
    assert pin_items[0]["quantity"] == 4.0  # BOM qty (deps not double-counted)

    rivet_where = client.get(f"/api/objects/{rivet['uuid']}/where-used")
    assert rivet_where.status_code == 200, rivet_where.text
    rivet_items = rivet_where.json()["items"]
    assert len(rivet_items) == 1
    assert rivet_items[0]["object_id"] == frame["uuid"]
    assert rivet_items[0]["quantity"] == 2.0

    pin_detail = client.get(f"/projects/{project['uuid']}/objects/{pin['uuid']}")
    assert pin_detail.status_code == 200
    assert "frame.asm.1" in pin_detail.text


@requires_git
def test_where_used_when_child_added_after_assembly_bom(client, repo_parent, tmp_path):
    """Assembly metadata captured before the child exists still feeds Where Used later."""
    project = _create_project(client, repo_parent)
    frame = _add_part(client, project["uuid"], tmp_path, "frame.asm.1")
    posted = client.post(
        f"/api/objects/{frame['uuid']}/creo-metadata",
        json={
            "identity": {"common_name": "Frame"},
            "bom": [
                {
                    "filename": "frame.asm",
                    "quantity": 1,
                    "dependency_type": "ASSEMBLY_ROOT",
                    "children": [
                        {
                            "filename": "late-pin.prt",
                            "quantity": 3,
                            "dependency_type": "ASSEMBLY_MEMBER",
                            "children": [],
                        }
                    ],
                }
            ],
        },
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["dependencies"] == []

    pin = _add_part(client, project["uuid"], tmp_path, "late-pin.prt.1")
    where = client.get(f"/api/objects/{pin['uuid']}/where-used")
    assert where.status_code == 200, where.text
    items = where.json()["items"]
    assert len(items) == 1
    assert items[0]["object_id"] == frame["uuid"]
    assert items[0]["quantity"] == 3.0


@requires_git
def test_where_used_from_vault_bytes_without_creo_metadata(
    client, repo_parent, data_dir, tmp_path
):
    """No Creo.JS capture: scan vault asm bytes for the part name."""
    from creopdm.utils.files import set_file_writable

    project = _create_project(client, repo_parent)
    pin = _add_part(client, project["uuid"], tmp_path, "clasp-clasp_mir.prt.1")
    frame = _add_part(client, project["uuid"], tmp_path, "draw_latch.asm.1")

    vault = data_dir / "vaults" / project["uuid"]
    asm_files = list(vault.rglob("draw_latch.asm*"))
    assert asm_files, f"expected vault asm under {vault}"
    set_file_writable(asm_files[0])
    asm_files[0].write_bytes(b"fake creo asm embeds CLASP-CLASP_MIR.PRT as member")

    where = client.get(f"/api/objects/{pin['uuid']}/where-used")
    assert where.status_code == 200, where.text
    items = where.json()["items"]
    assert len(items) == 1
    assert items[0]["object_id"] == frame["uuid"]
    assert items[0]["filename"].lower().startswith("draw_latch.asm")


@requires_git
def test_rebuild_where_used_writes_dependency_edges(client, repo_parent, data_dir, tmp_path):
    """Rebuild indexes vault refs into Dependency so Where Used is SQL-only."""
    import time

    from creopdm.utils.files import set_file_writable

    project = _create_project(client, repo_parent)
    pin = _add_part(client, project["uuid"], tmp_path, "pin.prt.1")
    frame = _add_part(client, project["uuid"], tmp_path, "frame.asm.1")

    vault = data_dir / "vaults" / project["uuid"]
    asm_files = list(vault.rglob("frame.asm*"))
    assert asm_files
    set_file_writable(asm_files[0])
    asm_files[0].write_bytes(b"assembly body mentions PIN.PRT as component")

    started = client.post(f"/api/projects/{project['uuid']}/rebuild-where-used")
    assert started.status_code == 200, started.text
    assert started.json()["state"] in {"queued", "running", "done"}

    body = None
    for _ in range(100):
        status = client.get(f"/api/projects/{project['uuid']}/rebuild-where-used")
        assert status.status_code == 200, status.text
        body = status.json()
        if body["done"]:
            break
        time.sleep(0.05)
    assert body is not None
    assert body["state"] == "done", body
    assert body["edges_added"] >= 1
    assert body["parents_total"] >= 1

    where = client.get(f"/api/objects/{pin['uuid']}/where-used?vault_scan=false")
    assert where.status_code == 200, where.text
    items = where.json()["items"]
    assert len(items) == 1
    assert items[0]["object_id"] == frame["uuid"]

    again = client.post(f"/api/projects/{project['uuid']}/rebuild-where-used")
    assert again.status_code == 200, again.text
    body2 = None
    for _ in range(100):
        status = client.get(f"/api/projects/{project['uuid']}/rebuild-where-used")
        assert status.status_code == 200, status.text
        body2 = status.json()
        if body2["done"]:
            break
        time.sleep(0.05)
    assert body2 is not None
    assert body2["state"] == "done"
    assert body2["edges_added"] == 0
    assert body2["edges_existing"] >= 1
