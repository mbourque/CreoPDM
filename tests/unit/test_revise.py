"""Revise Story 1: Release touches the files, and Revise is offered only where it can work."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.auth_constants import (
    BUILTIN_PERMISSIONS,
    PERMISSION_OBJECTS_REVISE,
    STARTER_ROLE_PERMISSION_KEYS,
    BuiltinRole,
)
from creopdm.config import ConfigManager
from creopdm.exceptions import ReviseInvalidLifecycleError, ReviseRevisionSchemeError
from creopdm.lifecycle_policy import default_lifecycle_policy, policy_from_dicts
from creopdm.services.revise_service import ensure_can_revise, evaluate_revise
from creopdm.utils.revision_scheme import get_initial_revision, get_next_revision, validate_revision
from tests.conftest import requires_git
from tests.unit.test_auth import _login, _setup_admin_and_users


# ---- pure rules -------------------------------------------------------------------------


def test_revise_permission_is_seeded_for_authoring_roles_only():
    assert PERMISSION_OBJECTS_REVISE in {key for key, _ in BUILTIN_PERMISSIONS}
    for role in (BuiltinRole.ADMINISTRATOR, BuiltinRole.PDM_MANAGER, BuiltinRole.ENGINEER):
        assert PERMISSION_OBJECTS_REVISE in STARTER_ROLE_PERMISSION_KEYS[role.value]
    assert PERMISSION_OBJECTS_REVISE not in STARTER_ROLE_PERMISSION_KEYS[BuiltinRole.VIEWER.value]


def test_matrix_revise_defaults_follow_editable_states_and_survive_old_settings():
    policy = default_lifecycle_policy()
    for editable in ("IN_WORK", "UNDER_CHANGE"):
        assert policy.allows(editable, "revise"), editable
    # Pre-Work is editable but nothing there should need a new revision: off by default.
    assert policy.allows("PRE_WORK", "checkout") and not policy.allows("PRE_WORK", "revise")
    for frozen in ("IN_REVIEW", "APPROVED", "RELEASED", "OBSOLETE", "ARCHIVED", "LOCKED"):
        assert not policy.allows(frozen, "revise"), frozen
    # Settings saved before the column existed carry no "revise" key: defaults still apply.
    old = policy_from_dicts(
        [
            {"key": "RELEASED", "permissions": {"checkout": False}},
            {"key": "UNDER_CHANGE", "permissions": {"checkout": True}},
        ]
    )
    assert old.allows("UNDER_CHANGE", "revise")
    assert not old.allows("RELEASED", "revise")


def _obj(lifecycle="RELEASED", state="UNDER_CHANGE", filename="shaft.prt"):
    product = SimpleNamespace(name="Gearbox", uuid="p-1", state=state)
    return SimpleNamespace(
        filename=filename, lifecycle_state=lifecycle, product=product, uuid="o-1"
    )


def test_evaluate_revise_rules_in_order():
    ok = evaluate_revise(_obj(), None)
    assert ok.allowed and not ok.code

    archived = evaluate_revise(_obj(state="ARCHIVED"), None)
    assert (archived.allowed, archived.code) == (False, "REVISE_NOT_ALLOWED")

    frozen = evaluate_revise(_obj(state="RELEASED"), None)
    assert (frozen.allowed, frozen.code) == (False, "REVISE_NOT_ALLOWED")
    assert "Released" in frozen.message

    held = evaluate_revise(_obj(), SimpleNamespace(user_name="Bob"))
    assert (held.allowed, held.code) == (False, "REVISE_ACTIVE_CHECKOUT")
    assert "Bob" in held.message

    in_work = evaluate_revise(_obj(lifecycle="IN_WORK"), None)
    assert (in_work.allowed, in_work.code) == (False, "REVISE_INVALID_LIFECYCLE")

    # The list flag ignores the product matrix (that is product_ui.show_revise's job).
    assert evaluate_revise(_obj(state="RELEASED"), None, check_product=False).allowed


def test_ensure_can_revise_raises_the_matching_code():
    with pytest.raises(ReviseInvalidLifecycleError) as err:
        ensure_can_revise(_obj(lifecycle="IN_WORK"), None)
    assert err.value.code == "REVISE_INVALID_LIFECYCLE"
    ensure_can_revise(_obj(), None)  # allowed: no raise


def test_revision_scheme_is_alphabetic_and_server_side():
    assert get_initial_revision() == "A"
    assert [get_next_revision(r) for r in ("A", "B", "Y")] == ["B", "C", "Z"]
    assert get_next_revision("Z") == "AA"
    assert get_next_revision("AZ") == "BA"
    assert get_next_revision("ZZ") == "AAA"
    for bad in ("", None, "b", "1", "A1", " "):
        with pytest.raises(ReviseRevisionSchemeError):
            validate_revision(bad)
    with pytest.raises(ReviseRevisionSchemeError) as err:
        get_next_revision("1")
    assert err.value.code == "REVISE_REVISION_SCHEME_ERROR"


# ---- release cascade + eligibility API --------------------------------------------------


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _make_product_with_file(auth_client, name="Gearbox", filename="shaft.prt"):
    created = auth_client.post(
        "/api/products", json={"name": name, "number": "GB-1"}
    )
    assert created.status_code == 201, created.text
    product = created.json()
    added = auth_client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": (filename, b"bytes", "application/octet-stream")},
        data={"comment": "Initial model"},
    )
    assert added.status_code == 201, added.text
    return product, added.json()


def _promote(auth_client, product, state):
    """Promote Products page (the real path). Returns the response: 200 saved, 400 refused."""
    return auth_client.post(
        "/admin/products/promote",
        data={"product_id": product["uuid"], "state": state, "confirm_password": "AdminPass1"},
    )


def _eligibility(auth_client, obj):
    response = auth_client.get(f"/api/objects/{obj['uuid']}/revise-eligibility")
    assert response.status_code == 200, response.text
    return response.json()


@requires_git
def test_release_releases_files_and_revise_follows_the_object(auth_client, auth_ctx):
    _setup_admin_and_users(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    product, obj = _make_product_with_file(auth_client)

    # In an editable product an IN_WORK file is not revisable (nothing released yet).
    body = _eligibility(auth_client, obj)
    assert (body["allowed"], body["code"]) == (False, "REVISE_INVALID_LIFECYCLE")

    # A checked-out file blocks Revise, and Release is refused until the checkout is gone
    # (a Released product blocks check-in and undo, so it would be stranded).
    out = auth_client.post(f"/api/objects/{obj['uuid']}/checkout")
    assert out.status_code == 200, out.text
    held = _eligibility(auth_client, obj)
    assert (held["allowed"], held["code"]) == (False, "REVISE_ACTIVE_CHECKOUT")
    blocked = _promote(auth_client, product, "RELEASED")
    assert blocked.status_code == 400, blocked.text
    assert "shaft.prt" in blocked.text and "checked out" in blocked.text
    still = auth_client.get(f"/api/objects/{obj['uuid']}").json()
    assert still["lifecycle_state"] == "IN_WORK" and still["owned_by_me"] is True
    undone = auth_client.post(f"/api/objects/{obj['uuid']}/undo-checkout")
    assert undone.status_code == 200, undone.text

    # Releasing the product releases its files...
    saved = _promote(auth_client, product, "RELEASED")
    assert saved.status_code == 200, saved.text
    released = auth_client.get(f"/api/objects/{obj['uuid']}").json()
    assert released["lifecycle_state"] == "RELEASED"
    assert released["can_checkout"] is False
    # ...but a Released product is frozen: Revise is refused until it is reopened.
    frozen = _eligibility(auth_client, obj)
    assert (frozen["allowed"], frozen["code"]) == (False, "REVISE_NOT_ALLOWED")

    # Reopened (Under change): the file stays Released and can now be revised.
    assert _promote(auth_client, product, "UNDER_CHANGE").status_code == 200
    reopened = auth_client.get(f"/api/objects/{obj['uuid']}").json()
    assert reopened["lifecycle_state"] == "RELEASED"
    assert reopened["can_revise"] is True
    ok = _eligibility(auth_client, obj)
    assert ok["allowed"] is True
    assert ok["display_version"] == f"{obj['revision']}.{obj['iteration']}"


@requires_git
def test_revise_eligibility_needs_the_permission_server_side(auth_client, auth_ctx):
    _setup_admin_and_users(
        auth_client,
        auth_ctx,
        ("eng", BuiltinRole.ENGINEER.value),
        ("view", BuiltinRole.VIEWER.value),
    )
    _login(auth_client, "admin", "AdminPass1")
    _product, obj = _make_product_with_file(auth_client)

    _login(auth_client, "view", "ViewPass1")
    denied = auth_client.get(f"/api/objects/{obj['uuid']}/revise-eligibility")
    assert denied.status_code == 403, denied.text

    _login(auth_client, "eng", "EngPass1")
    allowed = auth_client.get(f"/api/objects/{obj['uuid']}/revise-eligibility")
    assert allowed.status_code == 200, allowed.text


def test_revise_ui_is_wired_through_the_shared_menu_and_details():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "creopdm"
    menu = (root / "static" / "js" / "files_context_menu.js").read_text(encoding="utf-8")
    assert 'action: "revise"' in menu and "canRevise" in menu
    app = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "canRevise: row.dataset.canRevise" in app
    assert 'action === "revise"' in app
    assert "/revise-preview" in app and "openReviseDialog" in app
    base = (root / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'id="revise-dialog"' in base and 'id="revise-confirm"' in base
    assert 'id="revise-reason"' in base and "Revision Reason" in base
    # Revise and Check Out: opt-in checkbox, done as a second step through the Files deep link.
    assert 'id="revise-checkout"' in base
    assert 'q.set("action", "checkout")' in app and "checkoutAfter" in app
    assert "operationId" in app and "crypto.randomUUID" in app
    assert "/revise`" in app and "JSON.stringify({ reason, operation_id: operationId })" in app
    assert "Starting Iteration" in base and "New Lifecycle" in base
    files = (root / "templates" / "app.html").read_text(encoding="utf-8")
    assert "product_ui.show_revise and obj.can_revise" in files
    assert 'data-show-revise="{{ ' in files and "product_ui.show_revise else" in files
    # Search / soft-refresh rows are built in JS and must carry the same flag.
    assert 'data-can-revise="${' in app and "dataset.showRevise" in app
    detail = (root / "templates" / "object_detail.html").read_text(encoding="utf-8")
    assert "product_ui.show_revise and object.can_revise" in detail
    assert 'id="revise-btn"' in detail
    # /static is cached by URL: changing the menu script needs a new ?v= token or browsers keep
    # the old menu (Revise… silently missing even though the row flags are right).
    for name in ("base.html", "embed_explorer.html"):
        page = (root / "templates" / name).read_text(encoding="utf-8")
        assert "files_context_menu.js?v={{ app_version }}-files-ctx-nonopen" in page, name
    nav = (root / "static" / "js" / "embed_explorer.js").read_text(encoding="utf-8")
    assert "canRevise: showRevise && Boolean(obj.can_revise)" in nav


@requires_git
def test_revise_preview_is_calculated_by_the_server_and_creates_nothing(auth_client, auth_ctx):
    _setup_admin_and_users(auth_client, auth_ctx, ("view", BuiltinRole.VIEWER.value))
    _login(auth_client, "admin", "AdminPass1")
    product, obj = _make_product_with_file(auth_client)

    # Not Released yet: the preview refuses and names why, with no new revision.
    early = auth_client.get(f"/api/objects/{obj['uuid']}/revise-preview")
    assert early.status_code == 200, early.text
    body = early.json()
    assert (body["allowed"], body["code"]) == (False, "REVISE_INVALID_LIFECYCLE")
    assert body["new_revision"] == "" and body["new_display_version"] == ""

    assert _promote(auth_client, product, "RELEASED").status_code == 200
    assert _promote(auth_client, product, "UNDER_CHANGE").status_code == 200

    versions_before = auth_client.get(f"/api/objects/{obj['uuid']}/history").json()
    preview = auth_client.get(f"/api/objects/{obj['uuid']}/revise-preview")
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["allowed"] is True
    assert data["source_display_version"] == "A.1"
    assert data["source_lifecycle_state"] == "RELEASED"
    assert data["new_revision"] == "B"
    assert data["new_iteration"] == 1
    assert data["new_display_version"] == "B.1"
    assert data["new_lifecycle_state"] == "IN_WORK"
    assert data["source_version_id"] == obj["current_version"]["uuid"]
    assert data["name"] and data["filename"] == obj["filename"]

    # The client cannot choose the revision: query parameters are ignored.
    forced = auth_client.get(f"/api/objects/{obj['uuid']}/revise-preview?revision=D")
    assert forced.json()["new_revision"] == "B"

    # Previewing creates nothing: same history, same object revision/lifecycle.
    assert auth_client.get(f"/api/objects/{obj['uuid']}/history").json() == versions_before
    after = auth_client.get(f"/api/objects/{obj['uuid']}").json()
    assert (after["revision"], after["iteration"], after["lifecycle_state"]) == ("A", 1, "RELEASED")

    # Permission is enforced server-side on the preview too.
    _login(auth_client, "view", "ViewPass1")
    assert auth_client.get(f"/api/objects/{obj['uuid']}/revise-preview").status_code == 403


@requires_git
def test_revise_preview_refuses_when_the_next_revision_already_exists(auth_client, auth_ctx):
    from sqlalchemy import select

    from creopdm.models.object import EngineeringObject
    from creopdm.models.version import ObjectVersion

    _setup_admin_and_users(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    product, obj = _make_product_with_file(auth_client)
    assert _promote(auth_client, product, "RELEASED").status_code == 200
    assert _promote(auth_client, product, "UNDER_CHANGE").status_code == 200

    with auth_ctx.session_factory() as db:
        row = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == obj["uuid"]))
        src = row.current_version
        db.add(
            ObjectVersion(
                uuid="ver-existing-b",
                object_id=row.id,
                revision="B",
                iteration=1,
                content_hash=src.content_hash,
                created_by="test",
                comment="pre-existing B",
            )
        )
        db.commit()

    data = auth_client.get(f"/api/objects/{obj['uuid']}/revise-preview").json()
    assert (data["allowed"], data["code"]) == (False, "REVISE_NEXT_REVISION_EXISTS")
    assert data["new_revision"] == ""


# ---- Revise creates B.1 -----------------------------------------------------------------


def _released_under_change(auth_client, auth_ctx, name="Gearbox", filename="shaft.prt"):
    """Admin signed in; a product with one file, Released then reopened as Under Change."""
    _setup_admin_and_users(auth_client, auth_ctx, ("view", BuiltinRole.VIEWER.value))
    _login(auth_client, "admin", "AdminPass1")
    product, obj = _make_product_with_file(auth_client, name, filename)
    assert _promote(auth_client, product, "RELEASED").status_code == 200
    assert _promote(auth_client, product, "UNDER_CHANGE").status_code == 200
    return product, obj


def _vault_dir(auth_ctx, product):
    from pathlib import Path

    return Path(auth_ctx.config.workspace_root()) / product["vault_folder"]


def _versions(auth_ctx, object_uuid):
    from sqlalchemy import select

    from creopdm.models.object import EngineeringObject
    from creopdm.models.version import ObjectVersion

    with auth_ctx.session_factory() as db:
        row = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == object_uuid))
        rows = list(
            db.scalars(
                select(ObjectVersion)
                .where(ObjectVersion.object_id == row.id)
                .order_by(ObjectVersion.id)
            )
        )
        return row.id, [
            {
                "uuid": v.uuid,
                "revision": v.revision,
                "iteration": v.iteration,
                "lifecycle": v.lifecycle_state,
                "content_hash": v.content_hash,
                "git": v.git_commit_hash,
                "created_from": v.created_from_version_id,
                "reason": v.revision_reason,
                "id": v.id,
                "identity_json": v.identity_json,
                "bom_json": v.bom_json,
                "comment": v.comment,
            }
            for v in rows
        ]


@requires_git
def test_revise_creates_b1_and_keeps_a1_untouched(auth_client, auth_ctx):
    from sqlalchemy import select

    from creopdm.models.ai_snapshot import ObjectVersionSnapshot
    from creopdm.models.dependency import Dependency
    from creopdm.models.object import EngineeringObject
    from creopdm.models.parameter import Parameter

    product, obj = _released_under_change(auth_client, auth_ctx)
    vault = _vault_dir(auth_ctx, product)
    with auth_ctx.session_factory() as db:
        row = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == obj["uuid"]))
        src = row.current_version
        src.identity_json = '{"material":"4140"}'
        src.bom_json = '[{"filename":"a.prt"}]'
        db.add(
            Parameter(
                object_id=row.id,
                version_id=src.id,
                name="DESCRIPTION",
                value="Drive Shaft",
                data_type="STRING",
            )
        )
        db.add(
            ObjectVersionSnapshot(
                uuid="snap-a1",
                object_id=row.id,
                version_id=src.id,
                schema_version=1,
                snapshot_json='{"k":1}',
            )
        )
        db.commit()
        edges_before = len(list(db.scalars(select(Dependency))))
    head_before = auth_ctx.git.get_head(vault)
    object_id, before = _versions(auth_ctx, obj["uuid"])
    assert len(before) == 1

    done = auth_client.post(
        f"/api/objects/{obj['uuid']}/revise",
        json={"reason": "  Bearing   redesign ", "revision": "Z", "iteration": 9},
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["object_id"] == obj["uuid"]  # same object
    assert body["display_version"] == "B.1"  # the server chose B; the client's "Z" was ignored
    assert body["source_display_version"] == "A.1"
    assert body["lifecycle_state"] == "IN_WORK"
    assert body["reason"] == "Bearing redesign"
    assert body["new_version_id"] != body["source_version_id"]
    assert body["source_version_id"] == before[0]["uuid"]

    _object_id, after = _versions(auth_ctx, obj["uuid"])
    assert len(after) == 2
    a1, b1 = after
    # A.1 is untouched: same row, content, state, metadata.
    assert a1["uuid"] == before[0]["uuid"] and a1["revision"] == "A" and a1["iteration"] == 1
    assert a1["lifecycle"] == "RELEASED"
    assert a1["content_hash"] == before[0]["content_hash"] and a1["git"] == before[0]["git"]
    assert a1["identity_json"] == '{"material":"4140"}'
    # B.1: new version of the same object, iteration reset, In Work, provenance + reason.
    assert (b1["revision"], b1["iteration"], b1["lifecycle"]) == ("B", 1, "IN_WORK")
    assert b1["created_from"] == a1["id"]
    assert b1["reason"] == "Bearing redesign"
    assert b1["content_hash"] == a1["content_hash"]  # same bytes, separate PDM version
    assert b1["git"] and b1["git"] != a1["git"]  # its own repository state
    assert b1["identity_json"] == a1["identity_json"] and b1["bom_json"] == a1["bom_json"]
    assert "Bearing redesign" in b1["comment"]

    with auth_ctx.session_factory() as db:
        row = db.get(EngineeringObject, object_id)
        assert (row.revision, row.iteration, row.lifecycle_state) == ("B", 1, "IN_WORK")
        assert row.current_version.uuid == b1["uuid"]
        # Metadata rows are copied, not shared.
        params = list(db.scalars(select(Parameter).where(Parameter.object_id == object_id)))
        assert [p.name for p in params] == ["DESCRIPTION", "DESCRIPTION"]
        assert len({p.version_id for p in params}) == 2
        snaps = list(db.scalars(select(ObjectVersionSnapshot)))
        assert len(snaps) == 2 and len({s.uuid for s in snaps}) == 2
        # Usage edges are not rewritten.
        assert len(list(db.scalars(select(Dependency)))) == edges_before
        # The audit trail records it.
        events = auth_ctx.activities.list_events(db, q="shaft.prt")
        rev = [e for e in events if e.action == "REVISION_CREATED"]
        assert rev and "A.1 → B.1" in (rev[0].summary or "")
        assert (rev[0].details or {}).get("reason") == "Bearing redesign"
    # Git: a new commit exists, the vault bytes are unchanged.
    assert auth_ctx.git.get_head(vault) != head_before
    assert (vault / "shaft.prt").read_bytes() == b"bytes"

    # History lists B.1 first and shows provenance.
    history = auth_client.get(f"/api/objects/{obj['uuid']}/history").json()
    assert [h["display"] for h in history] == ["B.1", "A.1"]
    assert history[0]["created_from_display"] == "A.1"
    assert history[0]["revision_reason"] == "Bearing redesign"
    assert history[0]["lifecycle_state"] == "IN_WORK"
    assert history[1]["lifecycle_state"] == "RELEASED"

    # B.1 can be checked out and checked in as B.2 (Check-In does not change the revision).
    out = auth_client.post(f"/api/objects/{obj['uuid']}/checkout")
    assert out.status_code == 200, out.text
    (vault / "shaft.prt").write_bytes(b"edited-after-revise")
    checked = auth_client.post(
        f"/api/objects/{obj['uuid']}/checkin", json={"comment": "after revise"}
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["display_revision"] == "B.2"

    detail = auth_client.get(f"/products/{product['uuid']}/objects/{obj['uuid']}")
    assert detail.status_code == 200
    # B.2 is current now; Overview still shows where revision B came from and why.
    # History is grouped by revision, newest first, with the Released version labelled.
    text = detail.text
    assert text.count('class="revision-group-row"') == 2
    assert text.index("Revision B</th>") < text.index("Revision A</th>")
    assert "A.1 · Released" in text
    assert 'id="overview-created-from"' in detail.text
    assert 'id="overview-revision-reason"' in detail.text
    assert "Bearing redesign" in detail.text


@requires_git
def test_revise_refusals_create_nothing(auth_client, auth_ctx):
    product, obj = _released_under_change(auth_client, auth_ctx)

    missing = auth_client.post(f"/api/objects/{obj['uuid']}/revise", json={"reason": "  "})
    assert missing.status_code == 400, missing.text
    assert "reason" in missing.json()["error"]["message"].lower()
    long = auth_client.post(f"/api/objects/{obj['uuid']}/revise", json={"reason": "x" * 501})
    assert long.status_code == 400, long.text

    first = auth_client.post(f"/api/objects/{obj['uuid']}/revise", json={"reason": "first"})
    assert first.status_code == 200, first.text
    # B.1 is In Work now: a second Revise has nothing Released to start from.
    again = auth_client.post(f"/api/objects/{obj['uuid']}/revise", json={"reason": "again"})
    assert again.status_code == 409, again.text
    assert again.json()["error"]["code"] == "REVISE_INVALID_LIFECYCLE"
    _oid, versions = _versions(auth_ctx, obj["uuid"])
    assert [(v["revision"], v["iteration"]) for v in versions] == [("A", 1), ("B", 1)]


def _released_with_active_checkout(auth_client, auth_ctx):
    """A Released file that someone still has checked out (a legacy state)."""
    from sqlalchemy import select

    from creopdm.models.checkout import Checkout
    from creopdm.models.object import EngineeringObject

    product, obj = _released_under_change(auth_client, auth_ctx)
    with auth_ctx.session_factory() as db:
        row = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == obj["uuid"]))
        db.add(
            Checkout(
                object_id=row.id,
                user_name="Bob",
                machine_name="PC-1",
                workspace_path="C:/ws",
                status="ACTIVE",
            )
        )
        db.commit()
    return product, obj


@requires_git
def test_revise_is_refused_while_checked_out_and_without_permission(auth_client, auth_ctx):
    _product, obj = _released_with_active_checkout(auth_client, auth_ctx)
    blocked = auth_client.post(f"/api/objects/{obj['uuid']}/revise", json={"reason": "r"})
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["error"]["code"] == "REVISE_ACTIVE_CHECKOUT"
    assert "Bob" in blocked.json()["error"]["message"]
    _oid, versions = _versions(auth_ctx, obj["uuid"])
    assert len(versions) == 1

    _login(auth_client, "view", "ViewPass1")
    denied = auth_client.post(f"/api/objects/{obj['uuid']}/revise", json={"reason": "r"})
    assert denied.status_code == 403, denied.text


@requires_git
def test_failed_revise_leaves_everything_as_it_was(auth_client, auth_ctx, monkeypatch):
    product, obj = _released_under_change(auth_client, auth_ctx)
    vault = _vault_dir(auth_ctx, product)
    head = auth_ctx.git.get_head(vault)
    service = auth_ctx.revisions

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated failure")

    # Git step fails: nothing recorded.
    monkeypatch.setattr(service._store, "store_version", boom)
    failed = auth_client.post(f"/api/objects/{obj['uuid']}/revise", json={"reason": "r"})
    assert failed.status_code >= 400
    monkeypatch.undo()
    _oid, versions = _versions(auth_ctx, obj["uuid"])
    assert len(versions) == 1
    assert auth_ctx.git.get_head(vault) == head

    # Database step fails after Git committed: the Git state is rolled back too.
    monkeypatch.setattr(type(service), "_copy_metadata", staticmethod(boom))
    failed = auth_client.post(f"/api/objects/{obj['uuid']}/revise", json={"reason": "r"})
    assert failed.status_code >= 400
    monkeypatch.undo()
    _oid, versions = _versions(auth_ctx, obj["uuid"])
    assert len(versions) == 1 and versions[0]["lifecycle"] == "RELEASED"
    assert auth_ctx.git.get_head(vault) == head
    after = auth_client.get(f"/api/objects/{obj['uuid']}").json()
    assert (after["revision"], after["iteration"], after["lifecycle_state"]) == ("A", 1, "RELEASED")

    # And the retry works afterwards.
    ok = auth_client.post(f"/api/objects/{obj['uuid']}/revise", json={"reason": "r"})
    assert ok.status_code == 200, ok.text


# ---- Retry safety (operation id) --------------------------------------------------------


@requires_git
def test_revise_retry_with_same_operation_id_returns_the_original_b1(auth_client, auth_ctx):
    _product, obj = _released_under_change(auth_client, auth_ctx)
    op = "11111111-2222-3333-4444-555555555555"

    first = auth_client.post(
        f"/api/objects/{obj['uuid']}/revise",
        json={"reason": "Bearing redesign", "operation_id": op},
    )
    assert first.status_code == 200, first.text
    assert first.json()["display_version"] == "B.1" and first.json()["replayed"] is False

    # The response was "lost": the client retries. It must get the same B.1, not C.1 or an error.
    retry = auth_client.post(
        f"/api/objects/{obj['uuid']}/revise",
        json={"reason": "Bearing redesign", "operation_id": op},
    )
    assert retry.status_code == 200, retry.text
    again = retry.json()
    assert again["replayed"] is True
    assert again["display_version"] == "B.1"
    assert again["new_version_id"] == first.json()["new_version_id"]
    assert again["source_version_id"] == first.json()["source_version_id"]

    # Even a retry that lost its reason text gets the stored result.
    blank = auth_client.post(
        f"/api/objects/{obj['uuid']}/revise", json={"reason": "", "operation_id": op}
    )
    assert blank.status_code == 200 and blank.json()["new_version_id"] == again["new_version_id"]

    # Nothing extra exists: still A.1 and B.1, one audit entry.
    _oid, versions = _versions(auth_ctx, obj["uuid"])
    assert [(v["revision"], v["iteration"]) for v in versions] == [("A", 1), ("B", 1)]
    with auth_ctx.session_factory() as db:
        events = auth_ctx.activities.list_events(db, q="shaft.prt")
        assert len([e for e in events if e.action == "REVISION_CREATED"]) == 1

    # A different operation id is a different request: nothing Released is left to revise.
    other = auth_client.post(
        f"/api/objects/{obj['uuid']}/revise",
        json={"reason": "again", "operation_id": "99999999-0000-0000-0000-000000000000"},
    )
    assert other.status_code == 409, other.text
    assert other.json()["error"]["code"] == "REVISE_INVALID_LIFECYCLE"


@requires_git
def test_revise_operation_id_cannot_be_reused_for_another_file(auth_client, auth_ctx):
    product, obj = _make_two_file_product(auth_client, auth_ctx)
    op = "aaaaaaaa-0000-0000-0000-000000000001"
    ok = auth_client.post(
        f"/api/objects/{obj['uuid']}/revise", json={"reason": "r", "operation_id": op}
    )
    assert ok.status_code == 200, ok.text
    other_file = auth_client.get(f"/api/products/{product['uuid']}/objects").json()
    other = next(o for o in other_file if o["uuid"] != obj["uuid"])
    clash = auth_client.post(
        f"/api/objects/{other['uuid']}/revise", json={"reason": "r", "operation_id": op}
    )
    assert clash.status_code == 409, clash.text
    assert clash.json()["error"]["code"] == "REVISE_OPERATION_ALREADY_COMPLETED"
    _oid, versions = _versions(auth_ctx, other["uuid"])
    assert len(versions) == 1


def _make_two_file_product(auth_client, auth_ctx):
    _setup_admin_and_users(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    product, obj = _make_product_with_file(auth_client, "Pair", "one.prt")
    added = auth_client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": ("two.prt", b"two-bytes", "application/octet-stream")},
        data={"comment": "second"},
    )
    assert added.status_code == 201, added.text
    assert _promote(auth_client, product, "RELEASED").status_code == 200
    assert _promote(auth_client, product, "UNDER_CHANGE").status_code == 200
    return product, obj


@requires_git
def test_operation_id_is_unique_in_the_database(auth_client, auth_ctx):
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from creopdm.models.object import EngineeringObject
    from creopdm.models.revise_operation import ReviseOperation

    _product, obj = _released_under_change(auth_client, auth_ctx)
    op = "bbbbbbbb-0000-0000-0000-000000000002"
    done = auth_client.post(
        f"/api/objects/{obj['uuid']}/revise", json={"reason": "r", "operation_id": op}
    )
    assert done.status_code == 200, done.text
    with auth_ctx.session_factory() as db:
        row = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == obj["uuid"]))
        existing = db.scalar(select(ReviseOperation).where(ReviseOperation.operation_id == op))
        assert existing is not None and existing.status == "COMPLETED"
        db.add(
            ReviseOperation(
                operation_id=op,
                object_id=row.id,
                source_version_id=existing.source_version_id,
                new_version_id=existing.new_version_id,
                user_name="x",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


# ---- Promote back from Released --------------------------------------------------------


def _promote_with(auth_client, product, state, **extra):
    data = {"product_id": product["uuid"], "state": state, "confirm_password": "AdminPass1"}
    data.update(extra)
    return auth_client.post("/admin/products/promote", data=data)


@requires_git
def test_promote_back_keeps_files_released_unless_asked_to_undo_the_release(
    auth_client, auth_ctx
):
    _setup_admin_and_users(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    product, obj = _make_product_with_file(auth_client)

    assert _promote(auth_client, product, "RELEASED").status_code == 200
    assert auth_client.get(f"/api/objects/{obj['uuid']}").json()["lifecycle_state"] == "RELEASED"

    # Back to In Work without the choice: the file stays Released (needs Revise to edit).
    assert _promote_with(auth_client, product, "IN_WORK").status_code == 200
    kept = auth_client.get(f"/api/objects/{obj['uuid']}").json()
    assert kept["lifecycle_state"] == "RELEASED" and kept["can_checkout"] is False
    assert auth_client.get(f"/api/objects/{obj['uuid']}/revise-eligibility").json()["allowed"] is True

    # The choice is ignored for transitions it does not apply to (-> Under Change).
    assert _promote(auth_client, product, "RELEASED").status_code == 200
    assert _promote_with(auth_client, product, "UNDER_CHANGE", reopen_files="1").status_code == 200
    assert auth_client.get(f"/api/objects/{obj['uuid']}").json()["lifecycle_state"] == "RELEASED"

    # Under Change -> In Work with the choice also undoes the release (Released files in a
    # reopened product are the common case).
    assert _promote_with(auth_client, product, "IN_WORK", reopen_files="1").status_code == 200
    assert auth_client.get(f"/api/objects/{obj['uuid']}").json()["lifecycle_state"] == "IN_WORK"

    # Released -> In Work WITH the choice undoes the release.
    assert _promote(auth_client, product, "RELEASED").status_code == 200
    assert _promote_with(auth_client, product, "IN_WORK", reopen_files="1").status_code == 200
    reopened = auth_client.get(f"/api/objects/{obj['uuid']}").json()
    assert reopened["lifecycle_state"] == "IN_WORK" and reopened["can_checkout"] is True
    _oid, versions = _versions(auth_ctx, obj["uuid"])
    assert versions[-1]["lifecycle"] == "IN_WORK"
    with auth_ctx.session_factory() as db:
        events = auth_ctx.activities.list_events(db, q="Gearbox")
        assert any("set back to In Work" in (e.summary or "") for e in events)


@requires_git
def test_reopen_leaves_earlier_released_revisions_released(auth_client, auth_ctx):
    product, obj = _released_under_change(auth_client, auth_ctx)
    assert (
        auth_client.post(f"/api/objects/{obj['uuid']}/revise", json={"reason": "r"}).status_code
        == 200
    )
    # B.1 is In Work; release again (B.1 becomes Released), then undo that release.
    assert _promote(auth_client, product, "RELEASED").status_code == 200
    assert _promote_with(auth_client, product, "IN_WORK", reopen_files="1").status_code == 200
    _oid, versions = _versions(auth_ctx, obj["uuid"])
    assert [(v["revision"], v["lifecycle"]) for v in versions] == [("A", "RELEASED"), ("B", "IN_WORK")]


def test_promote_page_offers_the_undo_release_choice():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "creopdm"
    page = (root / "templates" / "admin_products_promote.html").read_text(encoding="utf-8")
    assert 'id="promote-reopen"' in page and 'name="reopen_files"' in page
    assert "undo the release" in page
    js = (root / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    assert "syncReopenChoice" in js and 'stateSel.value === "IN_WORK" || stateSel.value === "PRE_WORK"' in js
    assert "opt?.dataset?.released" in js and 'data-released="' in page


# ---- "Not changed since" note ------------------------------------------------------------


@requires_git
def test_revise_preview_notes_when_the_file_has_not_changed_since_its_revision_started(
    auth_client, auth_ctx
):
    product, obj = _released_under_change(auth_client, auth_ctx)
    vault = _vault_dir(auth_ctx, product)

    # A.1 -> B.1, nothing edited, released again: B.1 is byte-identical to A.1.
    first = auth_client.post(f"/api/objects/{obj['uuid']}/revise", json={"reason": "first"})
    assert first.status_code == 200, first.text
    assert _promote(auth_client, product, "RELEASED").status_code == 200
    assert _promote(auth_client, product, "UNDER_CHANGE").status_code == 200
    preview = auth_client.get(f"/api/objects/{obj['uuid']}/revise-preview").json()
    assert preview["allowed"] is True  # allowed: a soft note, never a block
    assert preview["new_display_version"] == "C.1"
    assert preview["unchanged_since"] == "A.1"
    # And it can really be revised again.
    second = auth_client.post(f"/api/objects/{obj['uuid']}/revise", json={"reason": "second"})
    assert second.status_code == 200, second.text
    assert second.json()["display_version"] == "C.1"

    # A revision whose content did change carries no note.
    out = auth_client.post(f"/api/objects/{obj['uuid']}/checkout")
    assert out.status_code == 200, out.text
    (vault / "shaft.prt").write_bytes(b"really-edited")
    checked = auth_client.post(
        f"/api/objects/{obj['uuid']}/checkin", json={"comment": "edited"}
    )
    assert checked.status_code == 200, checked.text
    assert _promote(auth_client, product, "RELEASED").status_code == 200
    assert _promote(auth_client, product, "UNDER_CHANGE").status_code == 200
    changed = auth_client.get(f"/api/objects/{obj['uuid']}/revise-preview").json()
    assert changed["allowed"] is True and changed["new_display_version"] == "D.1"
    assert changed["unchanged_since"] == ""


def test_revise_dialog_shows_the_unchanged_note():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "creopdm"
    base = (root / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'id="revise-unchanged"' in base
    app = (root / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "body.unchanged_since" in app and "has not changed since" in app


# ---- Promote refuses states that block Check Out while files are checked out -------------


@requires_git
def test_promote_into_a_state_that_blocks_checkout_is_refused_while_files_are_checked_out(
    auth_client, auth_ctx
):
    _setup_admin_and_users(auth_client, auth_ctx)
    _login(auth_client, "admin", "AdminPass1")
    product, obj = _make_product_with_file(auth_client)
    out = auth_client.post(f"/api/objects/{obj['uuid']}/checkout")
    assert out.status_code == 200, out.text

    # In Review, Approved and Released would strand the checkout (Undo follows the same matrix
    # column), so Promote refuses them and names the file and its owner.
    for state in ("IN_REVIEW", "APPROVED", "RELEASED"):
        refused = _promote(auth_client, product, state)
        assert refused.status_code == 400, (state, refused.text)
        assert "shaft.prt" in refused.text and "checked out" in refused.text, state
        assert "Alice" in refused.text or "(" in refused.text, state
    assert auth_client.get(f"/api/products/{product['uuid']}").json()["state"] == "IN_WORK"

    # States that still allow Check Out are not refused for this reason.
    assert _promote(auth_client, product, "UNDER_CHANGE").status_code == 200
    assert _promote(auth_client, product, "IN_WORK").status_code == 200

    # Once nothing is checked out the same promote works.
    undone = auth_client.post(f"/api/objects/{obj['uuid']}/undo-checkout")
    assert undone.status_code == 200, undone.text
    assert _promote(auth_client, product, "IN_REVIEW").status_code == 200
    assert auth_client.get(f"/api/products/{product['uuid']}").json()["state"] == "IN_REVIEW"


# ---- Deleting revised data must not trip over revise_operations ---------------------------


@requires_git
def test_deleting_a_revised_product_or_file_removes_its_revise_operation_rows(
    auth_client, auth_ctx
):
    """revise_operations points at objects and versions (a real foreign key on PostgreSQL), so every
    delete path has to remove those rows first or the delete fails with INTERNAL_ERROR."""
    from sqlalchemy import func, select

    from creopdm.models.revise_operation import ReviseOperation

    product, obj = _released_under_change(auth_client, auth_ctx, name="Doomed")
    done = auth_client.post(
        f"/api/objects/{obj['uuid']}/revise",
        json={"reason": "r", "operation_id": "cccccccc-0000-0000-0000-000000000003"},
    )
    assert done.status_code == 200, done.text

    def operation_rows() -> int:
        with auth_ctx.session_factory() as db:
            return int(db.scalar(select(func.count()).select_from(ReviseOperation)) or 0)

    assert operation_rows() == 1

    # Product delete (Administration → Delete products / forget).
    forgotten = auth_client.post(
        f"/api/products/{product['uuid']}/forget", json={"confirm_password": "AdminPass1"}
    )
    assert forgotten.status_code == 200, forgotten.text
    assert operation_rows() == 0

    # Removing a single revised file from a product.
    product2, obj2 = _make_product_with_file(auth_client, "Keeper", "keeper.prt")
    assert _promote(auth_client, product2, "RELEASED").status_code == 200
    assert _promote(auth_client, product2, "UNDER_CHANGE").status_code == 200
    ok = auth_client.post(
        f"/api/objects/{obj2['uuid']}/revise",
        json={"reason": "r", "operation_id": "dddddddd-0000-0000-0000-000000000004"},
    )
    assert ok.status_code == 200, ok.text
    assert operation_rows() == 1
    with auth_ctx.session_factory() as db:
        from creopdm.models.object import EngineeringObject

        row = db.scalar(select(EngineeringObject).where(EngineeringObject.uuid == obj2["uuid"]))
        auth_ctx.objects._delete_metadata(db, row)
        db.commit()
    assert operation_rows() == 0


def test_help_page_explains_revise_when_and_how():
    from pathlib import Path

    html = (
        Path(__file__).resolve().parents[2] / "src" / "creopdm" / "static" / "help" / "index.html"
    ).read_text(encoding="utf-8")
    assert 'id="revise"' in html and 'href="#revise"' in html
    for needle in (
        "When Revise is available",
        "How to revise a file",
        "Revision Reason",
        "Discard changes",
        "undo the release",
        "Check In</strong> keeps the revision",
    ):
        assert needle in html, needle
