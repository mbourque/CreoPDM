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
    for editable in ("PRE_WORK", "IN_WORK", "UNDER_CHANGE"):
        assert policy.allows(editable, "revise"), editable
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

    # A checked-out file blocks both Revise and Release, naming the owner.
    out = auth_client.post(f"/api/objects/{obj['uuid']}/checkout")
    assert out.status_code == 200, out.text
    held = _eligibility(auth_client, obj)
    assert (held["allowed"], held["code"]) == (False, "REVISE_ACTIVE_CHECKOUT")
    blocked = _promote(auth_client, product, "RELEASED")
    assert blocked.status_code == 400, blocked.text
    assert "shaft.prt" in blocked.text and "checked out" in blocked.text
    still = auth_client.get(f"/api/objects/{obj['uuid']}").json()
    assert still["lifecycle_state"] == "IN_WORK"
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
        assert "files_context_menu.js?v={{ app_version }}-files-ctx-revise" in page, name
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
