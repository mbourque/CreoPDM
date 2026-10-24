"""Files that share a name in different folders are different files: always told apart by UUID."""

from __future__ import annotations

from types import SimpleNamespace

from creopdm.utils.name_resolve import pick_in_folder
from tests.conftest import requires_git


def _add_two(client, name="plate.prt"):
    product = client.post("/api/products", json={"name": "Twins"}).json()
    response = client.post(
        f"/api/products/{product['uuid']}/objects/from-uploads",
        files=[
            ("files", (name, b"folder-a-bytes", "application/octet-stream")),
            ("files", (name, b"folder-b-bytes-different", "application/octet-stream")),
        ],
        data={"relative_paths": [f"folderA/{name}", f"folderB/{name}"], "comment": "twins"},
    )
    assert response.status_code == 200, response.text
    listed = client.get(f"/api/products/{product['uuid']}/objects").json()
    by_path = {row["relative_path"]: row for row in listed}
    assert set(by_path) == {f"folderA/{name}", f"folderB/{name}"}
    return product, by_path[f"folderA/{name}"], by_path[f"folderB/{name}"]


@requires_git
def test_checking_out_one_of_two_same_named_files_leaves_the_other_available(client):
    product, a, b = _add_two(client)
    assert a["uuid"] != b["uuid"]
    done = client.post("/api/objects/batch/checkout", json={"object_ids": [a["uuid"]]})
    assert done.status_code == 200, done.text
    assert [item["uuid"] for item in done.json()["ok"]] == [a["uuid"]]
    rows = {
        row["uuid"]: row for row in client.get(f"/api/products/{product['uuid']}/objects").json()
    }
    assert rows[a["uuid"]]["owned_by_me"] is True
    assert rows[b["uuid"]]["owned_by_me"] is False and rows[b["uuid"]]["checkout_user"] is None
    assert rows[b["uuid"]]["can_checkout"] is True
    checkouts = client.get(f"/api/products/{product['uuid']}/checkouts").json()
    assert [row["uuid"] if "uuid" in row else row.get("object_id") for row in checkouts] == [a["uuid"]]


@requires_git
def test_checking_out_a_single_same_named_file_by_its_own_endpoint(client):
    product, a, b = _add_two(client)
    assert client.post(f"/api/objects/{b['uuid']}/checkout").status_code == 200
    rows = {row["uuid"]: row for row in client.get(f"/api/products/{product['uuid']}/objects").json()}
    assert rows[b["uuid"]]["owned_by_me"] is True
    assert rows[a["uuid"]]["owned_by_me"] is False


# ------------------------------------------------------------------ a name means the file in the same folder
def _file(path):
    return SimpleNamespace(relative_path=path)


def test_a_name_in_several_folders_means_the_file_in_the_referring_files_own_folder():
    here, there = _file("asm/plate.prt"), _file("lib/plate.prt")
    assert pick_in_folder([there, here], "asm/top.asm") is here
    assert pick_in_folder([there, here], "lib/other.asm") is there
    deep, shallow = _file("lib/a/b/plate.prt"), _file("lib/plate.prt")
    assert pick_in_folder([deep, shallow], "lib/a/b/x.asm") is deep
    assert pick_in_folder([deep, shallow], "lib/x.asm") is shallow
    # folders are independent: a nearby folder is not "the same folder"
    assert pick_in_folder([deep, shallow], "lib/a/x.asm") is None
    assert pick_in_folder([here, there], "other/x.asm") is None
    assert pick_in_folder([here, there], "top.asm") is None  # the root folder has none either


def test_a_name_that_exists_once_is_that_file_wherever_it_is():
    lone = _file("library/plate.prt")
    assert pick_in_folder([lone], "anywhere/top.asm") is lone
    assert pick_in_folder([], "top.asm") is None


