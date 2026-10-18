"""Baselines Stories 37-38: archiving and renaming never break a baseline (it works by ids)."""

from __future__ import annotations

import hashlib
import uuid as uuidlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product
from creopdm.models.version import ObjectVersion
from tests.conftest import requires_git
from tests.unit.test_baselines import _create, _members, _product, _signed_in_admin


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _everything_still_works(auth_client, baseline_uuid, expect_files):
    """Read, compare, rebuild and verify a baseline: the exact files come back unchanged."""
    members = _members(auth_client, baseline_uuid)
    assert set(members) == set(expect_files)
    assert auth_client.get(f"/api/baselines/{baseline_uuid}/compare").status_code == 200

    manifest = auth_client.get(f"/api/baselines/{baseline_uuid}/workspace-manifest")
    assert manifest.status_code == 200, manifest.text
    for entry in manifest.json()["files"]:
        content = auth_client.get(entry["content_path"])
        assert content.status_code == 200, content.text
        assert content.content == f"{entry['filename']}-v1".encode()
        assert hashlib.sha256(content.content).hexdigest() == entry["sha256"]

    check = auth_client.post(f"/api/baselines/{baseline_uuid}/integrity", params={"deep": "true"})
    assert check.status_code == 200, check.text
    assert check.json()["status"] == "HEALTHY" and check.json()["hashes_ok"] == len(expect_files)
    return members


# ---- Story 37: archive does not break a baseline -------------------------------------------


@requires_git
def test_obsolete_files_stay_retrievable_through_the_baseline(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    baseline = _create(auth_client, product).json()
    # The file is retired in the product (Obsolete), as a clean-up would do.
    with auth_ctx.session_factory() as db:
        obj = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == objects["shaft.prt"]["uuid"]))
        obj.lifecycle_state = "OBSOLETE"
        obj.current_version.lifecycle_state = "OBSOLETE"
        db.commit()
    before = _members(auth_client, baseline["uuid"])
    members = _everything_still_works(auth_client, baseline["uuid"], objects)
    # Same exact version as captured: retiring the file never removes or swaps it.
    assert members["shaft.prt"]["version_uuid"] == before["shaft.prt"]["version_uuid"]
    assert members["shaft.prt"]["display_version"] == "A.1"


@requires_git
def test_an_archived_product_keeps_its_baselines_readable_and_rebuildable(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    baseline = _create(auth_client, product).json()
    with auth_ctx.session_factory() as db:
        db.scalar(select(Product).where(Product.uuid == product["uuid"])).state = "ARCHIVED"
        db.commit()

    _everything_still_works(auth_client, baseline["uuid"], objects)
    assert auth_client.get(f"/api/products/{product['uuid']}/baselines").json()[0]["uuid"] == baseline["uuid"]
    # A new baseline is a new capture, so an Archived product refuses that (and only that).
    refused = _create(auth_client, product, "After archive")
    assert refused.status_code == 409 and "Archived" in refused.text


@requires_git
def test_a_locked_product_still_reads_its_baselines_but_the_matrix_blocks_downloads(
    auth_client, auth_ctx
):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    baseline = _create(auth_client, product).json()
    with auth_ctx.session_factory() as db:
        db.scalar(select(Product).where(Product.uuid == product["uuid"])).state = "LOCKED"
        db.commit()

    # Reading is fine; the lifecycle matrix says a Locked product allows no downloads, and the
    # baseline's files follow that rule instead of bypassing it.
    assert len(_members(auth_client, baseline["uuid"])) == 3
    assert auth_client.get(f"/api/baselines/{baseline['uuid']}/compare").status_code == 200
    manifest = auth_client.get(f"/api/baselines/{baseline['uuid']}/workspace-manifest")
    assert manifest.status_code == 400 and "Locked" in manifest.text


# ---- Story 38: rename does not break a baseline ---------------------------------------------


def _rename_object_like_a_checkin_would(auth_ctx, object_uuid, new_name):
    """A check-in under a new name: the object row and a NEW version carry the new name."""
    with auth_ctx.session_factory() as db:
        obj = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == object_uuid))
        old = obj.current_version
        new = ObjectVersion(
            uuid=str(uuidlib.uuid4()),
            object_id=obj.id,
            revision=old.revision,
            iteration=old.iteration + 1,
            git_commit_hash=old.git_commit_hash,
            content_hash=old.content_hash,
            file_size=old.file_size,
            filename=new_name,
            relative_path=new_name,
            created_by="admin",
            comment=f"Renamed to {new_name}",
            lifecycle_state=old.lifecycle_state,
        )
        db.add(new)
        db.flush()
        obj.filename = new_name
        obj.relative_path = new_name
        obj.current_version_id = new.id
        db.commit()


@requires_git
def test_renaming_a_file_leaves_the_baseline_resolving_by_ids(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    baseline = _create(auth_client, product).json()
    before = _members(auth_client, baseline["uuid"])
    _rename_object_like_a_checkin_would(auth_ctx, objects["shaft.prt"]["uuid"], "drive_shaft.prt")

    # The baseline still says shaft.prt A.1 and still reaches the exact bytes (by version id).
    members = _everything_still_works(auth_client, baseline["uuid"], objects)
    assert members["shaft.prt"]["version_uuid"] == before["shaft.prt"]["version_uuid"]
    assert (members["shaft.prt"]["filename"], members["shaft.prt"]["display_version"]) == ("shaft.prt", "A.1")
    assert members["shaft.prt"]["status"] == "OUT_OF_DATE"
    assert members["shaft.prt"]["current_display_version"] == "A.2"

    # Compared with now it is the SAME file (matched by identity), not a remove plus an add.
    compare = auth_client.get(f"/api/baselines/{baseline['uuid']}/compare").json()
    rows = {row["filename"]: row for row in compare["items"]}
    assert set(rows) == {"drive_shaft.prt", "housing.prt", "gear.prt"}
    assert rows["drive_shaft.prt"]["status"] == "VERSION_CHANGED"
    assert (rows["drive_shaft.prt"]["from_version"], rows["drive_shaft.prt"]["to_version"]) == ("A.1", "A.2")
    assert compare["summary"]["removed"] == 0 and compare["summary"]["added"] == 0

    # The download still installs the file under the name it had in the baseline.
    manifest = auth_client.get(f"/api/baselines/{baseline['uuid']}/workspace-manifest").json()
    assert {f["filename"] for f in manifest["files"]} == {"shaft.prt", "housing.prt", "gear.prt"}


@requires_git
def test_renaming_the_product_leaves_its_baselines_and_their_folders_alone(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client, "Gearbox")
    baseline = _create(auth_client, product).json()
    folder = baseline["workspace_folder"]
    before = {n: m["version_uuid"] for n, m in _members(auth_client, baseline["uuid"]).items()}

    renamed = auth_client.patch(f"/api/products/{product['uuid']}", json={"name": "Gearbox Mk2"})
    assert renamed.status_code == 200, renamed.text

    detail = auth_client.get(f"/api/baselines/{baseline['uuid']}").json()
    assert detail["product_name"] == "Gearbox Mk2"  # the label follows the product
    assert detail["workspace_folder"] == folder and detail["uuid"] == baseline["uuid"]
    manifest = auth_client.get(f"/api/baselines/{baseline['uuid']}/workspace-manifest").json()
    assert manifest["product"]["vault_folder"] == product["vault_folder"]  # the vault folder is fixed
    assert {n: m["version_uuid"] for n, m in _members(auth_client, baseline["uuid"]).items()} == before
    _everything_still_works(auth_client, baseline["uuid"], objects)
