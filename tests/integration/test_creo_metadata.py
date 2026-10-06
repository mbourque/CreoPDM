"""Creo.JS metadata API and where-used graph."""

from pathlib import Path

from tests.conftest import requires_git


def _create_product(client, repo_parent: Path):
    location = repo_parent / "MetaArm"
    location.mkdir(parents=True, exist_ok=True)
    response = client.post(
        "/api/products",
        json={"name": "Meta Arm", "number": "PRJ-META"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_part(client, product_uuid: str, tmp_path: Path, name: str):
    path = tmp_path / name
    path.write_bytes(b"FAKE CREO PART")
    response = client.post(
        f"/api/products/{product_uuid}/objects",
        files={"file": (name, path.read_bytes(), "application/octet-stream")},
        data={"comment": f"Add {name}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


@requires_git
def test_post_get_creo_metadata_and_where_used(client, repo_parent, tmp_path):
    product = _create_product(client, repo_parent)
    shaft = _add_part(client, product["uuid"], tmp_path, "shaft.prt.1")
    frame = _add_part(client, product["uuid"], tmp_path, "frame.asm.1")

    payload = {
        "identity": {
            "file_name": "frame.asm",
            "common_name": "Main Frame",
            "full_name": "FRAME",
            "instance_name": "FRAME",
            "generic_name": "",
            "origin": "C:/cache/frame.asm.1",
            "model_type": "MDL_ASSEMBLY",
            "model_role": "",
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
    assert body["identity"]["model_type"] == "ASSEMBLY"
    assert body["identity"].get("model_role") in ("", None)
    assert body["parameters"][0]["name"] == "DESCRIPTION"
    assert body["parameters"][0]["is_designated"] is True
    assert len(body["dependencies"]) == 1
    assert body["dependencies"][0]["filename"] == "shaft.prt"
    assert body["dependencies"][0]["quantity"] == 2.0

    fetched = client.get(f"/api/objects/{frame['uuid']}/creo-metadata")
    assert fetched.status_code == 200
    assert fetched.json()["parameters"][0]["value"] == "Frame assembly"

    shaft_meta = client.post(
        f"/api/objects/{shaft['uuid']}/creo-metadata",
        json={
            "identity": {
                "file_name": "shaft.prt",
                "model_type": "PART",
                "model_role": "SHEETMETAL",
            }
        },
    )
    assert shaft_meta.status_code == 200, shaft_meta.text
    assert shaft_meta.json()["identity"]["model_type"] == "PART"
    assert shaft_meta.json()["identity"]["model_role"] == "SHEETMETAL"
    listed = client.get(f"/api/products/{product['uuid']}/objects")
    assert listed.status_code == 200
    by_uuid = {item["uuid"]: item for item in listed.json()}
    assert by_uuid[shaft["uuid"]]["type_label"] == "SHEETMETAL"
    assert by_uuid[frame["uuid"]]["type_label"] == "ASSEMBLY"
    skel_meta = client.post(
        f"/api/objects/{shaft['uuid']}/creo-metadata",
        json={
            "identity": {
                "file_name": "shaft.prt",
                "model_type": "PART",
                "model_role": "SKELETON",
            }
        },
    )
    assert skel_meta.status_code == 200, skel_meta.text
    assert skel_meta.json()["identity"]["model_role"] == "SKELETON"
    listed_skel = client.get(f"/api/products/{product['uuid']}/objects")
    assert {item["uuid"]: item["type_label"] for item in listed_skel.json()}[shaft["uuid"]] == "SKELETON"
    found_skel = client.get(f"/api/products/{product['uuid']}/objects", params={"q": "SKELETON"})
    assert found_skel.status_code == 200
    assert shaft["uuid"] in {item["uuid"] for item in found_skel.json()}
    # Restore sheet-metal role for later Detail assertions.
    shaft_meta = client.post(
        f"/api/objects/{shaft['uuid']}/creo-metadata",
        json={
            "identity": {
                "file_name": "shaft.prt",
                "model_type": "PART",
                "model_role": "SHEETMETAL",
            }
        },
    )
    assert shaft_meta.status_code == 200, shaft_meta.text
    found_smt = client.get(f"/api/products/{product['uuid']}/objects", params={"q": "SHEETMETAL"})
    assert found_smt.status_code == 200
    assert shaft["uuid"] in {item["uuid"] for item in found_smt.json()}
    mfg_meta = client.post(
        f"/api/objects/{frame['uuid']}/creo-metadata",
        json={
            "identity": {
                "file_name": "frame.asm",
                "common_name": "Main Frame",
                "model_type": "MFG",
                "model_role": "MFG",
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
        },
    )
    assert mfg_meta.status_code == 200, mfg_meta.text
    listed_mfg = client.get(f"/api/products/{product['uuid']}/objects")
    assert {item["uuid"]: item["type_label"] for item in listed_mfg.json()}[frame["uuid"]] == "MFG"
    home_mfg = client.get(f"/?product={product['uuid']}")
    assert home_mfg.status_code == 200
    assert ">MFG<" in home_mfg.text or "title=\"MFG\"" in home_mfg.text
    shaft_detail = client.get(f"/products/{product['uuid']}/objects/{shaft['uuid']}")
    assert shaft_detail.status_code == 200
    assert "Model type" in shaft_detail.text
    assert "PART" in shaft_detail.text
    assert "Subtype" in shaft_detail.text
    assert "Model role" not in shaft_detail.text
    assert "SHEETMETAL" in shaft_detail.text

    where = client.get(f"/api/objects/{shaft['uuid']}/where-used")
    assert where.status_code == 200, where.text
    items = where.json()["items"]
    assert len(items) == 1
    assert items[0]["object_id"] == frame["uuid"]
    assert items[0]["filename"] == "frame.asm"
    assert items[0]["quantity"] == 2.0

    detail = client.get(f"/products/{product['uuid']}/objects/{frame['uuid']}")
    assert detail.status_code == 200
    text = detail.text
    assert 'data-tab="parameters"' in text
    assert 'data-tab="parameters" disabled' not in text
    assert "Main Frame" in text
    assert "Model type" in text
    assert "MFG" in text
    assert "Subtype" in text
    assert "Model role" not in text
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

    shaft_detail = client.get(f"/products/{product['uuid']}/objects/{shaft['uuid']}")
    assert shaft_detail.status_code == 200
    assert 'data-tab="where-used"' in shaft_detail.text
    assert 'id="panel-where-used"' in shaft_detail.text

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
    shaft_detail = client.get(f"/products/{product['uuid']}/objects/{shaft['uuid']}")
    assert shaft_detail.status_code == 200
    assert "frame.asm" in shaft_detail.text
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
    product = _create_product(client, repo_parent)
    frame = _add_part(client, product["uuid"], tmp_path, "frame.asm.2")
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
    product = _create_product(client, repo_parent)
    pin = _add_part(client, product["uuid"], tmp_path, "pin.prt.1")
    rivet = _add_part(client, product["uuid"], tmp_path, "SPLIT-RIVET.prt.1")
    frame = _add_part(client, product["uuid"], tmp_path, "frame.asm.1")

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
    assert "pin.prt" in child_names
    assert "SPLIT-RIVET.prt" in child_names

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

    pin_detail = client.get(f"/products/{product['uuid']}/objects/{pin['uuid']}")
    assert pin_detail.status_code == 200
    assert "frame.asm" in pin_detail.text


@requires_git
def test_where_used_when_child_added_after_assembly_bom(client, repo_parent, tmp_path):
    """Assembly metadata captured before the child exists still feeds Where Used later."""
    product = _create_product(client, repo_parent)
    frame = _add_part(client, product["uuid"], tmp_path, "frame.asm.1")
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

    pin = _add_part(client, product["uuid"], tmp_path, "late-pin.prt.1")
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

    product = _create_product(client, repo_parent)
    pin = _add_part(client, product["uuid"], tmp_path, "clasp-clasp_mir.prt.1")
    frame = _add_part(client, product["uuid"], tmp_path, "draw_latch.asm.1")

    vault = data_dir / "vaults" / product["uuid"]
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

    product = _create_product(client, repo_parent)
    pin = _add_part(client, product["uuid"], tmp_path, "pin.prt.1")
    frame = _add_part(client, product["uuid"], tmp_path, "frame.asm.1")

    vault = data_dir / "vaults" / product["uuid"]
    asm_files = list(vault.rglob("frame.asm*"))
    assert asm_files
    set_file_writable(asm_files[0])
    asm_files[0].write_bytes(b"assembly body mentions PIN.PRT as component")

    started = client.post(f"/api/products/{product['uuid']}/rebuild-where-used")
    assert started.status_code == 200, started.text
    assert started.json()["state"] in {"queued", "running", "done"}

    body = None
    for _ in range(100):
        status = client.get(f"/api/products/{product['uuid']}/rebuild-where-used")
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

    again = client.post(f"/api/products/{product['uuid']}/rebuild-where-used")
    assert again.status_code == 200, again.text
    body2 = None
    for _ in range(100):
        status = client.get(f"/api/products/{product['uuid']}/rebuild-where-used")
        assert status.status_code == 200, status.text
        body2 = status.json()
        if body2["done"]:
            break
        time.sleep(0.05)
    assert body2 is not None
    assert body2["state"] == "done"
    # Rebuild clears asm/drw edges at start, then re-adds from vault bytes.
    assert body2["edges_added"] >= 1
    where2 = client.get(f"/api/objects/{pin['uuid']}/where-used?vault_scan=false")
    assert where2.status_code == 200, where2.text
    assert where2.json()["items"][0]["object_id"] == frame["uuid"]


@requires_git
def test_metadata_menu_items_are_creo_session_only(client, repo_parent):
    """Collect needs Creo.JS; Rebuild Where Used is server-side (visible without Creo)."""
    import re

    product = _create_product(client, repo_parent)
    page = client.get(f"/?product={product['uuid']}")
    assert page.status_code == 200, page.text
    assert 'data-allows-mutation="1"' in page.text
    collect = re.search(r"<button[^>]*id=\"collect-metadata-btn\"[^>]*>", page.text)
    rebuild = re.search(r"<button[^>]*id=\"rebuild-where-used-btn\"[^>]*>", page.text)
    assert collect, page.text
    assert rebuild, page.text
    assert "creo-session-only" in collect.group(0)
    assert "hidden" in collect.group(0)
    assert "creo-session-only" not in rebuild.group(0)
    assert " hidden" not in rebuild.group(0) and not rebuild.group(0).endswith(" hidden>")
    assert 'id="set-creo-dir-btn"' in page.text


@requires_git
def test_metadata_save_erases_this_objects_old_table_rows(client, repo_parent, tmp_path):
    """Save deletes this object's old Parameter/Dependency rows before rewrite."""
    product = _create_product(client, repo_parent)
    shaft = _add_part(client, product["uuid"], tmp_path, "shaft.prt.1")
    frame = _add_part(client, product["uuid"], tmp_path, "frame.asm.1")

    first = client.post(
        f"/api/objects/{frame['uuid']}/creo-metadata",
        json={
            "identity": {"file_name": "frame.asm", "model_type": "ASSEMBLY"},
            "parameters": [
                {
                    "name": "OLD_PARAM",
                    "value": "gone",
                    "data_type": "STRING",
                    "is_designated": False,
                }
            ],
            "dependencies": [
                {"filename": "shaft.prt", "quantity": 1, "dependency_type": "ASSEMBLY_MEMBER"}
            ],
        },
    )
    assert first.status_code == 200, first.text
    assert {p["name"] for p in first.json()["parameters"]} == {"OLD_PARAM"}
    assert len(first.json()["dependencies"]) == 1

    second = client.post(
        f"/api/objects/{frame['uuid']}/creo-metadata",
        json={
            "identity": {"file_name": "frame.asm", "model_type": "ASSEMBLY"},
            "parameters": [
                {
                    "name": "NEW_PARAM",
                    "value": "kept",
                    "data_type": "STRING",
                    "is_designated": True,
                }
            ],
            "dependencies": [],
            "bom": [
                {
                    "filename": "frame.asm",
                    "quantity": 1,
                    "dependency_type": "ASSEMBLY_ROOT",
                    "children": [],
                }
            ],
        },
    )
    assert second.status_code == 200, second.text
    names = [p["name"] for p in second.json()["parameters"]]
    assert names == ["NEW_PARAM"]
    assert "OLD_PARAM" not in names
    # BOM with no members + empty deps → dependency rows erased for this parent.
    assert second.json()["dependencies"] == []

    listed = client.get(f"/api/products/{product['uuid']}/objects")
    assert listed.status_code == 200, listed.text
    by_uuid = {item["uuid"]: item for item in listed.json()}
    assert by_uuid[frame["uuid"]]["creo_metadata_captured"] is True
    assert by_uuid[shaft["uuid"]]["creo_metadata_captured"] is False


@requires_git
def test_assembly_metadata_does_not_write_child_skeleton_role(client, repo_parent, tmp_path):
    """Assembly SKELETON deps are this object's edges only — child identity unchanged."""
    product = _create_product(client, repo_parent)
    layout = _add_part(client, product["uuid"], tmp_path, "jd_layout.prt.1")
    top = _add_part(client, product["uuid"], tmp_path, "jd_top.asm.1")

    posted = client.post(
        f"/api/objects/{top['uuid']}/creo-metadata",
        json={
            "identity": {
                "file_name": "jd_top.asm",
                "model_type": "ASSEMBLY",
                "model_role": "",
            },
            "dependencies": [
                {
                    "filename": "jd_layout.prt",
                    "quantity": 1,
                    "dependency_type": "SKELETON",
                }
            ],
        },
    )
    assert posted.status_code == 200, posted.text
    deps = posted.json()["dependencies"]
    assert any(
        str(row.get("filename") or "").lower().startswith("jd_layout")
        and str(row.get("dependency_type") or "").upper() == "SKELETON"
        for row in deps
    )

    listed = client.get(f"/api/products/{product['uuid']}/objects")
    assert listed.status_code == 200, listed.text
    by_uuid = {item["uuid"]: item for item in listed.json()}
    assert by_uuid[layout["uuid"]]["type_label"] != "SKELETON"
    assert by_uuid[layout["uuid"]]["creo_metadata_captured"] is False

    layout_meta = client.get(f"/api/objects/{layout['uuid']}/creo-metadata")
    assert layout_meta.status_code == 200, layout_meta.text
    assert layout_meta.json()["captured"] is False

    # Collect the part later (assemblies-first Collect): parent SKELETON edge flags the part.
    part_post = client.post(
        f"/api/objects/{layout['uuid']}/creo-metadata",
        json={
            "identity": {
                "file_name": "jd_layout.prt",
                "model_type": "PART",
                "model_role": "SOLID",
            },
            "materials": {"current": None, "names": []},
        },
    )
    assert part_post.status_code == 200, part_post.text
    assert part_post.json()["identity"]["model_role"] == "SKELETON"
    listed_after = client.get(f"/api/products/{product['uuid']}/objects")
    assert listed_after.status_code == 200
    assert {item["uuid"]: item["type_label"] for item in listed_after.json()}[
        layout["uuid"]
    ] == "SKELETON"


@requires_git
def test_collect_clear_wipes_product_creo_metadata(client, repo_parent, tmp_path):
    """Collect-all start endpoint erases stored identity/params/deps for the product."""
    product = _create_product(client, repo_parent)
    shaft = _add_part(client, product["uuid"], tmp_path, "shaft.prt.1")
    frame = _add_part(client, product["uuid"], tmp_path, "frame.asm.1")
    posted = client.post(
        f"/api/objects/{frame['uuid']}/creo-metadata",
        json={
            "identity": {"file_name": "frame.asm", "model_type": "ASSEMBLY"},
            "parameters": [
                {"name": "DESCRIPTION", "value": "x", "data_type": "STRING", "is_designated": False}
            ],
            "dependencies": [
                {"filename": "shaft.prt", "quantity": 1, "dependency_type": "ASSEMBLY_MEMBER"}
            ],
        },
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["captured"] is True

    cleared = client.post(f"/api/products/{product['uuid']}/creo-metadata/clear")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["ok"] is True
    assert cleared.json()["versions_cleared"] >= 1

    fetched = client.get(f"/api/objects/{frame['uuid']}/creo-metadata")
    assert fetched.status_code == 200
    assert fetched.json()["captured"] is False
    assert not fetched.json()["parameters"]
    assert not fetched.json()["dependencies"]
    listed = client.get(f"/api/products/{product['uuid']}/objects")
    by_uuid = {item["uuid"]: item for item in listed.json()}
    assert by_uuid[frame["uuid"]]["creo_metadata_captured"] is False
    assert by_uuid[shaft["uuid"]]["creo_metadata_captured"] is False


@requires_git
def test_assembly_is_not_promoted_to_skeleton_role(client, repo_parent, tmp_path):
    """Assemblies never keep model_role SKELETON — parts only."""
    product = _create_product(client, repo_parent)
    child_asm = _add_part(client, product["uuid"], tmp_path, "sub.asm.1")
    top = _add_part(client, product["uuid"], tmp_path, "top.asm.1")

    posted = client.post(
        f"/api/objects/{top['uuid']}/creo-metadata",
        json={
            "identity": {
                "file_name": "top.asm",
                "model_type": "ASSEMBLY",
                "model_role": "SKELETON",
            },
            "dependencies": [
                {"filename": "sub.asm", "quantity": 1, "dependency_type": "SKELETON"}
            ],
        },
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["identity"].get("model_role") in ("", None)

    listed = client.get(f"/api/products/{product['uuid']}/objects")
    assert listed.status_code == 200, listed.text
    by_uuid = {item["uuid"]: item for item in listed.json()}
    assert by_uuid[child_asm["uuid"]]["type_label"] != "SKELETON"
    assert by_uuid[top["uuid"]]["type_label"] != "SKELETON"


@requires_git
def test_where_used_tab_only_for_creo_models_extensions(client, repo_parent, tmp_path):
    """Details Where Used follows Settings → Creo Models, not Documents/Other."""
    product = _create_product(client, repo_parent)
    part = _add_part(client, product["uuid"], tmp_path, "pin.prt.1")
    notes = tmp_path / "notes.txt"
    notes.write_bytes(b"hello")
    added = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("notes.txt", notes.read_bytes(), "text/plain")},
        data={"comment": "Notes"},
    )
    assert added.status_code == 201, added.text
    doc = added.json()

    part_page = client.get(f"/products/{product['uuid']}/objects/{part['uuid']}")
    assert part_page.status_code == 200, part_page.text
    assert 'data-tab="where-used"' in part_page.text
    assert 'id="panel-where-used"' in part_page.text

    doc_page = client.get(f"/products/{product['uuid']}/objects/{doc['uuid']}")
    assert doc_page.status_code == 200, doc_page.text
    assert 'data-tab="where-used"' not in doc_page.text
    assert 'id="panel-where-used"' not in doc_page.text
    assert 'data-tab="history"' in doc_page.text