def test_folder_case_does_not_matter_and_two_in_one_folder_are_not_guessed():
    a, b = _file("Face/plate.prt"), _file("face/Plate.prt")
    assert pick_in_folder([a, b], "FACE/top.asm") is None  # two candidates in that one folder
    assert pick_in_folder([a, _file("other/plate.prt")], "FACE/top.asm") is a


def test_collect_metadata_erases_a_model_whose_name_exists_in_another_folder():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "src" / "creopdm" / "static" / "js" / "metadata.js").read_text(
        encoding="utf-8"
    )
    assert "sharedName: (nameCounts.get(sameNameKey(row.filename)) || 0) > 1," in source
    assert "deferErase: opts.deferErase !== false && !target.sharedName," in source


# ------------------------------------------------------------------ end to end: Where Used per folder
def _upload(client, product_uuid, files):
    names = [(f"{folder}/{name}") for folder, name, _ in files]
    response = client.post(
        f"/api/products/{product_uuid}/objects/from-uploads",
        files=[("files", (name, data, "application/octet-stream")) for _folder, name, data in files],
        data={"relative_paths": names, "comment": "twins"},
    )
    assert response.status_code == 200, response.text
    return {row["relative_path"]: row for row in client.get(f"/api/products/{product_uuid}/objects").json()}


def _bom_metadata(parent_name, child_name):
    return {
        "identity": {"file_name": parent_name, "full_name": parent_name.upper(), "model_type": "MDL_ASSEMBLY"},
        "parameters": [],
        "bom": [
            {
                "filename": parent_name,
                "quantity": 1,
                "dependency_type": "ASSEMBLY_ROOT",
                "children": [{"filename": child_name, "quantity": 1, "dependency_type": "ASSEMBLY_MEMBER", "children": []}],
            }
        ],
    }


@requires_git
def test_where_used_only_lists_parents_from_the_same_folder_as_the_same_named_file(client):
    product = client.post("/api/products", json={"name": "Faces"}).json()
    rows = _upload(
        client,
        product["uuid"],
        [
            ("Face_Lateral", "face_mill.asm", b"lateral-mill"),
            ("Face_Lateral", "lateral.asm", b"lateral-parent"),
            ("Face_Entry-Exit", "face_mill.asm", b"entry-mill"),
            ("Face_Entry-Exit", "entry_exit.asm", b"entry-parent"),
        ],
    )
    lateral_mill = rows["Face_Lateral/face_mill.asm"]
    entry_mill = rows["Face_Entry-Exit/face_mill.asm"]
    for parent_path, parent_name in (("Face_Lateral/lateral.asm", "lateral.asm"), ("Face_Entry-Exit/entry_exit.asm", "entry_exit.asm")):
        saved = client.post(
            f"/api/objects/{rows[parent_path]['uuid']}/creo-metadata",
            json=_bom_metadata(parent_name, "face_mill.asm"),
        )
        assert saved.status_code in (200, 201), saved.text

    def parents_of(row):
        body = client.get(f"/api/objects/{row['uuid']}/where-used").json()
        return sorted(item["relative_path"] for item in body["items"])

    assert parents_of(lateral_mill) == ["Face_Lateral/lateral.asm"]
    assert parents_of(entry_mill) == ["Face_Entry-Exit/entry_exit.asm"]


# ------------------------------------------------------------------ Modified shows without a checkout
def test_modified_count_includes_files_that_are_not_checked_out_but_not_ones_held_by_others():
    from creopdm.utils.folders import folder_view_counts

    def row(**kw):
        base = dict(relative_path="a.prt", filename="a.prt", extension=".prt", object_type="CREO_PART",
                    modified_locally=True, owned_by_me=False, can_checkin=False, checkout_user=None)
        base.update(kw)
        return SimpleNamespace(**base)

    rows = [
        row(relative_path="free.prt", filename="free.prt"),  # not checked out, modified: counts
        row(relative_path="mine.prt", filename="mine.prt", owned_by_me=True, checkout_user="me"),
        row(relative_path="theirs.prt", filename="theirs.prt", checkout_user="sam"),  # held by someone else
        row(relative_path="clean.prt", filename="clean.prt", modified_locally=False),
    ]
    assert folder_view_counts(rows, "")["modified"] == 2


