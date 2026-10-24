"""Files that share a name in different folders are different files: always told apart by UUID."""

from __future__ import annotations

from types import SimpleNamespace

from creopdm.utils.name_resolve import pick_nearest
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


# ------------------------------------------------------------------ naming a file picks the nearest
def _file(path):
    return SimpleNamespace(relative_path=path)


def test_pick_nearest_prefers_the_same_folder_then_the_closest_one():
    here, there = _file("asm/plate.prt"), _file("lib/plate.prt")
    assert pick_nearest([there, here], "asm/top.asm") is here
    assert pick_nearest([there, here], "lib/other.asm") is there
    deep, shallow = _file("lib/a/b/plate.prt"), _file("lib/plate.prt")
    assert pick_nearest([deep, shallow], "lib/a/x.asm") is deep  # shares "lib/a" with it, only "lib" with the other
    assert pick_nearest([deep, shallow], "lib/a/b/x.asm") is deep
    assert pick_nearest([deep, shallow], "lib/x.asm") is shallow  # same folder


def test_pick_nearest_does_not_guess_between_equally_near_files():
    a, b = _file("a/plate.prt"), _file("b/plate.prt")
    assert pick_nearest([a, b], "top.asm") is None
    assert pick_nearest([a], "top.asm") is a  # a single file is that file
    assert pick_nearest([], "top.asm") is None


def test_collect_metadata_erases_a_model_whose_name_exists_in_another_folder():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "src" / "creopdm" / "static" / "js" / "metadata.js").read_text(
        encoding="utf-8"
    )
    assert "sharedName: (nameCounts.get(sameNameKey(row.filename)) || 0) > 1," in source
    assert "deferErase: opts.deferErase !== false && !target.sharedName," in source
