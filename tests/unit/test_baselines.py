"""Baselines, Story 1: Create Baseline captures an exact, immutable, audited snapshot."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

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
        # A direct SQL statement stands in for corruption: the ORM refuses this edit (Story 4).
        db.execute(
            update(BaselineMember)
            .where(BaselineMember.baseline_id == baseline.id, BaselineMember.object_id == obj.id)
            .values(revision="Q", iteration=7)
        )
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
    assert '<a href="#" class' not in module and '<a class="baseline-open"' not in module
    # Wording and font follow the Files list: "In Work" (not "In work"), sans-serif names.
    assert "function stateLabel" in module and "stateLabel(m.lifecycle_state)" in module
    assert "baseline-name-cell" in module and 'class="filename-cell"' not in module
    css = (ROOT / "src" / "creopdm" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert ".baseline-name-cell" in css
    assert 'class="baseline-open"' in module and "<button type=\"button\" class=\"baseline-open\"" in module
    page = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    assert 'id="baseline-members-dialog"' in page and 'id="baseline-members-table"' in page
    assert "this baseline is immutable" in page


# ---- Story 4: a finalized baseline is immutable ---------------------------------------------


def _baseline_row(db, uuid):
    return db.scalar(select(Baseline).where(Baseline.uuid == uuid))


def test_a_new_baseline_is_finalized_with_all_members_in_one_step(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    created = _create(auth_client, product).json()
    assert created["status"] == "FINALIZED" and created["member_count"] == 3
    with auth_ctx.session_factory() as db:
        baseline = _baseline_row(db, created["uuid"])
        assert baseline.status == "FINALIZED"
        assert baseline.finalized_at is not None and baseline.finalized_by == "admin"
        assert len(baseline.members) == baseline.member_count == 3


def test_the_model_refuses_to_add_remove_or_change_members_after_finalization(
    auth_client, auth_ctx
):
    from creopdm.exceptions import BaselineImmutableError

    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    created = _create(auth_client, product).json()
    with auth_ctx.session_factory() as db:
        baseline = _baseline_row(db, created["uuid"])
        first = baseline.members[0]

        first.revision = "Z"
        with pytest.raises(BaselineImmutableError):
            db.flush()
        db.rollback()

        baseline = _baseline_row(db, created["uuid"])
        db.delete(baseline.members[0])
        with pytest.raises(BaselineImmutableError):
            db.flush()
        db.rollback()

        baseline = _baseline_row(db, created["uuid"])
        template = baseline.members[0]
        db.add(
            BaselineMember(
                baseline_id=baseline.id,
                object_id=template.object_id,
                object_version_id=template.object_version_id,
                filename="extra.prt",
                relative_path="extra.prt",
                object_type="PART",
                revision="A",
                iteration=1,
                lifecycle_state="IN_WORK",
                content_hash="x",
            )
        )
        with pytest.raises(BaselineImmutableError):
            db.flush()
        db.rollback()

    with auth_ctx.session_factory() as db:
        baseline = _baseline_row(db, created["uuid"])
        assert len(baseline.members) == 3
        assert all(m.revision == "A" for m in baseline.members)


def test_the_model_refuses_to_change_what_a_finalized_baseline_is(auth_client, auth_ctx):
    from creopdm.exceptions import BaselineImmutableError

    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    created = _create(auth_client, product).json()
    for field, value in (
        ("member_count", 99),
        ("baseline_type", "AUTOMATIC"),
        ("created_by", "someone-else"),
        ("finalized_by", "someone-else"),
        ("status", "DRAFT"),
    ):
        with auth_ctx.session_factory() as db:
            baseline = _baseline_row(db, created["uuid"])
            setattr(baseline, field, value)
            with pytest.raises(BaselineImmutableError):
                db.flush()
            db.rollback()

    # Labels stay editable, and the only status it may move to is ARCHIVED.
    with auth_ctx.session_factory() as db:
        baseline = _baseline_row(db, created["uuid"])
        baseline.description = "Reworded"
        baseline.status = "ARCHIVED"
        db.commit()
    with auth_ctx.session_factory() as db:
        baseline = _baseline_row(db, created["uuid"])
        assert baseline.description == "Reworded" and baseline.status == "ARCHIVED"
        assert baseline.member_count == 3 and len(baseline.members) == 3
        baseline.status = "DRAFT"
        with pytest.raises(BaselineImmutableError):
            db.flush()
        db.rollback()


def test_the_service_has_no_way_to_change_membership(auth_client, auth_ctx):
    from creopdm.exceptions import BaselineImmutableError

    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    created = _create(auth_client, product).json()
    with auth_ctx.session_factory() as db:
        baseline = auth_ctx.baselines.get(db, created["uuid"])
        for call in (
            lambda: auth_ctx.baselines.add_member(db, baseline, object()),
            lambda: auth_ctx.baselines.remove_member(db, baseline, 1),
            lambda: auth_ctx.baselines.replace_member_version(db, baseline, 1, 2),
            lambda: auth_ctx.baselines.replace_members(db, baseline, []),
        ):
            with pytest.raises(BaselineImmutableError) as caught:
                call()
            assert caught.value.code == "BASELINE_IMMUTABLE"
            assert caught.value.http_status == 409
    with auth_ctx.session_factory() as db:
        assert len(auth_ctx.baselines.get(db, created["uuid"]).members) == 3


def test_the_api_offers_no_way_to_modify_a_baseline(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    created = _create(auth_client, product).json()
    base = f"/api/baselines/{created['uuid']}"
    for method, path in (
        ("post", f"{base}/members"),
        ("put", f"{base}/members"),
        ("patch", f"{base}/members"),
        ("delete", f"{base}/members"),
        ("put", base),
        ("patch", base),
        ("delete", base),
        ("post", base),
    ):
        response = auth_client.request(method.upper(), path, json={"name": "x"})
        assert response.status_code in (404, 405), (method, path, response.status_code)
    assert len(_members(auth_client, created["uuid"])) == 3
    assert auth_client.get(base).json()["name"] == "Design Review 01"


@requires_git
def test_a_different_configuration_needs_a_new_baseline(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    first = _create(auth_client, product, "Rev A review").json()
    _check_in(auth_client, auth_ctx, product, objects["shaft.prt"], b"shaft-v2")
    second = _create(auth_client, product, "Rev B review").json()
    assert first["uuid"] != second["uuid"]

    assert _members(auth_client, first["uuid"])["shaft.prt"]["iteration"] == 1
    assert _members(auth_client, second["uuid"])["shaft.prt"]["iteration"] == 2


def test_finalized_status_is_explained_in_the_ui():
    module = (ROOT / "src" / "creopdm" / "static" / "js" / "baselines.js").read_text(encoding="utf-8")
    assert "function statusHint" in module and "can never change" in module
    assert "title=\"${esc(statusHint(item.status))}\"" in module


# ---- Story 5: a new check-in does not change an existing baseline -------------------------


@requires_git
def test_new_check_ins_leave_an_existing_baseline_unchanged(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    shaft = objects["shaft.prt"]
    _check_in(auth_client, auth_ctx, product, shaft, b"shaft-v2")  # shaft is now A.2
    created = _create(auth_client, product, "Shaft at A.2").json()

    def snapshot():
        with auth_ctx.session_factory() as db:
            baseline = _baseline_row(db, created["uuid"])
            return baseline.member_count, sorted(
                (m.id, m.object_id, m.object_version_id, m.revision, m.iteration, m.content_hash)
                for m in baseline.members
            )

    before = snapshot()
    before_members = _members(auth_client, created["uuid"])
    assert before_members["shaft.prt"]["iteration"] == 2

    _check_in(auth_client, auth_ctx, product, shaft, b"shaft-v3")  # A.3
    _check_in(auth_client, auth_ctx, product, shaft, b"shaft-v4")  # A.4

    # The object moved on, the baseline did not: same rows, same version ids, same hashes.
    assert snapshot() == before
    after_members = _members(auth_client, created["uuid"])
    assert after_members["shaft.prt"]["iteration"] == 2
    assert after_members["shaft.prt"]["revision"] == "A"
    assert after_members["shaft.prt"]["version_uuid"] == before_members["shaft.prt"]["version_uuid"]
    assert after_members["shaft.prt"]["content_hash"] == before_members["shaft.prt"]["content_hash"]
    assert after_members["shaft.prt"]["status"] == "OUT_OF_DATE"  # reported as newer, not rewritten
    assert after_members["housing.prt"]["status"] == "SAME"
    assert after_members["housing.prt"]["version_uuid"] == before_members["housing.prt"]["version_uuid"]

    listed = auth_client.get(f"/api/products/{product['uuid']}/baselines").json()
    assert [b["member_count"] for b in listed] == [3]

    # The pinned A.2 version row itself is still there and still holds A.2's content.
    with auth_ctx.session_factory() as db:
        version = db.scalar(
            select(ObjectVersion).where(ObjectVersion.uuid == before_members["shaft.prt"]["version_uuid"])
        )
        assert version is not None and (version.revision, version.iteration) == ("A", 2)
        current = db.scalar(
            select(EngineeringObject).where(EngineeringObject.uuid == shaft["uuid"])
        ).current_version
        assert current.id != version.id and current.iteration == 4


# ---- Story 6: a new revision does not change an existing baseline -------------------------


@requires_git
def test_a_new_revision_leaves_an_existing_baseline_unchanged(auth_client, auth_ctx):
    from tests.unit.test_revise import _released_under_change

    product, obj = _released_under_change(auth_client, auth_ctx, filename="shaft.prt")
    created = _create(auth_client, product, "Released A.1").json()

    def pinned():
        with auth_ctx.session_factory() as db:
            baseline = _baseline_row(db, created["uuid"])
            return baseline.member_count, sorted(
                (m.id, m.object_version_id, m.revision, m.iteration, m.lifecycle_state, m.content_hash)
                for m in baseline.members
            )

    before = pinned()
    before_members = _members(auth_client, created["uuid"])
    assert before_members["shaft.prt"]["revision"] == "A"
    assert before_members["shaft.prt"]["lifecycle_state"] == "RELEASED"

    revised = auth_client.post(f"/api/objects/{obj['uuid']}/revise", json={"reason": "Design change"})
    assert revised.status_code == 200, revised.text
    assert revised.json()["revision"] == "B"

    # The file now has revision B, the baseline still says A (same version, same state, same rows).
    assert pinned() == before
    after_members = _members(auth_client, created["uuid"])
    assert after_members["shaft.prt"]["revision"] == "A"
    assert after_members["shaft.prt"]["version_uuid"] == before_members["shaft.prt"]["version_uuid"]
    assert after_members["shaft.prt"]["lifecycle_state"] == "RELEASED"
    assert after_members["shaft.prt"]["status"] == "OUT_OF_DATE"
    assert after_members["shaft.prt"]["current_display_version"] == "B.1"

    with auth_ctx.session_factory() as db:
        version = db.scalar(
            select(ObjectVersion).where(ObjectVersion.uuid == before_members["shaft.prt"]["version_uuid"])
        )
        assert version is not None and (version.revision, version.iteration) == ("A", 1)
        assert version.lifecycle_state == "RELEASED"


# ---- Story 7: the exact structure is captured with the baseline ---------------------------


def _edge(db, product_row, parent, child_id, kind="ASSEMBLY_MEMBER", qty=1.0):
    from creopdm.models.dependency import Dependency

    db.add(
        Dependency(
            product_id=product_row.id,
            parent_object_id=parent.id,
            child_object_id=child_id,
            dependency_type=kind,
            quantity=qty,
        )
    )


def _structure_product(auth_client, auth_ctx):
    """gear.prt uses shaft.prt (x2, required), housing.prt (reference) and ghost.prt (no version)."""
    from creopdm.models.product import Product

    product, objects = _product(auth_client)
    with auth_ctx.session_factory() as db:
        row = db.scalar(select(Product).where(Product.uuid == product["uuid"]))
        by_name = {
            o.filename: o
            for o in db.scalars(select(EngineeringObject).where(EngineeringObject.product_id == row.id))
        }
        ghost = EngineeringObject(
            uuid="00000000-0000-4000-8000-00000000abcd",
            product_id=row.id,
            name="ghost",
            filename="ghost.prt",
            extension=".prt",
            relative_path="ghost.prt",
        )
        db.add(ghost)
        db.flush()
        gear = by_name["gear.prt"]
        _edge(db, row, gear, by_name["shaft.prt"].id, "ASSEMBLY_MEMBER", 2.0)
        _edge(db, row, gear, by_name["housing.prt"].id, "REFERENCE")
        _edge(db, row, gear, ghost.id, "ASSEMBLY_MEMBER")
        db.commit()
    return product, objects


def _dependencies(auth_client, baseline_uuid):
    response = auth_client.get(f"/api/baselines/{baseline_uuid}/dependencies")
    assert response.status_code == 200, response.text
    return {row["child_filename"]: row for row in response.json()}


def test_a_baseline_captures_the_structure_with_exact_versions(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _structure_product(auth_client, auth_ctx)
    created = _create(auth_client, product).json()
    assert created["dependency_count"] == 3
    assert created["unresolved_dependency_count"] == 1

    members = _members(auth_client, created["uuid"])
    edges = _dependencies(auth_client, created["uuid"])
    assert set(edges) == {"shaft.prt", "housing.prt", "ghost.prt"}

    shaft = edges["shaft.prt"]
    assert shaft["parent_filename"] == "gear.prt"
    assert shaft["parent_version_uuid"] == members["gear.prt"]["version_uuid"]
    assert shaft["child_version_uuid"] == members["shaft.prt"]["version_uuid"]
    assert shaft["child_display_version"] == "A.1" and shaft["quantity"] == 2.0
    assert shaft["required"] is True and shaft["resolved"] is True
    # A plain reference is recorded but not required.
    assert edges["housing.prt"]["required"] is False and edges["housing.prt"]["resolved"] is True
    # A child with no captured version is kept as an unresolved edge, not dropped or guessed.
    ghost = edges["ghost.prt"]
    assert ghost["resolved"] is False and ghost["required"] is True
    assert ghost["child_version_uuid"] is None and ghost["child_display_version"] is None


@requires_git
def test_the_captured_structure_is_not_recomputed_from_latest_versions(auth_client, auth_ctx):
    from creopdm.models.dependency import Dependency

    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _structure_product(auth_client, auth_ctx)
    created = _create(auth_client, product).json()
    before = _dependencies(auth_client, created["uuid"])

    # The product moves on: shaft gets a new version and the live edge is deleted.
    _check_in(auth_client, auth_ctx, product, objects["shaft.prt"], b"shaft-v2")
    with auth_ctx.session_factory() as db:
        for edge in db.scalars(select(Dependency)):
            db.delete(edge)
        db.commit()

    after = _dependencies(auth_client, created["uuid"])
    assert after == before
    assert after["shaft.prt"]["child_display_version"] == "A.1"
    assert auth_client.get(f"/api/baselines/{created['uuid']}").json()["dependency_count"] == 3


def test_a_product_without_structure_has_no_dependencies(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    created = _create(auth_client, product).json()
    assert created["dependency_count"] == 0 and created["unresolved_dependency_count"] == 0
    assert _dependencies(auth_client, created["uuid"]) == {}


def test_the_captured_structure_is_immutable_and_cannot_be_unpinned(auth_client, auth_ctx):
    from creopdm.exceptions import BaselineImmutableError
    from creopdm.models.baseline import BaselineDependency
    from creopdm.services.baseline_guard import baseline_names_pinning

    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _structure_product(auth_client, auth_ctx)
    created = _create(auth_client, product).json()
    with auth_ctx.session_factory() as db:
        edge = db.scalar(select(BaselineDependency))
        edge.quantity = 99
        with pytest.raises(BaselineImmutableError):
            db.flush()
        db.rollback()
        edge = db.scalar(select(BaselineDependency))
        db.delete(edge)
        with pytest.raises(BaselineImmutableError):
            db.flush()
        db.rollback()
        assert db.scalar(select(func.count()).select_from(BaselineDependency)) == 3
        # The unresolved child is not a member, but an edge still points at it: it stays pinned.
        ghost = db.scalar(select(EngineeringObject).where(EngineeringObject.filename == "ghost.prt"))
        assert baseline_names_pinning(db, [ghost.id]) == ["Design Review 01"]
    assert created["dependency_count"] == 3


def test_structure_rows_need_permission_and_leave_with_the_product(auth_client, auth_ctx):
    from creopdm.models.baseline import BaselineDependency

    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _structure_product(auth_client, auth_ctx)
    created = _create(auth_client, product).json()
    assert auth_client.get(f"/api/baselines/{created['uuid']}/dependencies").status_code == 200
    for method in ("post", "put", "patch", "delete"):
        response = auth_client.request(
            method.upper(), f"/api/baselines/{created['uuid']}/dependencies", json={}
        )
        assert response.status_code in (404, 405)

    removed = auth_client.post(
        f"/api/products/{product['uuid']}/forget", json={"confirm_password": "AdminPass1"}
    )
    assert removed.status_code == 200, removed.text
    with auth_ctx.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(BaselineDependency)) == 0
        assert db.scalar(select(func.count()).select_from(Baseline)) == 0


def test_baseline_structure_ui_is_wired():
    module = (ROOT / "src" / "creopdm" / "static" / "js" / "baselines.js").read_text(encoding="utf-8")
    assert "/dependencies`" in module and "function renderStructure" in module
    assert "baseline-unresolved" in module and "unresolved_dependency_count" in module
    template = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    assert 'id="baseline-structure-table"' in template


# ---- Story 7b: a missing Where Used index is never silently an empty structure -------------


def _assembly_product(auth_client, auth_ctx, with_edge=False):
    from creopdm.models.product import Product

    product, objects = _product(auth_client, "Rig", ("top.asm", "bolt.prt"))
    if with_edge:
        with auth_ctx.session_factory() as db:
            row = db.scalar(select(Product).where(Product.uuid == product["uuid"]))
            by_name = {
                o.filename: o
                for o in db.scalars(
                    select(EngineeringObject).where(EngineeringObject.product_id == row.id)
                )
            }
            assert by_name["top.asm"].object_type == "CREO_ASSEMBLY"
            _edge(db, row, by_name["top.asm"], by_name["bolt.prt"].id)
            db.commit()
    return product, objects


def test_creating_without_where_used_asks_first_and_creates_nothing(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _assembly_product(auth_client, auth_ctx)
    refused = _create(auth_client, product)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "BASELINE_STRUCTURE_NOT_INDEXED"
    assert "Where Used" in refused.json()["error"]["message"]
    with auth_ctx.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Baseline)) == 0


def test_the_user_can_confirm_a_baseline_without_structure_and_it_says_so(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _assembly_product(auth_client, auth_ctx)
    created = _create(auth_client, product, accept_missing_structure=True)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["structure_indexed"] is False and body["dependency_count"] == 0
    assert auth_client.get(f"/api/baselines/{body['uuid']}").json()["structure_indexed"] is False
    with auth_ctx.session_factory() as db:
        events = auth_ctx.activities.list_events(db, q="Design Review 01")
        entry = next(e for e in events if e.action == "BASELINE_CREATED")
        assert (entry.details or {}).get("structure_indexed") is False


def test_no_confirmation_is_needed_when_structure_exists_or_is_not_applicable(
    auth_client, auth_ctx
):
    _signed_in_admin(auth_client, auth_ctx)
    indexed, _o = _assembly_product(auth_client, auth_ctx, with_edge=True)
    created = _create(auth_client, indexed, "With structure")
    assert created.status_code == 201, created.text
    assert created.json()["structure_indexed"] is True
    assert created.json()["dependency_count"] == 1

    parts_only, _p = _product(auth_client, "Parts only", ("a.prt", "b.prt"))
    plain = _create(auth_client, parts_only, "Plain")
    assert plain.status_code == 201, plain.text
    assert plain.json()["structure_indexed"] is True


def test_missing_structure_ui_is_wired():
    module = (ROOT / "src" / "creopdm" / "static" / "js" / "baselines.js").read_text(encoding="utf-8")
    assert "BASELINE_STRUCTURE_NOT_INDEXED" in module and "accept_missing_structure" in module
    assert "baseline-no-structure" in module and "structure_indexed === false" in module
    template = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    assert 'id="baseline-accept-structure"' in template and 'id="baseline-no-structure"' in template


# ---- Story 9: the configuration is validated before a baseline is finalized -------------------


def _tamper(auth_ctx, object_uuid, **fields):
    """Change the current version row directly (a stand-in for a damaged vault or database)."""
    with auth_ctx.session_factory() as db:
        obj = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == object_uuid))
        version = obj.current_version
        original = {name: getattr(version, name) for name in fields}
        for name, value in fields.items():
            setattr(version, name, value)
        db.commit()
    return original


def _no_baselines(auth_ctx):
    with auth_ctx.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Baseline)) == 0
        assert db.scalar(select(func.count()).select_from(BaselineMember)) == 0


@requires_git
def test_content_missing_from_the_vault_refuses_the_baseline_and_names_the_file(
    auth_client, auth_ctx
):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    original = _tamper(auth_ctx, objects["shaft.prt"]["uuid"], git_commit_hash="0" * 40)

    refused = _create(auth_client, product)
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "BASELINE_VALIDATION_FAILED"
    assert "shaft.prt" in error["message"] and "No baseline was created" in error["message"]
    assert [p["code"] for p in error["details"]["problems"]] == ["CONTENT_MISSING"]
    _no_baselines(auth_ctx)

    # Repair it and the same request now succeeds.
    _tamper(auth_ctx, objects["shaft.prt"]["uuid"], **original)
    assert _create(auth_client, product).status_code == 201


@requires_git
def test_every_failing_file_is_reported_and_nothing_is_created(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    _tamper(auth_ctx, objects["shaft.prt"]["uuid"], git_commit_hash=None)
    _tamper(auth_ctx, objects["housing.prt"]["uuid"], git_commit_hash="1" * 40)
    with auth_ctx.session_factory() as db:
        gear = db.scalar(
            select(EngineeringObject).where(EngineeringObject.uuid == objects["gear.prt"]["uuid"])
        )
        recorded = gear.current_version.file_size
    assert recorded
    _tamper(auth_ctx, objects["gear.prt"]["uuid"], file_size=recorded + 5)

    refused = _create(auth_client, product)
    assert refused.status_code == 409, refused.text
    problems = {p["file"]: p["code"] for p in refused.json()["error"]["details"]["problems"]}
    assert problems == {
        "shaft.prt": "NO_STORED_COMMIT",
        "housing.prt": "CONTENT_MISSING",
        "gear.prt": "CONTENT_SIZE_MISMATCH",
    }
    _no_baselines(auth_ctx)


def test_an_archived_product_cannot_be_baselined_but_a_locked_one_can(auth_client, auth_ctx):
    from creopdm.models.product import Product

    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)

    def set_state(value):
        with auth_ctx.session_factory() as db:
            db.scalar(select(Product).where(Product.uuid == product["uuid"])).state = value
            db.commit()

    set_state("ARCHIVED")
    refused = _create(auth_client, product)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "BASELINE_VALIDATION_FAILED"
    assert "Archived" in refused.json()["error"]["message"]
    _no_baselines(auth_ctx)

    # A baseline only reads the configuration, so a frozen product can still be baselined.
    set_state("LOCKED")
    assert _create(auth_client, product, "Locked snapshot").status_code == 201


@requires_git
def test_blob_sizes_checks_many_stored_files_in_one_call(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    with auth_ctx.session_factory() as db:
        version = db.scalar(
            select(EngineeringObject).where(EngineeringObject.uuid == objects["shaft.prt"]["uuid"])
        ).current_version
        commit, size = version.git_commit_hash, version.file_size
    sizes = auth_ctx.git.blob_sizes(
        _vault(auth_ctx, product),
        [f"{commit}:shaft.prt", f"{commit}:not-there.prt", f"{'0' * 40}:shaft.prt"],
    )
    assert sizes == [size, None, None]
    assert auth_ctx.git.blob_sizes(_vault(auth_ctx, product), []) == []


# ---- Story 10: a release baseline is validated strictly -------------------------------------


def test_release_baseline_is_blocked_by_an_unresolved_required_dependency(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _structure_product(auth_client, auth_ctx)  # gear needs ghost.prt (no version)

    refused = _create(auth_client, product, "Release R1", baseline_type="RELEASE")
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "BASELINE_VALIDATION_FAILED"
    assert "No release baseline was created" in error["message"]
    assert "gear.prt needs ghost.prt" in error["message"]
    assert error["details"]["problems"] == [
        {
            "code": "UNRESOLVED_REQUIRED_DEPENDENCY",
            "parent": "gear.prt",
            "child": "ghost.prt",
            "dependency_type": "ASSEMBLY_MEMBER",
        }
    ]
    _no_baselines(auth_ctx)

    # The same configuration is allowed as a manual baseline, with the gap recorded (not hidden).
    manual = _create(auth_client, product, "Working copy")
    assert manual.status_code == 201, manual.text
    assert manual.json()["baseline_type"] == "MANUAL"
    assert manual.json()["unresolved_dependency_count"] == 1


def test_release_baseline_succeeds_when_every_required_dependency_is_resolved(
    auth_client, auth_ctx
):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _assembly_product(auth_client, auth_ctx, with_edge=True)
    created = _create(auth_client, product, "Release R1", baseline_type="release")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["baseline_type"] == "RELEASE" and body["status"] == "FINALIZED"
    assert body["dependency_count"] == 1 and body["unresolved_dependency_count"] == 0


def test_release_baseline_ignores_unresolved_optional_references(auth_client, auth_ctx):
    from creopdm.models.product import Product

    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _structure_product(auth_client, auth_ctx)
    with auth_ctx.session_factory() as db:
        row = db.scalar(select(Product).where(Product.uuid == product["uuid"]))
        from creopdm.models.dependency import Dependency

        # Keep only a REFERENCE edge to the unversioned object: optional, so not blocking.
        ghost = db.scalar(select(EngineeringObject).where(EngineeringObject.filename == "ghost.prt"))
        for edge in db.scalars(select(Dependency)):
            db.delete(edge)
        db.flush()
        gear = db.scalar(select(EngineeringObject).where(EngineeringObject.filename == "gear.prt"))
        _edge(db, row, gear, ghost.id, "REFERENCE")
        db.commit()
    created = _create(auth_client, product, "Release R2", baseline_type="RELEASE")
    assert created.status_code == 201, created.text
    assert created.json()["unresolved_dependency_count"] == 1


def test_release_baseline_cannot_waive_a_missing_where_used_index(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _assembly_product(auth_client, auth_ctx)  # assembly, no edges
    refused = _create(
        auth_client, product, "Release R1", baseline_type="RELEASE", accept_missing_structure=True
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "BASELINE_VALIDATION_FAILED"
    assert "Where Used" in refused.json()["error"]["message"]
    _no_baselines(auth_ctx)


def test_an_unknown_baseline_type_is_refused(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    refused = _create(auth_client, product, baseline_type="NIGHTLY")
    assert 400 <= refused.status_code < 500, refused.text
    _no_baselines(auth_ctx)


def test_release_baseline_choice_is_in_the_dialog():
    module = (ROOT / "src" / "creopdm" / "static" / "js" / "baselines.js").read_text(encoding="utf-8")
    assert 'baseline_type: $("#baseline-release")?.checked ? "RELEASE" : "MANUAL"' in module
    template = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    assert 'id="baseline-release"' in template and "strict" in template
    # Check boxes use the shared "choice" row (box beside its label), not a stacked label.
    assert 'class="choice baseline-release-choice"' in template
    assert 'class="choice baseline-structure-confirm"' in template


# ---- Story 11: baseline creation is all-or-nothing -------------------------------------------


def _create_expecting_failure(auth_client, product, name="Design Review 01", **extra):
    """The create request blows up part-way: either the test client re-raises it or it answers 5xx."""
    try:
        response = _create(auth_client, product, name, **extra)
    except RuntimeError:
        return
    assert response.status_code >= 500, response.text


def _nothing_left_behind(auth_ctx):
    from creopdm.models.baseline import BaselineDependency

    with auth_ctx.session_factory() as db:
        for model in (Baseline, BaselineMember, BaselineDependency):
            assert db.scalar(select(func.count()).select_from(model)) == 0, model.__name__
        events = auth_ctx.activities.list_events(db, q="Design Review 01")
        assert not [e for e in events if e.action == "BASELINE_CREATED"]


@pytest.mark.parametrize("failing_step", ["members", "structure", "audit", "commit"])
def test_a_failure_at_any_step_leaves_no_partial_baseline(
    auth_client, auth_ctx, monkeypatch, failing_step
):
    from sqlalchemy.orm import Session

    from creopdm.services.baseline_service import BaselineService

    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _structure_product(auth_client, auth_ctx)

    def boom(*_args, **_kwargs):
        raise RuntimeError(f"injected failure at {failing_step}")

    with monkeypatch.context() as patch:
        if failing_step == "members":
            patch.setattr(BaselineService, "_members", staticmethod(boom))
        elif failing_step == "structure":
            patch.setattr(BaselineService, "_dependencies", staticmethod(boom))
        elif failing_step == "audit":
            patch.setattr(auth_ctx.activities, "record", boom)
        else:
            real_commit = Session.commit

            def failing_commit(self, *args, **kwargs):
                # By commit time the rows are flushed, so look at what the session holds.
                if any(isinstance(obj, Baseline) for obj in self.identity_map.values()):
                    raise RuntimeError("injected failure at commit")
                return real_commit(self, *args, **kwargs)

            patch.setattr(Session, "commit", failing_commit)
        _create_expecting_failure(auth_client, product, operation_id="op-fail-1")

    # No draft or finalized baseline, no members, no structure rows, no audit entry.
    _nothing_left_behind(auth_ctx)

    # The product lock was released and the same request now works, exactly once.
    retry = _create(auth_client, product, operation_id="op-fail-1")
    assert retry.status_code == 201, retry.text
    again = _create(auth_client, product, operation_id="op-fail-1")
    assert again.json()["uuid"] == retry.json()["uuid"]
    with auth_ctx.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Baseline)) == 1
        rows = list(db.scalars(select(Baseline)))
        assert [b.status for b in rows] == ["FINALIZED"]
        assert rows[0].member_count == len(rows[0].members) == 3


def test_a_baseline_is_never_visible_as_a_draft(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    for index in range(3):
        assert _create(auth_client, product, f"Review {index}").status_code == 201
    with auth_ctx.session_factory() as db:
        statuses = set(db.scalars(select(Baseline.status)))
        assert statuses == {"FINALIZED"}
        assert all(
            b.member_count == len(b.members) and b.finalized_at is not None
            for b in db.scalars(select(Baseline))
        )
    listed = auth_client.get(f"/api/products/{product['uuid']}/baselines").json()
    assert {row["status"] for row in listed} == {"FINALIZED"}


# ---- Story 12: the baseline records the repository commit ------------------------------------


def _head(auth_ctx, product) -> str:
    return auth_ctx.git.get_head(_vault(auth_ctx, product)).strip().lower()


@requires_git
def test_a_baseline_records_the_full_repository_commit(auth_client, auth_ctx):
    import re

    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    head = _head(auth_ctx, product)
    created = _create(auth_client, product).json()

    assert re.fullmatch(r"[0-9a-f]{40}", created["git_commit_sha"])  # the whole SHA, not a prefix
    assert created["git_commit_sha"] == head
    assert auth_client.get(f"/api/baselines/{created['uuid']}").json()["git_commit_sha"] == head
    listed = auth_client.get(f"/api/products/{product['uuid']}/baselines").json()
    assert listed[0]["git_commit_sha"] == head

    # It is a record, never an identity: not the baseline uuid and not any version uuid.
    assert created["git_commit_sha"] != created["uuid"]
    members = _members(auth_client, created["uuid"])
    assert head not in {m["version_uuid"] for m in members.values()} | {
        m["object_uuid"] for m in members.values()
    }
    with auth_ctx.session_factory() as db:
        events = auth_ctx.activities.list_events(db, q="Design Review 01")
        entry = next(e for e in events if e.action == "BASELINE_CREATED")
        assert (entry.details or {}).get("git_commit_sha") == head


@requires_git
def test_the_recorded_commit_does_not_follow_the_repository(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    first = _create(auth_client, product, "At first commit").json()
    _check_in(auth_client, auth_ctx, product, objects["shaft.prt"], b"shaft-v2")
    moved = _head(auth_ctx, product)
    assert moved != first["git_commit_sha"]

    # The repository moved on; the baseline still points at the commit it was made at.
    assert auth_client.get(f"/api/baselines/{first['uuid']}").json()["git_commit_sha"] != moved
    second = _create(auth_client, product, "At second commit").json()
    assert second["git_commit_sha"] == moved
    assert second["git_commit_sha"] != first["git_commit_sha"]


@requires_git
def test_the_recorded_commit_is_frozen(auth_client, auth_ctx):
    from creopdm.exceptions import BaselineImmutableError

    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    created = _create(auth_client, product).json()
    with auth_ctx.session_factory() as db:
        baseline = _baseline_row(db, created["uuid"])
        baseline.git_commit_sha = "f" * 40
        with pytest.raises(BaselineImmutableError):
            db.flush()
        db.rollback()
    assert (
        auth_client.get(f"/api/baselines/{created['uuid']}").json()["git_commit_sha"]
        == created["git_commit_sha"]
    )


def test_baseline_commit_is_shown_in_the_contents_dialog():
    module = (ROOT / "src" / "creopdm" / "static" / "js" / "baselines.js").read_text(encoding="utf-8")
    assert "git_commit_sha" in module and "baseline-commit-sha" in module
    template = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    assert 'id="baseline-commit-sha"' in template
    # The dialog opens at its top: the title takes focus and the dialog itself never scrolls.
    assert 'id="baseline-members-title" tabindex="-1"' in template
    assert "title?.focus({ preventScroll: true })" in module
    css = (ROOT / "src" / "creopdm" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert "max-height: 94vh; overflow: hidden; border-radius: 12px; }" in css
    # Files and Structure are two views of one dialog so each table gets the full height.
    assert "function setBaselineView" in module and "data-baseline-view" in template


# ---- Stories 14-16: optional Git tag, moved-tag detection, tag failure is harmless -------------


def _tag_target(auth_ctx, product, name):
    return auth_ctx.git.tag_target(_vault(auth_ctx, product), name)


def _git_check(auth_client, baseline_uuid):
    response = auth_client.get(f"/api/baselines/{baseline_uuid}/git-check")
    assert response.status_code == 200, response.text
    return response.json()


@requires_git
def test_a_baseline_can_carry_an_optional_git_tag_on_its_commit(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)

    plain = _create(auth_client, product, "No tag").json()
    assert plain["git_tag_name"] is None and plain["git_tag_status"] == "NONE"
    assert _git_check(auth_client, plain["uuid"])["state"] == "NO_TAG"

    tagged = _create(auth_client, product, "Tagged", git_tag="baseline/design-review-01").json()
    assert tagged["git_tag_name"] == "baseline/design-review-01"
    assert tagged["git_tag_status"] == "CREATED" and tagged["git_tag_error"] is None
    assert _tag_target(auth_ctx, product, "baseline/design-review-01") == tagged["git_commit_sha"]
    check = _git_check(auth_client, tagged["uuid"])
    assert check["state"] == "OK" and check["warning"] is None
    assert check["tag_points_at"] == check["stored_commit"] == tagged["git_commit_sha"]
    with auth_ctx.session_factory() as db:
        events = auth_ctx.activities.list_events(db, q="Tagged")
        entry = next(e for e in events if e.action == "BASELINE_CREATED")
        assert (entry.details or {}).get("git_tag_name") == "baseline/design-review-01"


@pytest.mark.parametrize(
    "bad", ["bad name", "a..b", "-leading", "trailing/", "x.lock", "has~tilde", "a//b", "/abs"]
)
def test_unsafe_tag_names_are_refused_before_anything_is_created(auth_client, auth_ctx, bad):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    refused = _create(auth_client, product, git_tag=bad)
    assert 400 <= refused.status_code < 500, refused.text
    _no_baselines(auth_ctx)


@requires_git
def test_a_moved_or_deleted_tag_is_reported_and_the_stored_commit_never_follows(
    auth_client, auth_ctx
):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    tagged = _create(auth_client, product, "Tagged", git_tag="baseline/r1").json()
    original = tagged["git_commit_sha"]
    _check_in(auth_client, auth_ctx, product, objects["shaft.prt"], b"shaft-v2")
    newer = _head(auth_ctx, product)
    assert newer != original

    # Someone retags the repository (accidentally or not).
    vault = _vault(auth_ctx, product)
    auth_ctx.git._run(["tag", "-f", "baseline/r1", newer], cwd=vault)
    check = _git_check(auth_client, tagged["uuid"])
    assert check["state"] == "MOVED"
    assert check["tag_points_at"] == newer and check["stored_commit"] == original
    assert "Integrity warning" in check["warning"] and newer[:12] in check["warning"]
    # CreoPDM reports it and does not silently adopt the new commit.
    after = auth_client.get(f"/api/baselines/{tagged['uuid']}").json()
    assert after["git_commit_sha"] == original and after["git_tag_status"] == "CREATED"

    # Moving it back clears the warning; deleting it is reported as missing.
    auth_ctx.git._run(["tag", "-f", "baseline/r1", original], cwd=vault)
    assert _git_check(auth_client, tagged["uuid"])["state"] == "OK"
    auth_ctx.git._run(["tag", "-d", "baseline/r1"], cwd=vault)
    missing = _git_check(auth_client, tagged["uuid"])
    assert missing["state"] == "MISSING" and "no longer exists" in missing["warning"]
    assert auth_client.get(f"/api/baselines/{tagged['uuid']}").json()["git_commit_sha"] == original


@requires_git
def test_a_failed_tag_leaves_a_valid_baseline_and_can_be_retried(
    auth_client, auth_ctx, monkeypatch
):
    from creopdm.exceptions import RepositoryError
    from creopdm.services.git_service import GitService

    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)

    def refuse(self, *_args, **_kwargs):
        raise RepositoryError("fatal: unable to write ref")

    with monkeypatch.context() as patch:
        patch.setattr(GitService, "create_tag", refuse)
        created = _create(auth_client, product, "Tag will fail", git_tag="baseline/will-fail")
        assert created.status_code == 201, created.text  # the baseline is not affected
        body = created.json()
        assert body["status"] == "FINALIZED" and body["member_count"] == 3
        assert body["git_commit_sha"] == _head(auth_ctx, product)
        assert body["git_tag_status"] == "FAILED" and "unable to write ref" in body["git_tag_error"]
        assert _git_check(auth_client, body["uuid"])["state"] == "NOT_CREATED"
        # Reconstruction still works: the members come back exactly.
        assert len(_members(auth_client, body["uuid"])) == 3

    # The repository is healthy again: retry creates the tag on the stored commit.
    retried = auth_client.post(f"/api/baselines/{body['uuid']}/git-tag")
    assert retried.status_code == 200, retried.text
    assert retried.json()["git_tag_status"] == "CREATED" and retried.json()["git_tag_error"] is None
    assert _tag_target(auth_ctx, product, "baseline/will-fail") == body["git_commit_sha"]
    assert _git_check(auth_client, body["uuid"])["state"] == "OK"
    # Retrying a finished tag changes nothing.
    again = auth_client.post(f"/api/baselines/{body['uuid']}/git-tag")
    assert again.status_code == 200 and again.json()["git_tag_status"] == "CREATED"


@requires_git
def test_an_existing_tag_elsewhere_is_never_moved(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    old = _head(auth_ctx, product)
    auth_ctx.git._run(["tag", "baseline/taken", old], cwd=_vault(auth_ctx, product))
    _check_in(auth_client, auth_ctx, product, objects["shaft.prt"], b"shaft-v2")

    created = _create(auth_client, product, "Wants taken tag", git_tag="baseline/taken").json()
    assert created["status"] == "FINALIZED"
    assert created["git_tag_status"] == "FAILED" and "never moves a tag" in created["git_tag_error"]
    assert _tag_target(auth_ctx, product, "baseline/taken") == old  # untouched
    retried = auth_client.post(f"/api/baselines/{created['uuid']}/git-tag").json()
    assert retried["git_tag_status"] == "FAILED"
    assert _tag_target(auth_ctx, product, "baseline/taken") == old


def test_tag_retry_needs_a_tag_and_the_create_permission(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    plain = _create(auth_client, product, "No tag").json()
    refused = auth_client.post(f"/api/baselines/{plain['uuid']}/git-tag")
    assert 400 <= refused.status_code < 500, refused.text

    _login(auth_client, "view", "ViewPass1")
    assert auth_client.get(f"/api/baselines/{plain['uuid']}/git-check").status_code == 200
    assert auth_client.post(f"/api/baselines/{plain['uuid']}/git-tag").status_code == 403


@requires_git
def test_the_tag_name_is_frozen_but_its_status_is_bookkeeping(auth_client, auth_ctx):
    from creopdm.exceptions import BaselineImmutableError

    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    created = _create(auth_client, product, "Tagged", git_tag="baseline/frozen").json()
    with auth_ctx.session_factory() as db:
        baseline = _baseline_row(db, created["uuid"])
        baseline.git_tag_name = "baseline/other"
        with pytest.raises(BaselineImmutableError):
            db.flush()
        db.rollback()
        baseline = _baseline_row(db, created["uuid"])
        baseline.git_tag_status = "FAILED"
        db.commit()


def test_git_tag_ui_is_wired():
    module = (ROOT / "src" / "creopdm" / "static" / "js" / "baselines.js").read_text(encoding="utf-8")
    assert "git_tag:" in module and "/git-check`" in module and "/git-tag`" in module
    assert "function renderTag" in module and "function suggestTag" in module
    # The suggested tag follows the name until the user types their own.
    assert "let tagEdited = false" in module and '$("#baseline-name")?.addEventListener("input"' in module
    template = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    for needle in (
        'id="baseline-tag-on"',
        'id="baseline-tag"',
        'id="baseline-tag-retry"',
        'id="baseline-tag-warning"',
    ):
        assert needle in template


# ---- Stories 17-20: list, detail, exact members, exact historical version ---------------------


def test_the_baseline_list_shows_the_required_columns_newest_first(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    _create(auth_client, product, "Design Review 01")
    _create(auth_client, product, "GEARBOX-R1", baseline_type="RELEASE")

    listed = auth_client.get(f"/api/products/{product['uuid']}/baselines").json()
    assert [row["name"] for row in listed] == ["GEARBOX-R1", "Design Review 01"]  # newest first
    first = listed[0]
    assert first["baseline_type"] == "RELEASE" and first["status"] == "FINALIZED"
    assert first["member_count"] == 3 and first["created_by"] == "admin"
    assert first["created_at"]
    assert listed[1]["baseline_type"] == "MANUAL"

    template = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    header = template[template.index('id="baselines-table"') :]
    header = header[: header.index("</thead>")]
    for column in ("Name", "Type", "Status", "Members", "Created", "Created by"):
        assert f"<th>{column}</th>" in header


def test_the_baseline_detail_shows_its_facts(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client, "Gearbox")
    created = _create(
        auth_client, product, "Design Review 01", description="October design review"
    ).json()
    detail = auth_client.get(f"/api/baselines/{created['uuid']}").json()
    assert detail["name"] == "Design Review 01"
    assert detail["description"] == "October design review"
    assert detail["status"] == "FINALIZED" and detail["baseline_type"] == "MANUAL"
    assert detail["product_uuid"] == product["uuid"] and detail["product_name"] == "Gearbox"
    assert detail["created_by"] == "admin" and detail["created_at"]
    assert detail["member_count"] == 3
    assert "git_commit_sha" in detail and "git_tag_name" in detail  # the advanced facts

    module = (ROOT / "src" / "creopdm" / "static" / "js" / "baselines.js").read_text(encoding="utf-8")
    assert "info.product_name" in module and "baseline-members-desc" in module
    template = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    assert 'id="baseline-members-desc"' in template


@requires_git
def test_a_member_opens_the_exact_version_even_when_the_file_moved_on(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    shaft = objects["shaft.prt"]
    _check_in(auth_client, auth_ctx, product, shaft, b"shaft-v2")  # shaft A.2
    created = _create(auth_client, product).json()
    member = _members(auth_client, created["uuid"])["shaft.prt"]
    assert member["display_version"] == "A.2"
    _check_in(auth_client, auth_ctx, product, shaft, b"shaft-v3")  # now A.3

    url = f"/products/{product['uuid']}/objects/{member['object_uuid']}/versions/{member['version_uuid']}"
    page = auth_client.get(url)
    assert page.status_code == 200, page.text
    html = page.text
    # The page is for A.2, labelled historical, and points at the current A.3 without redirecting.
    assert "A.2" in html and "Historical version" in html and "<strong>A.3</strong>" in html
    assert f"/products/{product['uuid']}/objects/{shaft['uuid']}" in html
    assert 'id="version-facts"' in html and "In Work" in html
    with auth_ctx.session_factory() as db:
        version = db.scalar(select(ObjectVersion).where(ObjectVersion.uuid == member["version_uuid"]))
        assert version.content_hash in html and (version.revision, version.iteration) == ("A", 2)

    # The current version's page says so. (Re-read the member: the earlier read predates A.3.)
    latest = _members(auth_client, created["uuid"])["shaft.prt"]
    assert latest["current_display_version"] == "A.3"
    current = auth_client.get(
        f"/products/{product['uuid']}/objects/{shaft['uuid']}/versions/{latest['current_version_uuid']}"
    )
    assert current.status_code == 200 and "<strong>current</strong>" in current.text


@requires_git
def test_an_exact_version_page_refuses_a_version_of_another_file_or_product(
    auth_client, auth_ctx
):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    other, _o = _product(auth_client, "Other", ("bracket.prt",))
    created = _create(auth_client, product).json()
    members = _members(auth_client, created["uuid"])
    shaft, housing = members["shaft.prt"], members["housing.prt"]
    base = f"/products/{product['uuid']}/objects"

    # A version uuid that belongs to a different file, a made-up one, and the wrong product.
    assert auth_client.get(f"{base}/{shaft['object_uuid']}/versions/{housing['version_uuid']}").status_code == 404
    assert auth_client.get(f"{base}/{shaft['object_uuid']}/versions/not-a-version").status_code == 404
    wrong_product = f"/products/{other['uuid']}/objects/{shaft['object_uuid']}/versions/{shaft['version_uuid']}"
    assert auth_client.get(wrong_product).status_code == 404


def test_baseline_member_rows_link_to_the_exact_version():
    module = (ROOT / "src" / "creopdm" / "static" / "js" / "baselines.js").read_text(encoding="utf-8")
    assert "function versionLink" in module and "/versions/${encodeURIComponent(m.version_uuid)}" in module
    assert "baseline-version-link" in module
    template = (ROOT / "src" / "creopdm" / "templates" / "object_version.html").read_text(encoding="utf-8")
    assert "Historical version" in template and 'id="version-facts"' in template


# ---- Stories 27-30: comparing baselines, in PDM terms -----------------------------------------


def _compare(auth_client, baseline_uuid, to="current"):
    response = auth_client.get(f"/api/baselines/{baseline_uuid}/compare", params={"to": to})
    assert response.status_code == 200, response.text
    body = response.json()
    return body, {row["filename"]: row for row in body["items"]}


def _add_file(auth_client, product, filename, payload=b"new-file-v1"):
    added = auth_client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": (filename, payload, "application/octet-stream")},
        data={"comment": "Add"},
    )
    assert added.status_code == 201, added.text
    return added.json()


@requires_git
def test_two_baselines_are_compared_as_added_removed_changed_and_unchanged(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    first = _create(auth_client, product, "Base").json()
    _check_in(auth_client, auth_ctx, product, objects["shaft.prt"], b"shaft-v2")
    _add_file(auth_client, product, "bracket.prt")
    second = _create(auth_client, product, "Later").json()

    body, rows = _compare(auth_client, first["uuid"], second["uuid"])
    assert body["summary"] == {"changed": 1, "added": 1, "removed": 0, "unchanged": 2}
    assert rows["shaft.prt"]["status"] == "VERSION_CHANGED"
    assert (rows["shaft.prt"]["from_version"], rows["shaft.prt"]["to_version"]) == ("A.1", "A.2")
    assert rows["bracket.prt"]["status"] == "ADDED"
    assert (rows["bracket.prt"]["from_version"], rows["bracket.prt"]["to_version"]) == (None, "A.1")
    assert rows["housing.prt"]["status"] == "UNCHANGED" and rows["gear.prt"]["status"] == "UNCHANGED"
    assert body["from_baseline"]["name"] == "Base" and body["to_baseline"]["name"] == "Later"
    # Changed first, then added, removed, unchanged.
    assert [r["status"] for r in body["items"]] == [
        "VERSION_CHANGED", "ADDED", "UNCHANGED", "UNCHANGED"
    ]

    # The other way round: what the later baseline has that the earlier does not is REMOVED.
    back, back_rows = _compare(auth_client, second["uuid"], first["uuid"])
    assert back["summary"] == {"changed": 1, "added": 0, "removed": 1, "unchanged": 2}
    assert back_rows["bracket.prt"]["status"] == "REMOVED"
    assert (back_rows["shaft.prt"]["from_version"], back_rows["shaft.prt"]["to_version"]) == ("A.2", "A.1")

    same, same_rows = _compare(auth_client, first["uuid"], first["uuid"])
    assert same["summary"]["unchanged"] == 3 and {r["status"] for r in same_rows.values()} == {"UNCHANGED"}


@requires_git
def test_a_baseline_is_compared_with_the_current_configuration(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    base = _create(auth_client, product, "Base").json()

    body, rows = _compare(auth_client, base["uuid"])  # default target: current
    assert body["to_baseline"]["kind"] == "CURRENT"
    assert body["summary"] == {"changed": 0, "added": 0, "removed": 0, "unchanged": 3}

    _check_in(auth_client, auth_ctx, product, objects["shaft.prt"], b"shaft-v2")
    _check_in(auth_client, auth_ctx, product, objects["housing.prt"], b"housing-v2")
    _add_file(auth_client, product, "bracket.prt")
    body, rows = _compare(auth_client, base["uuid"], "current")
    assert body["summary"] == {"changed": 2, "added": 1, "removed": 0, "unchanged": 1}
    assert rows["shaft.prt"]["status"] == "VERSION_CHANGED" and rows["shaft.prt"]["to_version"] == "A.2"
    assert rows["bracket.prt"]["status"] == "ADDED" and rows["gear.prt"]["status"] == "UNCHANGED"

    # Comparing changes nothing: the baseline still holds exactly what it captured.
    assert {m["display_version"] for m in _members(auth_client, base["uuid"]).values()} == {"A.1"}


@requires_git
def test_a_review_baseline_is_compared_with_a_release_baseline(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    review = _create(auth_client, product, "Review").json()
    _check_in(auth_client, auth_ctx, product, objects["gear.prt"], b"gear-v2")
    release = _create(auth_client, product, "R1", baseline_type="RELEASE").json()

    body, rows = _compare(auth_client, review["uuid"], release["uuid"])
    assert body["to_baseline"]["baseline_type"] == "RELEASE"
    assert body["summary"]["changed"] == 1 and rows["gear.prt"]["status"] == "VERSION_CHANGED"


@requires_git
def test_the_result_is_in_pdm_versions_with_commits_only_as_supplemental_info(
    auth_client, auth_ctx
):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    first = _create(auth_client, product, "Base").json()
    _check_in(auth_client, auth_ctx, product, objects["shaft.prt"], b"shaft-v2")
    second = _create(auth_client, product, "Later").json()
    body, rows = _compare(auth_client, first["uuid"], second["uuid"])
    # Reported as "A.1 -> A.2" of the exact versions, never as a raw Git change.
    assert rows["shaft.prt"]["from_version_uuid"] != rows["shaft.prt"]["to_version_uuid"]
    assert (rows["shaft.prt"]["from_version"], rows["shaft.prt"]["to_version"]) == ("A.1", "A.2")
    assert body["from_baseline"]["git_commit_sha"] == first["git_commit_sha"]
    assert body["to_baseline"]["git_commit_sha"] == second["git_commit_sha"]
    assert body["from_baseline"]["git_commit_sha"] != body["to_baseline"]["git_commit_sha"]


def test_compare_refuses_other_products_and_unknown_baselines(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    other, _o = _product(auth_client, "Other", ("bracket.prt",))
    mine = _create(auth_client, product, "Mine").json()
    theirs = _create(auth_client, other, "Theirs").json()
    refused = auth_client.get(f"/api/baselines/{mine['uuid']}/compare", params={"to": theirs["uuid"]})
    assert refused.status_code in (400, 422), refused.text
    unknown = auth_client.get(
        f"/api/baselines/{mine['uuid']}/compare", params={"to": "00000000-0000-4000-8000-000000000000"}
    )
    assert unknown.status_code == 404

    _login(auth_client, "view", "ViewPass1")
    assert auth_client.get(f"/api/baselines/{mine['uuid']}/compare").status_code == 200


def test_compare_ui_is_wired():
    module = (ROOT / "src" / "creopdm" / "static" / "js" / "baselines.js").read_text(encoding="utf-8")
    assert "/compare?to=" in module and "function runCompare" in module and "function renderCompare" in module
    assert "VERSION_CHANGED" in module and "baseline-compare-unchanged" in module
    template = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    for needle in ('data-baseline-view="compare"', 'id="baseline-compare-to"', 'id="baseline-compare-table"'):
        assert needle in template


# ---- Stories 21-25 (server half): exact manifest, exact content, explicit failure --------------


def _manifest_of(auth_client, baseline_uuid):
    response = auth_client.get(f"/api/baselines/{baseline_uuid}/workspace-manifest")
    assert response.status_code == 200, response.text
    return response.json()


@requires_git
def test_the_workspace_manifest_lists_exact_versions_with_hashes(auth_client, auth_ctx):
    import hashlib

    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    created = _create(auth_client, product).json()
    manifest = _manifest_of(auth_client, created["uuid"])

    assert manifest["baseline"]["uuid"] == created["uuid"] and manifest["read_only"] is True
    assert manifest["folder"] == created["workspace_folder"]
    assert manifest["folder"].endswith(created["uuid"][:8]) and "Design_Review_01" in manifest["folder"]
    assert manifest["product"]["uuid"] == product["uuid"]
    members = _members(auth_client, created["uuid"])
    files = {f["filename"]: f for f in manifest["files"]}
    assert set(files) == {"shaft.prt", "housing.prt", "gear.prt"}
    for name, entry in files.items():
        assert entry["version_uuid"] == members[name]["version_uuid"]  # exact ids, not "latest"
        assert entry["sha256"] == hashlib.sha256(f"{name}-v1".encode()).hexdigest()
        assert entry["size"] == len(f"{name}-v1")
        assert entry["content_path"] == f"/api/baselines/{created['uuid']}/versions/{entry['version_uuid']}/content"


@requires_git
def test_no_latest_substitution_the_baseline_version_is_delivered(auth_client, auth_ctx):
    import hashlib

    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    shaft = objects["shaft.prt"]
    created = _create(auth_client, product).json()  # shaft is A.1 here
    _check_in(auth_client, auth_ctx, product, shaft, b"shaft-NEWER")
    _check_in(auth_client, auth_ctx, product, shaft, b"shaft-NEWEST")

    manifest = _manifest_of(auth_client, created["uuid"])
    entry = next(f for f in manifest["files"] if f["filename"] == "shaft.prt")
    assert entry["display_version"] == "A.1"
    assert entry["sha256"] == hashlib.sha256(b"shaft.prt-v1").hexdigest()

    content = auth_client.get(entry["content_path"])
    assert content.status_code == 200, content.text
    assert content.content == b"shaft.prt-v1"  # the captured bytes, not the current ones
    assert content.headers["x-content-sha256"] == entry["sha256"]
    assert content.headers["cache-control"] == "no-store"

    # A newer version of the same file is not part of this baseline and is never served by it.
    with auth_ctx.session_factory() as db:
        newest = db.scalar(
            select(EngineeringObject).where(EngineeringObject.uuid == shaft["uuid"])
        ).current_version
        newest_uuid = newest.uuid
    refused = auth_client.get(f"/api/baselines/{created['uuid']}/versions/{newest_uuid}/content")
    assert refused.status_code == 404, refused.text


@requires_git
def test_missing_exact_content_fails_the_reconstruction_and_names_the_member(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    created = _create(auth_client, product).json()
    before = _members(auth_client, created["uuid"])
    # The captured shaft version loses its content in the vault; its object also has a newer one.
    _check_in(auth_client, auth_ctx, product, objects["shaft.prt"], b"shaft-NEWER")
    with auth_ctx.session_factory() as db:
        version = db.scalar(select(ObjectVersion).where(ObjectVersion.uuid == before["shaft.prt"]["version_uuid"]))
        version.git_commit_hash = "0" * 40
        db.commit()

    refused = auth_client.get(f"/api/baselines/{created['uuid']}/workspace-manifest")
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "BASELINE_RECONSTRUCTION_FAILED"
    assert "shaft.prt A.1" in error["message"] and "No other version is substituted" in error["message"]
    assert [p["file"] for p in error["details"]["problems"]] == ["shaft.prt"]
    content = auth_client.get(f"/api/baselines/{created['uuid']}/versions/{before['shaft.prt']['version_uuid']}/content")
    assert content.status_code == 409 and content.json()["error"]["code"] == "BASELINE_RECONSTRUCTION_FAILED"

    # The baseline itself is unchanged: same members, same version ids.
    after = _members(auth_client, created["uuid"])
    assert {n: m["version_uuid"] for n, m in after.items()} == {n: m["version_uuid"] for n, m in before.items()}


@requires_git
def test_damaged_content_is_never_sent(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    created = _create(auth_client, product).json()
    members = _members(auth_client, created["uuid"])
    with auth_ctx.session_factory() as db:
        version = db.scalar(select(ObjectVersion).where(ObjectVersion.uuid == members["gear.prt"]["version_uuid"]))
        version.content_hash = "f" * 64  # the record no longer matches the stored bytes
        db.commit()
    url = f"/api/baselines/{created['uuid']}/versions/{members['gear.prt']['version_uuid']}/content"
    refused = auth_client.get(url)
    assert refused.status_code == 409, refused.text
    assert "damaged" in refused.json()["error"]["message"] and not refused.content.startswith(b"gear")


def test_workspace_manifest_needs_the_view_permission_and_exists_for_viewers(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    created = _create(auth_client, product).json()
    _login(auth_client, "view", "ViewPass1")
    assert auth_client.get(f"/api/baselines/{created['uuid']}/workspace-manifest").status_code == 200
    for method in ("post", "put", "delete"):
        response = auth_client.request(method.upper(), f"/api/baselines/{created['uuid']}/workspace-manifest")
        assert response.status_code in (404, 405)


def test_workspace_ui_is_wired():
    module = (ROOT / "src" / "creopdm" / "static" / "js" / "baselines.js").read_text(encoding="utf-8")
    assert "/workspace-manifest`" in module and "/baseline-workspace" in module
    assert "async function openAddToWorkspace" in module and "async function removeFromWorkspace" in module
    assert "canSetCreoWorkingDirectory" in module and "setCreoWorkingDirectory" in module
    assert "folder_locked" in module  # the user is told whether Creo can still save into the folder
    template = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    for needle in (
        'id="baseline-ws-add"',
        'id="baseline-ws-remove"',
        'id="baseline-workspace-dialog"',
        'id="baseline-ws-wd"',
    ):
        assert needle in template
    app_js = (ROOT / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "options && options.directory" in app_js and "canSetCreoWorkingDirectory" in app_js