def test_modified_is_shown_for_unheld_files_in_the_page_navigator_and_pending_lists():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "creopdm"
    app = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'row.dataset.checkedOut !== "1"' in app and "checked_out_by_other" in app
    assert "modifiedLocally && (obj.owned_by_me || obj.can_checkin || !obj.checkout_user)" in app
    rows = (root / "utils" / "file_rows_html.py").read_text(encoding="utf-8")
    assert "obj.can_checkin or not obj.checkout_user" in rows
    nav = (root / "static" / "js" / "embed_explorer.js").read_text(encoding="utf-8")
    assert "obj.checkout_user && !obj.owned_by_me" in nav
    pending = (root / "static" / "js" / "local_cache_pending.js").read_text(encoding="utf-8")
    assert "item.canCheckin || !item.heldByOther" in pending


# ------------------------------------------------------------------ Modified tab: one row per file
@requires_git
def test_the_check_in_queue_names_the_folder_of_each_pending_save(client):
    product, a, b = _add_two(client)
    path = None
    # edit the vault copy of the first file so it is a pending save
    import creopdm.api.deps as deps  # noqa: F401  (ensures the app is imported)

    assert client.post(f"/api/objects/{a['uuid']}/checkout").status_code == 200
    saved = client.put(
        f"/api/objects/{a['uuid']}/workspace-content",
        files={"file": ("plate.prt", b"folder-a-bytes-EDITED", "application/octet-stream")},
    )
    assert saved.status_code == 200, saved.text
    queue = client.get(f"/api/products/{product['uuid']}/checkin-queue").json()
    assert [item["relative_path"] for item in queue["saves"]] == ["folderA/plate.prt"]
    assert [item["uuid"] for item in queue["saves"]] == [a["uuid"]]


def test_the_modified_tab_shows_folders_and_drops_a_local_tip_when_the_file_is_already_listed():
    from pathlib import Path

    app = (Path(__file__).resolve().parents[2] / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    parts = app.split("async function loadCheckinQueueParts(", 1)[1].split("function prefetchCheckinQueueParts", 1)[0]
    assert "vaultSaveKeys" in parts and "!vaultSaveKeys.has(" in parts and "!vaultSaveIds.has(" in parts
    assert "folderPrefix" in app and "relativePath: item.relative_path || \"\"," in app


# ------------------------------------------------------------------ Open: dependencies stay in the model's folder
def test_open_dependencies_only_come_from_the_models_own_folder(tmp_path):
    from creopdm.utils.creo_dependencies import collect_open_dependency_walk

    def obj(i, rel):
        return SimpleNamespace(id=i, relative_path=rel, filename=rel.rsplit("/", 1)[-1], object_type="CREO_PART", extension=".prt")

    model = tmp_path / "plate.asm"
    model.write_bytes(b"\x00plate.prt\x00")
    siblings = [obj(1, "A/plate.asm"), obj(2, "A/plate.prt"), obj(3, "B/plate.prt"), obj(4, "C/plate.prt")]
    siblings[0].object_type = "CREO_ASSEMBLY"
    siblings[0].extension = ".asm"
    found, _edges = collect_open_dependency_walk(
        primary_relative="A/plate.asm",
        primary_filename="plate.asm",
        object_type="CREO_ASSEMBLY",
        siblings=siblings,
        model_path=model,
        model_extensions=[".prt", ".asm"],
        all_cad_extensions=[".prt", ".asm"],
        resolve_path=lambda o: None,
        skip_object_id=1,
    )
    assert sorted(o.relative_path for o in found) == ["A/plate.prt"]
