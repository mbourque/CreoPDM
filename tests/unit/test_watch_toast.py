"""Watching a product also raises a toast and a bell entry, not only an e-mail."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from creopdm.app import build_context, create_app
from creopdm.auth_constants import BuiltinRole
from creopdm.config import ConfigManager
from creopdm.models.user import Permission, Role, RolePermission, User
from tests.conftest import requires_git
from tests.unit.test_auth import _login, _setup_admin_and_users


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _inbox(client):
    out = client.get("/api/notifications")
    assert out.status_code == 200, out.text
    return out.json()


def _watch(client, product_uuid):
    done = client.post(f"/api/products/{product_uuid}/watch")
    assert done.status_code == 200, done.text


def _add(client, product_uuid, name="watch.prt"):
    added = client.post(
        f"/api/products/{product_uuid}/objects",
        files={"file": (name, b"bytes", "application/octet-stream")},
        data={"comment": "init"},
    )
    assert added.status_code == 201, added.text
    return added.json()


def _setup(auth_client, auth_ctx):
    _setup_admin_and_users(
        auth_client,
        auth_ctx,
        ("watcher", BuiltinRole.ENGINEER.value),
        ("blind", BuiltinRole.VIEWER.value),  # will lose comments.view: no bell
        ("bystander", BuiltinRole.ENGINEER.value),  # does not watch
    )
    _login(auth_client, "admin", "AdminPass1")
    auth_ctx.settings.email.enabled = True  # watching needs e-mail to subscribe
    product = auth_client.post("/api/products", json={"name": "Watched"}).json()
    for user in ("watcher", "blind"):
        _login(auth_client, user, f"{user.title()}Pass1")
        _watch(auth_client, product["uuid"])
    _login(auth_client, "admin", "AdminPass1")
    return product


@requires_git
def test_a_watcher_gets_a_bell_entry_and_the_actor_does_not(auth_client, auth_ctx):
    product = _setup(auth_client, auth_ctx)
    auth_ctx.settings.email.enabled = False  # in-app works without e-mail
    obj = _add(auth_client, product["uuid"])

    _login(auth_client, "watcher", "WatcherPass1")
    inbox = _inbox(auth_client)
    assert inbox["unread"] == 1
    (item,) = inbox["items"]
    assert item["kind"] == "WATCH"
    assert "added" in item["title"].lower() and "admin" in item["title"].lower()
    assert "watch.prt" in item["excerpt"]
    assert item["target_type"] == "OBJECT" and item["object_uuid"] == obj["uuid"]
    assert item["product_uuid"] == product["uuid"] and item["comment_uuid"] == ""

    _login(auth_client, "admin", "AdminPass1")  # the person who did it
    assert _inbox(auth_client)["items"] == []
    _login(auth_client, "bystander", "BystanderPass1")  # not watching
    assert _inbox(auth_client)["items"] == []


@requires_git
def test_a_watcher_without_the_bell_permission_or_without_access_is_not_notified(auth_client, auth_ctx):
    product = _setup(auth_client, auth_ctx)
    with auth_ctx.session_factory() as db:  # "blind": comments.view taken away
        role = db.scalar(select(Role).where(Role.name == BuiltinRole.VIEWER.value))
        ids = db.scalars(select(Permission.id).where(Permission.key == "comments.view")).all()
        db.execute(
            delete(RolePermission).where(RolePermission.role_id == role.id, RolePermission.permission_id.in_(ids))
        )
        db.commit()
    # "watcher" loses access to the product
    with auth_ctx.session_factory() as db:
        user = db.scalar(select(User).where(User.username == "watcher"))
        auth_ctx.user_accounts.set_product_access(db, user, access_all=False, product_uuids=[])
        db.commit()
    _add(auth_client, product["uuid"])
    with auth_ctx.session_factory() as db:
        from creopdm.models.comment import UserNotification

        assert db.scalars(select(UserNotification)).all() == []


@requires_git
def test_many_files_go_to_the_product_and_a_new_comment_is_not_told_twice(auth_client, auth_ctx):
    product = _setup(auth_client, auth_ctx)
    _add(auth_client, product["uuid"], "one.prt")
    _login(auth_client, "watcher", "WatcherPass1")
    before = len(_inbox(auth_client)["items"])
    _login(auth_client, "admin", "AdminPass1")
    # a comment that mentions nobody: comments tell only the people they concern
    made = auth_client.post(
        f"/api/products/{product['uuid']}/comments",
        json={"target_type": "PRODUCT", "target": product["uuid"], "body": "just a note"},
    )
    assert made.status_code == 201, made.text
    _login(auth_client, "watcher", "WatcherPass1")
    assert len(_inbox(auth_client)["items"]) == before  # no duplicate for "Comment added"


def test_toast_links_for_watch_notifications_go_to_files_and_details():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[2] / "src/creopdm/static/js/notifications.js").read_text(
        encoding="utf-8"
    )
    assert 'item.kind === "WATCH"' in js
    assert "`/products/${p}/objects/${o}`" in js and "`/?product=${p}`" in js
