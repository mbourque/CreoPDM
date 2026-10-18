"""Baselines, Story 1: Create Baseline captures an exact, immutable, audited snapshot."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from creopdm.app import build_context, create_app
from creopdm.auth_constants import (
    BUILTIN_PERMISSIONS,
    PERMISSION_BASELINES_CREATE,
    PERMISSION_BASELINES_VIEW,
    STARTER_ROLE_PERMISSION_KEYS,
    BuiltinRole,
)
from creopdm.config import ConfigManager
from creopdm.models.baseline import Baseline, BaselineMember
from creopdm.models.object import EngineeringObject
from creopdm.models.version import ObjectVersion
from tests.conftest import requires_git
from tests.unit.test_auth import _login, _setup_admin_and_users

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _signed_in_admin(auth_client, auth_ctx):
    _setup_admin_and_users(
        auth_client,
        auth_ctx,
        ("eng", BuiltinRole.ENGINEER.value),
        ("view", BuiltinRole.VIEWER.value),
    )
    _login(auth_client, "admin", "AdminPass1")


def _product(auth_client, name="Gearbox", files=("shaft.prt", "housing.prt", "gear.prt")):
    created = auth_client.post("/api/products", json={"name": name})
    assert created.status_code == 201, created.text
    product = created.json()
    objects = {}
    for filename in files:
        added = auth_client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": (filename, f"{filename}-v1".encode(), "application/octet-stream")},
            data={"comment": "Initial model"},
        )
        assert added.status_code == 201, added.text
        objects[filename] = added.json()
    return product, objects


def _vault(auth_ctx, product) -> Path:
    return Path(auth_ctx.config.workspace_root()) / product["vault_folder"]


def _check_in(auth_client, auth_ctx, product, obj, payload: bytes, comment="edit"):
    out = auth_client.post(f"/api/objects/{obj['uuid']}/checkout")
    assert out.status_code == 200, out.text
    (_vault(auth_ctx, product) / obj["filename"]).write_bytes(payload)
    done = auth_client.post(f"/api/objects/{obj['uuid']}/checkin", json={"comment": comment})
    assert done.status_code == 200, done.text
    return done.json()


def _create(auth_client, product, name="Design Review 01", **extra):
    return auth_client.post(
        f"/api/products/{product['uuid']}/baselines", json={"name": name, **extra}
    )


# ---- permissions ----------------------------------------------------------------------


def test_baseline_permissions_are_seeded_for_the_starter_roles():
    keys = {key for key, _ in BUILTIN_PERMISSIONS}
    assert {PERMISSION_BASELINES_VIEW, PERMISSION_BASELINES_CREATE} <= keys
    for role in BuiltinRole:
        assert PERMISSION_BASELINES_VIEW in STARTER_ROLE_PERMISSION_KEYS[role.value]
    assert PERMISSION_BASELINES_CREATE not in STARTER_ROLE_PERMISSION_KEYS[BuiltinRole.VIEWER.value]
    for role in (BuiltinRole.ADMINISTRATOR, BuiltinRole.PDM_MANAGER, BuiltinRole.ENGINEER):
        assert PERMISSION_BASELINES_CREATE in STARTER_ROLE_PERMISSION_KEYS[role.value]


@requires_git
def test_viewer_can_list_but_not_create_and_engineer_can_create(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)

    _login(auth_client, "view", "ViewPass1")
    assert auth_client.get(f"/api/products/{product['uuid']}/baselines").status_code == 200
    denied = _create(auth_client, product)
    assert denied.status_code == 403, denied.text

    _login(auth_client, "eng", "EngPass1")
    ok = _create(auth_client, product)
    assert ok.status_code == 201, ok.text


# ---- capture ---------------------------------------------------------------------------


@requires_git
def test_create_captures_the_exact_current_versions_and_never_changes(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    shaft = objects["shaft.prt"]
    second = _check_in(auth_client, auth_ctx, product, shaft, b"shaft-v2")
    assert second["display_revision"] == "A.2"

    created = _create(
        auth_client, product, "  Design   Review 01 ", description="October design review"
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Design Review 01"  # trimmed, spaces collapsed
    assert body["description"] == "October design review"
    assert body["status"] == "FINALIZED" and body["baseline_type"] == "MANUAL"
    assert body["member_count"] == 3
    assert body["created_by"] and body["finalized_at"]
    assert len(body["uuid"]) == 36  # stable identity, not the name

    def members_by_filename():
        with auth_ctx.session_factory() as db:
            baseline = db.scalar(select(Baseline).where(Baseline.uuid == body["uuid"]))
            rows = list(
                db.scalars(select(BaselineMember).where(BaselineMember.baseline_id == baseline.id))
            )
            current = {
                obj.id: obj.current_version_id
                for obj in db.scalars(select(EngineeringObject))
            }
            return baseline.member_count, {
                row.filename: (row, current[row.object_id]) for row in rows
            }

    count, members = members_by_filename()
    assert count == 3 and set(members) == {"shaft.prt", "housing.prt", "gear.prt"}
    for filename, (row, current_version_id) in members.items():
        # Exact version ids, equal to what was current when the baseline was made.
        assert row.object_version_id == current_version_id
        assert row.lifecycle_state == "IN_WORK" and row.content_hash
    shaft_row = members["shaft.prt"][0]
    assert (shaft_row.revision, shaft_row.iteration) == ("A", 2)
    with auth_ctx.session_factory() as db:
        version = db.get(ObjectVersion, shaft_row.object_version_id)
        assert version.content_hash == shaft_row.content_hash

    # A later check-in does not touch the baseline: it still points at A.2.
    third = _check_in(auth_client, auth_ctx, product, shaft, b"shaft-v3")
    assert third["display_revision"] == "A.3"
    _count, after = members_by_filename()
    assert after["shaft.prt"][0].object_version_id == shaft_row.object_version_id
    assert after["shaft.prt"][1] != shaft_row.object_version_id  # current moved on
    assert (after["shaft.prt"][0].revision, after["shaft.prt"][0].iteration) == ("A", 2)


@requires_git
def test_name_is_required_and_unique_per_product(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    other, _other_objects = _product(auth_client, "Other", ("bracket.prt",))

    blank = _create(auth_client, product, "   ")
    assert blank.status_code == 400, blank.text
    assert "name is required" in blank.json()["error"]["message"]
    too_long = _create(auth_client, product, "x" * 256)
    assert too_long.status_code == 400, too_long.text

    assert _create(auth_client, product, "Design Review 01").status_code == 201
    clash = _create(auth_client, product, "design review 01")
    assert clash.status_code == 409, clash.text
    assert clash.json()["error"]["code"] == "BASELINE_NAME_CONFLICT"
    # The same name in another product is fine.
    assert _create(auth_client, other, "Design Review 01").status_code == 201

    listed = auth_client.get(f"/api/products/{product['uuid']}/baselines").json()
    assert [row["name"] for row in listed] == ["Design Review 01"]


@requires_git
def test_a_product_without_files_cannot_be_baselined(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    empty = auth_client.post("/api/products", json={"name": "Empty"}).json()
    refused = _create(auth_client, empty)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "BASELINE_EMPTY"
    with auth_ctx.session_factory() as db:
        assert int(db.scalar(select(func.count()).select_from(Baseline)) or 0) == 0


@requires_git
def test_retry_with_the_same_operation_id_returns_the_same_baseline(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    other, _o = _product(auth_client, "Other", ("bracket.prt",))
    op = "11111111-aaaa-bbbb-cccc-000000000001"

    first = _create(auth_client, product, "Review", operation_id=op)
    assert first.status_code == 201, first.text
    again = _create(auth_client, product, "Review", operation_id=op)
    assert again.status_code == 201, again.text
    assert again.json()["uuid"] == first.json()["uuid"]
    # A retry that lost its name still gets the stored baseline.
    blank = _create(auth_client, product, "", operation_id=op)
    assert blank.json()["uuid"] == first.json()["uuid"]
    with auth_ctx.session_factory() as db:
        assert int(db.scalar(select(func.count()).select_from(Baseline)) or 0) == 1
    # The same id for another product is refused, not answered with someone else's baseline.
    reused = _create(auth_client, other, "Review", operation_id=op)
    assert reused.status_code == 400, reused.text


@requires_git
def test_creating_a_baseline_is_audited(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    assert _create(auth_client, product, "Design Review 01").status_code == 201
    with auth_ctx.session_factory() as db:
        events = auth_ctx.activities.list_events(db, q="Design Review 01")
        created = [e for e in events if e.action == "BASELINE_CREATED"]
        assert created
        assert created[0].action_label == "Baseline created"
        assert "Design Review 01" in (created[0].summary or "")
        assert "3 members" in (created[0].summary or "")
        assert (created[0].details or {}).get("member_count") == 3


# ---- protection: nothing a baseline pins may be destroyed ----------------------------------


@requires_git
def test_removing_files_a_baseline_pins_is_refused_before_anything_changes(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    shaft = objects["shaft.prt"]
    assert _create(auth_client, product, "Design Review 01").status_code == 201
    vault_file = _vault(auth_ctx, product) / "shaft.prt"
    assert vault_file.is_file()

    batch = auth_client.post(
        "/api/objects/batch/remove",
        json={"object_ids": [shaft["uuid"]], "product_id": product["uuid"]},
    )
    assert batch.status_code == 200, batch.text
    failed = batch.json()["failed"]
    assert failed and failed[0]["code"] == "VERSION_REFERENCED_BY_BASELINE"
    assert "Design Review 01" in failed[0]["message"]

    single = auth_client.delete(f"/api/objects/{shaft['uuid']}")
    assert single.status_code == 409, single.text
    assert single.json()["error"]["code"] == "VERSION_REFERENCED_BY_BASELINE"
    assert "Design Review 01" in single.json()["error"]["message"]

    # Nothing was purged or unregistered.
    assert vault_file.is_file()
    assert auth_client.get(f"/api/objects/{shaft['uuid']}").status_code == 200


@requires_git
def test_compact_and_rebuild_are_refused_while_a_baseline_pins_history(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    assert _create(auth_client, product, "Design Review 01").status_code == 201

    compact = auth_client.post(
        "/admin/products/compact",
        data={"product_id": product["uuid"], "confirm_password": "AdminPass1", "confirm": "1"},
    )
    assert compact.status_code == 400, compact.text
    assert "Design Review 01" in compact.text and "compact the vault history" in compact.text

    rebuild = auth_client.post(
        "/admin/products/rebuild",
        data={
            "product_id": product["uuid"],
            "confirm_password": "AdminPass1",
            "confirm": "1",
            "repair_action": "rebuild",
        },
    )
    assert rebuild.status_code == 400, rebuild.text
    assert "Design Review 01" in rebuild.text and "rebuild the file list" in rebuild.text


@requires_git
def test_deleting_a_product_removes_its_baselines_and_members(auth_client, auth_ctx):
    """baselines point at objects and versions (a real foreign key on PostgreSQL), so product
    delete must remove them first; SQLite does not enforce FKs, so the rows are checked directly."""
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client, "Doomed")
    keeper, _k = _product(auth_client, "Keeper", ("bracket.prt",))
    assert _create(auth_client, product, "Doomed review").status_code == 201
    assert _create(auth_client, keeper, "Keeper review").status_code == 201

    forgotten = auth_client.post(
        f"/api/products/{product['uuid']}/forget", json={"confirm_password": "AdminPass1"}
    )
    assert forgotten.status_code == 200, forgotten.text
    with auth_ctx.session_factory() as db:
        names = list(db.scalars(select(Baseline.name)))
        assert names == ["Keeper review"]
        assert int(db.scalar(select(func.count()).select_from(BaselineMember)) or 0) == 1


# ---- UI --------------------------------------------------------------------------------


@requires_git
def test_files_page_has_the_baselines_tab_pill_and_dialog(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    page = auth_client.get(f"/?product={product['uuid']}")
    assert page.status_code == 200
    text = page.text
    assert 'data-tab="baselines"' in text and 'id="panel-baselines"' in text
    assert 'id="create-baseline-btn"' in text and 'id="baseline-dialog"' in text
    assert 'id="baselines-pill-item" hidden' in text  # no baselines yet: pill hidden
    assert _create(auth_client, product).status_code == 201
    after = auth_client.get(f"/?product={product['uuid']}").text
    assert "Baselines · 1" in after
    assert 'id="baselines-pill-item" hidden' not in after
    assert 'data-tab-link="baselines"' in after

    # A viewer sees the tab and list but no way to create.
    _login(auth_client, "view", "ViewPass1")
    viewer = auth_client.get(f"/?product={product['uuid']}").text
    assert 'data-tab="baselines"' in viewer
    assert 'id="create-baseline-btn"' not in viewer and 'id="baseline-dialog"' not in viewer


def test_baselines_client_wiring():
    module = (ROOT / "src" / "creopdm" / "static" / "js" / "baselines.js").read_text(encoding="utf-8")
    assert "/baselines`" in module and "operation_id: operationId" in module
    assert "loadBaselinesTab" in module and "openCreateBaselineDialog" in module
    app = (ROOT / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'name === "baselines"' in app and 'initJobModule("baselines"' in app
    assert "[data-tab-link]" in app
    server = (ROOT / "src" / "creopdm" / "app.py").read_text(encoding="utf-8")
    assert '"baselines"' in server


# ---- Story 2: identity is the uuid, never the name --------------------------------------


@requires_git
def test_every_baseline_has_a_unique_server_made_uuid(auth_client, auth_ctx):
    import uuid as uuidlib

    _signed_in_admin(auth_client, auth_ctx)
    first_product, _a = _product(auth_client, "Alpha")
    second_product, _b = _product(auth_client, "Beta", ("bracket.prt",))

    # Same name in two products: two different identities.
    one = _create(auth_client, first_product, "Review").json()
    two = _create(auth_client, second_product, "Review").json()
    assert one["name"] == two["name"] == "Review"
    assert one["uuid"] != two["uuid"]
    for value in (one["uuid"], two["uuid"]):
        assert str(uuidlib.UUID(value)) == value  # a real uuid, canonical form

    # The client cannot choose the identity: a uuid in the request is ignored.
    forced = _create(
        auth_client, first_product, "Forced", uuid="00000000-0000-0000-0000-000000000001"
    ).json()
    assert forced["uuid"] != "00000000-0000-0000-0000-000000000001"
    assert len({one["uuid"], two["uuid"], forced["uuid"]}) == 3

    with auth_ctx.session_factory() as db:
        uuids = list(db.scalars(select(Baseline.uuid)))
        assert len(uuids) == len(set(uuids)) == 3


@requires_git
def test_a_baseline_is_found_by_uuid_not_by_name(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    created = _create(auth_client, product, "Design Review 01").json()

    found = auth_client.get(f"/api/baselines/{created['uuid']}")
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["uuid"] == created["uuid"] and body["name"] == "Design Review 01"
    assert body["product_uuid"] == product["uuid"] and body["member_count"] == 3

    # The name (or a differently written name) is never an identity.
    by_name = auth_client.get("/api/baselines/Design Review 01")
    assert by_name.status_code == 404, by_name.text
    assert by_name.json()["error"]["code"] == "BASELINE_NOT_FOUND"
    assert auth_client.get("/api/baselines/does-not-exist").status_code == 404

    # Viewing needs the permission and access to the product.
    _login(auth_client, "view", "ViewPass1")
    assert auth_client.get(f"/api/baselines/{created['uuid']}").status_code == 200


@requires_git
def test_baseline_lookup_respects_product_membership(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    other, _o = _product(auth_client, "Other", ("bracket.prt",))
    created = _create(auth_client, product, "Design Review 01").json()

    # eng may only open the other product: the baseline of the first one is not theirs to read.
    with auth_ctx.session_factory() as db:
        from creopdm.models.user import User

        eng = db.scalar(select(User).where(User.username == "eng"))
        auth_ctx.user_accounts.set_product_access(
            db, eng, access_all=False, product_uuids=[other["uuid"]]
        )
        db.commit()
    _login(auth_client, "eng", "EngPass1")
    denied = auth_client.get(f"/api/baselines/{created['uuid']}")
    assert denied.status_code == 403, denied.text


@requires_git
def test_other_records_refer_to_the_baseline_by_uuid_and_the_uuid_cannot_change(
    auth_client, auth_ctx
):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    created = _create(auth_client, product, "Design Review 01").json()

    with auth_ctx.session_factory() as db:
        # The audit entry carries the uuid, so it stays meaningful if a name ever changed.
        events = auth_ctx.activities.list_events(db, q="Design Review 01")
        entry = next(e for e in events if e.action == "BASELINE_CREATED")
        assert (entry.details or {}).get("baseline_uuid") == created["uuid"]

        # Members point at the baseline by its row id, never by name.
        baseline = db.scalar(select(Baseline).where(Baseline.uuid == created["uuid"]))
        assert all(m.baseline_id == baseline.id for m in baseline.members)
        assert len(baseline.members) == 3

        # The name is just a label: it can be edited without touching identity ...
        baseline.name = "Renamed review"
        db.flush()
        assert baseline.uuid == created["uuid"]
        # ... but the uuid itself can never be rewritten.
        baseline.uuid = "11111111-2222-3333-4444-555555555555"
        with pytest.raises(ValueError, match="uuid is its identity"):
            db.flush()
        db.rollback()

    with auth_ctx.session_factory() as db:
        assert db.scalar(select(Baseline.uuid).where(Baseline.uuid == created["uuid"])) is not None


# ---- Story 3: the exact object versions are what is stored and what is read back ----------


def _members(auth_client, baseline_uuid):
    response = auth_client.get(f"/api/baselines/{baseline_uuid}/members")
    assert response.status_code == 200, response.text
    return {row["filename"]: row for row in response.json()}


@requires_git
def test_members_are_resolved_through_the_stored_version_ids(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    shaft = objects["shaft.prt"]
    _check_in(auth_client, auth_ctx, product, shaft, b"shaft-v2")  # A.2
    created = _create(auth_client, product, "Design Review 01").json()

    with auth_ctx.session_factory() as db:
        expected = {
            obj.filename: (obj.uuid, obj.current_version.uuid, obj.current_version.content_hash)
            for obj in db.scalars(select(EngineeringObject))
        }

    members = _members(auth_client, created["uuid"])
    assert set(members) == {"shaft.prt", "housing.prt", "gear.prt"}
    for filename, row in members.items():
        object_uuid, version_uuid, content_hash = expected[filename]
        # The two uuids are the identity of the member.
        assert row["object_uuid"] == object_uuid
        assert row["version_uuid"] == version_uuid
        assert row["content_hash"] == content_hash
        assert row["status"] == "SAME" and row["lifecycle_state"] == "IN_WORK"
    assert members["shaft.prt"]["display_version"] == "A.2"
    assert members["housing.prt"]["display_version"] == "A.1"

    # The product moves on: A.3. Reopening the baseline still answers with A.2.
    _check_in(auth_client, auth_ctx, product, shaft, b"shaft-v3")  # A.3
    again = _members(auth_client, created["uuid"])
    assert again["shaft.prt"]["version_uuid"] == members["shaft.prt"]["version_uuid"]
    assert again["shaft.prt"]["display_version"] == "A.2"
    assert again["shaft.prt"]["status"] == "OUT_OF_DATE"
    assert again["shaft.prt"]["current_display_version"] == "A.3"
    assert again["shaft.prt"]["current_version_uuid"] != members["shaft.prt"]["version_uuid"]
    assert again["housing.prt"]["status"] == "SAME"


@requires_git
def test_reopening_a_baseline_ignores_current_pointers_names_and_stored_strings(
    auth_client, auth_ctx
):
    """Neither the object's current version, its filename, nor the copied revision text decides
    what the baseline says: the stored version id does."""
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    shaft = objects["shaft.prt"]
    created = _create(auth_client, product, "Design Review 01").json()
    before = _members(auth_client, created["uuid"])["shaft.prt"]

    second = _check_in(auth_client, auth_ctx, product, shaft, b"shaft-v2")
    assert second["display_revision"] == "A.2"

    with auth_ctx.session_factory() as db:
        obj = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == shaft["uuid"]))
        # The object is renamed and its revision text rewritten ...
        obj.filename = "drive_shaft.prt"
        obj.revision = "Z"
        obj.iteration = 99
        # ... and the baseline's own copied strings are tampered with.
        baseline = db.scalar(select(Baseline).where(Baseline.uuid == created["uuid"]))
        member = next(m for m in baseline.members if m.object_id == obj.id)
        member.revision = "Q"
        member.iteration = 7
        db.commit()

    after = _members(auth_client, created["uuid"])["shaft.prt"]  # name as captured
    assert after["version_uuid"] == before["version_uuid"]
    assert after["object_uuid"] == before["object_uuid"]
    # Revision and iteration come from the exact version row, not the tampered strings.
    assert (after["revision"], after["iteration"], after["display_version"]) == ("A", 1, "A.1")
    assert after["status"] == "OUT_OF_DATE"


@requires_git
def test_baseline_members_need_permission_and_product_access(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    other, _o = _product(auth_client, "Other", ("bracket.prt",))
    created = _create(auth_client, product, "Design Review 01").json()

    _login(auth_client, "view", "ViewPass1")
    assert auth_client.get(f"/api/baselines/{created['uuid']}/members").status_code == 200
    assert auth_client.get("/api/baselines/does-not-exist/members").status_code == 404

    _login(auth_client, "admin", "AdminPass1")
    with auth_ctx.session_factory() as db:
        from creopdm.models.user import User

        eng = db.scalar(select(User).where(User.username == "eng"))
        auth_ctx.user_accounts.set_product_access(
            db, eng, access_all=False, product_uuids=[other["uuid"]]
        )
        db.commit()
    _login(auth_client, "eng", "EngPass1")
    denied = auth_client.get(f"/api/baselines/{created['uuid']}/members")
    assert denied.status_code == 403, denied.text


def test_baseline_contents_dialog_is_wired():
    module = (ROOT / "src" / "creopdm" / "static" / "js" / "baselines.js").read_text(encoding="utf-8")
    assert "openBaselineMembers" in module and "/members`" in module
    assert "data-open-baseline" in module and "OUT_OF_DATE" in module
    # The page-wide click handler soft-navigates every <a href>; "#" is the current page, so a
    # link here reloaded the Files tab instead of opening the dialog.
    assert '<a href="#"' not in module
    # Wording and font follow the Files list: "In Work" (not "In work"), sans-serif names.
    assert "function stateLabel" in module and "stateLabel(m.lifecycle_state)" in module
    assert "baseline-name-cell" in module and 'class="filename-cell"' not in module
    css = (ROOT / "src" / "creopdm" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert ".baseline-name-cell" in css
    assert 'class="baseline-open"' in module and "<button type=\"button\" class=\"baseline-open\"" in module
    page = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    assert 'id="baseline-members-dialog"' in page and 'id="baseline-members-table"' in page
    assert "this baseline is immutable" in page
