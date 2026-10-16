"""Administration → Products Copy: new product as if it was created and Added."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from creopdm.app import build_context, create_app
from creopdm.auth_constants import BuiltinRole
from creopdm.config import ConfigManager
from creopdm.constants import CheckoutStatus, LifecycleState
from creopdm.models.ai_snapshot import ObjectVersionSnapshot
from creopdm.models.checkout import Checkout
from creopdm.models.dependency import Dependency
from creopdm.models.object import EngineeringObject
from creopdm.models.parameter import Parameter
from creopdm.models.product import Product
from creopdm.models.thumbnail import Thumbnail
from creopdm.models.user import ProductWatch, User, UserProduct
from creopdm.models.version import ObjectVersion
from creopdm.utils.hashing import calculate_sha256
from tests.conftest import requires_git
from tests.unit.test_auth import _login, _setup_admin_and_users


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _vault(auth_ctx, folder: str) -> Path:
    return Path(auth_ctx.config.workspace_root()) / folder


def _add(auth_client, product_uuid: str, filename: str, payload: bytes) -> dict:
    created = auth_client.post(
        f"/api/products/{product_uuid}/objects",
        files={"file": (filename, payload, "application/octet-stream")},
        data={"comment": "Initial model"},
    )
    assert created.status_code == 201, created.text
    return created.json()


@requires_git
def test_admin_copy_product_is_a_fresh_add(auth_client, auth_ctx):
    """Copy is a new id + one Add: A.1 In Work, metadata/Where Used kept, history/watch/checkout not."""
    _setup_admin_and_users(auth_client, auth_ctx, ("pat", BuiltinRole.ENGINEER.value))
    _login(auth_client, "admin", "AdminPass1")

    created = auth_client.post(
        "/admin/products/new",
        data={
            "name": "Source Widget",
            "number": "SW-1",
            "description": "Original",
            "vault_folder": "",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303, created.text
    listed = auth_client.get("/admin/products")
    assert listed.status_code == 200
    assert ">Copy<" in listed.text
    source = next(p for p in auth_client.get("/api/products").json() if p["name"] == "Source Widget")
    assert f'/admin/products/{source["uuid"]}/copy' in listed.text

    shaft = _add(auth_client, source["uuid"], "shaft.prt", b"shaft-v1")
    bracket = _add(auth_client, source["uuid"], "bracket.prt", b"bracket-v1")

    assert auth_client.post(f"/api/objects/{bracket['uuid']}/checkout").status_code == 200
    bracket_path = _vault(auth_ctx, source["vault_folder"]) / "bracket.prt"
    bracket_path.write_bytes(b"bracket-v2")
    checked = auth_client.post(
        f"/api/objects/{bracket['uuid']}/checkin",
        json={"comment": "Second save"},
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["display_revision"] == "A.2"

    assert auth_client.post(f"/api/objects/{shaft['uuid']}/checkout").status_code == 200
    shaft_path = _vault(auth_ctx, source["vault_folder"]) / "shaft.prt"
    with auth_ctx.session_factory() as db:
        shaft_row = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == shaft["uuid"]))
        assert shaft_row is not None and shaft_row.current_version is not None
        original_hash = shaft_row.current_version.content_hash
        bracket_row = db.scalar(
            select(EngineeringObject).where(EngineeringObject.uuid == bracket["uuid"])
        )
        assert bracket_row is not None and bracket_row.current_version is not None
        bracket_row.revision = "B"
        bracket_row.iteration = 2
        bracket_row.lifecycle_state = LifecycleState.RELEASED.value
        bracket_row.current_version.revision = "B"
        bracket_row.current_version.iteration = 2
        bracket_row.current_version.identity_json = '{"part":"bracket"}'
        bracket_row.current_version.features_json = '["hole"]'
        db.add(
            Parameter(
                object_id=bracket_row.id,
                version_id=bracket_row.current_version.id,
                name="DESCRIPTION",
                value="steel",
                data_type="STRING",
            )
        )
        db.add(
            Dependency(
                product_id=bracket_row.product_id,
                parent_object_id=bracket_row.id,
                child_object_id=shaft_row.id,
                dependency_type="ASSEMBLY_MEMBER",
                quantity=2,
            )
        )
        db.add(
            ObjectVersionSnapshot(
                uuid="snap-source-bracket",
                object_id=bracket_row.id,
                version_id=bracket_row.current_version.id,
                schema_version=1,
                snapshot_json='{"nope":true}',
            )
        )
        db.add(
            Thumbnail(
                content_hash=original_hash,
                mime="image/jpeg",
                width=4,
                height=4,
                bytes=b"jpeg-original",
            )
        )
        product_row = db.scalar(select(Product).where(Product.uuid == source["uuid"]))
        assert product_row is not None
        pat = db.scalar(select(User).where(User.username == "pat"))
        admin = db.scalar(select(User).where(User.username == "admin"))
        assert pat is not None and admin is not None
        auth_ctx.user_accounts.set_product_access(
            db, pat, access_all=False, product_uuids=[source["uuid"]]
        )
        db.add(ProductWatch(user_id=pat.id, product_id=product_row.id))
        db.commit()
        source_product_id = product_row.id

    shaft_path.write_bytes(b"shaft-dirty-checkout")
    dirty_hash = calculate_sha256(shaft_path)
    with auth_ctx.session_factory() as db:
        db.add(
            Thumbnail(
                content_hash=dirty_hash,
                mime="image/jpeg",
                width=8,
                height=8,
                bytes=b"jpeg-dirty",
            )
        )
        db.commit()
    (_vault(auth_ctx, source["vault_folder"]) / "trail.txt").write_text("session junk", encoding="utf-8")

    released = auth_client.post(
        f"/admin/products/{source['uuid']}",
        data={
            "name": "Source Widget",
            "number": "SW-1",
            "description": "Original",
            "state": "RELEASED",
        },
        follow_redirects=False,
    )
    assert released.status_code == 303, released.text

    hub = auth_client.get("/admin")
    assert "Create, copy, rename, or remove products." in hub.text

    form = auth_client.get(f"/admin/products/{source['uuid']}/copy")
    assert form.status_code == 200, form.text
    assert 'name="name" type="text" value=""' in form.text
    assert 'name="number" type="text" value=""' in form.text
    assert 'name="description" type="text" value=""' in form.text
    assert 'name="vault_folder" type="text" value=""' in form.text
    assert (
        '<textarea name="comment" rows="3" placeholder="First check in: Add 2 files"></textarea>'
        in form.text
    )
    assert "A.1" in form.text
    edit = auth_client.get(f"/admin/products/{source['uuid']}")
    assert f'/admin/products/{source["uuid"]}/copy' in edit.text

    same = auth_client.post(
        f"/admin/products/{source['uuid']}/copy",
        data={
            "name": "Source Widget",
            "number": "",
            "description": "",
            "comment": "Brought over from Source Widget",
            "vault_folder": "",
        },
    )
    assert same.status_code == 400, same.text
    assert "already exists" in same.text.lower()

    taken_vault = auth_client.post(
        f"/admin/products/{source['uuid']}/copy",
        data={
            "name": "Widget Copy",
            "number": "",
            "description": "",
            "comment": "Brought over from Source Widget",
            "vault_folder": source["vault_folder"],
        },
    )
    assert taken_vault.status_code == 400, taken_vault.text
    assert "vault" in taken_vault.text.lower()

    copied = auth_client.post(
        f"/admin/products/{source['uuid']}/copy",
        data={
            "name": "Widget Copy",
            "number": "SW-1",
            "description": "Original",
            "comment": "Brought over from Source Widget",
            "vault_folder": "widget-copy-vault",
        },
        follow_redirects=False,
    )
    assert copied.status_code == 303, copied.text

    blank = auth_client.post(
        f"/admin/products/{source['uuid']}/copy",
        data={
            "name": "Widget Copy Blank",
            "number": "SW-9",
            "description": "Blank comment",
            "comment": "   ",
        },
        follow_redirects=False,
    )
    assert blank.status_code == 303, blank.text

    api_products = auth_client.get("/api/products").json()
    copy = next(p for p in api_products if p["name"] == "Widget Copy")
    blank_copy = next(p for p in api_products if p["name"] == "Widget Copy Blank")
    assert copy["uuid"] != source["uuid"]
    assert copy["vault_folder"] == "widget-copy-vault"
    assert copy["vault_folder"] != source["vault_folder"]
    assert blank_copy["vault_folder"] == blank_copy["uuid"]
    assert copy["state"] == "IN_WORK"
    assert copy["number"] == "SW-1"
    assert copy["description"] == "Original"
    assert blank_copy["state"] == "IN_WORK"

    dest_files = {
        item["filename"]: item
        for item in auth_client.get(f"/api/products/{copy['uuid']}/objects").json()
    }
    assert set(dest_files) == {"shaft.prt", "bracket.prt"}
    for item in dest_files.values():
        assert item["display_revision"] == "A.1"
        assert item["lifecycle_state"] == "IN_WORK"
        assert item["iteration"] == 1
        assert item["uuid"] not in {shaft["uuid"], bracket["uuid"]}
    assert dest_files["shaft.prt"]["current_version"]["comment"] == "Brought over from Source Widget"
    assert dest_files["shaft.prt"]["current_version"]["content_hash"] == dirty_hash
    assert (_vault(auth_ctx, copy["vault_folder"]) / "shaft.prt").read_bytes() == b"shaft-dirty-checkout"
    assert not (_vault(auth_ctx, copy["vault_folder"]) / "trail.txt").exists()

    blank_files = auth_client.get(f"/api/products/{blank_copy['uuid']}/objects").json()
    assert blank_files
    assert all(
        item["current_version"]["comment"] == "First check in: Add 2 files" for item in blank_files
    )

    source_bracket = auth_client.get(f"/api/objects/{bracket['uuid']}").json()
    assert source_bracket["display_revision"] == "B.2"
    assert source_bracket["lifecycle_state"] == "RELEASED"
    source_shaft = auth_client.get(f"/api/objects/{shaft['uuid']}").json()
    assert source_shaft["owned_by_me"] is True
    assert (_vault(auth_ctx, source["vault_folder"]) / "shaft.prt").read_bytes() == b"shaft-dirty-checkout"

    dest_hist = auth_ctx.git.get_history(_vault(auth_ctx, copy["vault_folder"]), limit=20)
    assert [entry.message for entry in dest_hist] == [
        "Brought over from Source Widget",
        "Initialize product Widget Copy",
    ]
    source_hist = auth_ctx.git.get_history(_vault(auth_ctx, source["vault_folder"]), limit=20)
    assert len(source_hist) >= 4
    assert any(entry.message == "Second save" for entry in source_hist)
    assert "Second save" not in {entry.message for entry in dest_hist}

    with auth_ctx.session_factory() as db:
        dest = db.scalar(select(Product).where(Product.uuid == copy["uuid"]))
        assert dest is not None
        dest_ids = list(
            db.scalars(select(EngineeringObject.id).where(EngineeringObject.product_id == dest.id))
        )
        version_ids = list(
            db.scalars(select(ObjectVersion.id).where(ObjectVersion.object_id.in_(dest_ids)))
        )
        assert len(version_ids) == 2
        snap_count = db.scalar(
            select(func.count())
            .select_from(ObjectVersionSnapshot)
            .where(ObjectVersionSnapshot.version_id.in_(version_ids))
        )
        assert snap_count == 0
        checkout_count = db.scalar(
            select(func.count())
            .select_from(Checkout)
            .where(
                Checkout.object_id.in_(dest_ids),
                Checkout.status == CheckoutStatus.ACTIVE.value,
            )
        )
        assert checkout_count == 0
        source_checkout = db.scalar(
            select(func.count())
            .select_from(Checkout)
            .join(EngineeringObject, Checkout.object_id == EngineeringObject.id)
            .where(
                EngineeringObject.product_id == source_product_id,
                Checkout.status == CheckoutStatus.ACTIVE.value,
            )
        )
        assert source_checkout == 1
        edge = db.scalar(select(Dependency).where(Dependency.product_id == dest.id))
        assert edge is not None
        assert edge.quantity == 2
        assert edge.dependency_type == "ASSEMBLY_MEMBER"
        param = db.scalar(
            select(Parameter).where(Parameter.object_id.in_(dest_ids), Parameter.name == "DESCRIPTION")
        )
        assert param is not None
        assert param.value == "steel"
        identities = set(
            db.scalars(
                select(ObjectVersion.identity_json).where(ObjectVersion.id.in_(version_ids))
            )
        )
        assert '{"part":"bracket"}' in identities
        watches = db.scalar(
            select(func.count()).select_from(ProductWatch).where(ProductWatch.product_id == dest.id)
        )
        assert watches == 0
        source_watches = db.scalar(
            select(func.count())
            .select_from(ProductWatch)
            .where(ProductWatch.product_id == source_product_id)
        )
        assert source_watches == 1
        members = db.scalar(
            select(func.count()).select_from(UserProduct).where(UserProduct.product_id == dest.id)
        )
        assert members == 0
        source_members = db.scalar(
            select(func.count())
            .select_from(UserProduct)
            .where(UserProduct.product_id == source_product_id)
        )
        assert source_members == 1
        assert db.get(Thumbnail, original_hash) is not None
        assert db.get(Thumbnail, original_hash).bytes == b"jpeg-original"
        assert db.get(Thumbnail, dirty_hash).bytes == b"jpeg-dirty"
