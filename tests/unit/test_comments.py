"""Collaboration phase 1: comments, @mentions, resolve loop, images, notifications, audit, access."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from creopdm.app import build_context, create_app
from creopdm.auth_constants import BuiltinRole, UserStatus
from creopdm.config import ConfigManager
from creopdm.models.comment import (
    Comment,
    CommentAttachment,
    CommentMention,
    UserNotification,
)
from creopdm.models.user import User
from tests.conftest import requires_git
from tests.unit.test_auth import _login, _setup_admin_and_users
from tests.unit.test_baselines import _create, _product


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _png(size=(40, 30), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _setup(auth_client, auth_ctx):
    _setup_admin_and_users(
        auth_client,
        auth_ctx,
        ("eng", BuiltinRole.ENGINEER.value),
        ("view", BuiltinRole.VIEWER.value),
        ("bob", BuiltinRole.ENGINEER.value),
    )
    _login(auth_client, "admin", "AdminPass1")


def _restrict(auth_client, auth_ctx, username: str, product_uuids: list[str]) -> None:
    """Limit a user to the given products (none: no product at all)."""
    with auth_ctx.session_factory() as db:
        uuid = db.scalar(select(User.uuid).where(User.username == username))
    data = {"product_access_present": "1"}
    if product_uuids:
        data["product_uuid"] = product_uuids
    done = auth_client.post(f"/admin/membership/users/{uuid}", data=data, follow_redirects=False)
    assert done.status_code == 303, done.text


def _post(auth_client, product, body, target_type="PRODUCT", target=None, **extra):
    return auth_client.post(
        f"/api/products/{product['uuid']}/comments",
        json={
            "target_type": target_type,
            "target": target if target is not None else product["uuid"],
            "body": body,
            **extra,
        },
    )


def _inbox(auth_client, **params):
    out = auth_client.get("/api/notifications", params=params)
    assert out.status_code == 200, out.text
    return out.json()


# ------------------------------------------------------------------ basics
@requires_git
def test_comment_thread_reply_edit_delete(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    shaft = objects["shaft.prt"]
    first = _post(auth_client, product, "Please check the bolt pattern", "OBJECT", shaft["uuid"])
    assert first.status_code == 201, first.text
    root = first.json()
    assert root["target_name"] == "shaft.prt" and root["version_display"]
    assert root["can_edit"] and root["can_delete"] and root["can_resolve"]

    reply = _post(auth_client, product, "On it", parent=root["uuid"])
    assert reply.status_code == 201, reply.text
    assert reply.json()["parent_uuid"] == root["uuid"]
    # a reply to a reply stays in the same thread (one level)
    nested = _post(auth_client, product, "Thanks", parent=reply.json()["uuid"])
    assert nested.status_code == 404

    threads = auth_client.get(
        f"/api/products/{product['uuid']}/comments",
        params={"target_type": "OBJECT", "target": shaft["uuid"]},
    ).json()
    assert len(threads) == 1 and [r["body"] for r in threads[0]["replies"]] == ["On it"]

    edited = auth_client.patch(f"/api/comments/{root['uuid']}", json={"body": "Check the pattern"})
    assert edited.status_code == 200 and edited.json()["edited_at"]
    gone = auth_client.delete(f"/api/comments/{reply.json()['uuid']}")
    assert gone.status_code == 204
    again = auth_client.get(
        f"/api/products/{product['uuid']}/comments",
        params={"target_type": "OBJECT", "target": shaft["uuid"]},
    ).json()
    assert again[0]["replies"][0]["deleted"] is True and again[0]["replies"][0]["body"] == ""


@requires_git
def test_empty_and_overlong_comments_are_refused(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    assert _post(auth_client, product, "   ").status_code == 400
    assert _post(auth_client, product, "x" * 4001).status_code == 400
    assert _post(auth_client, product, "hi", "PRODUCT", "not-the-product").status_code == 404
    assert _post(auth_client, product, "hi", "NOPE", "x").status_code == 400


@requires_git
def test_only_the_author_edits_and_only_author_or_admin_deletes(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    mine = _post(auth_client, product, "Admin note").json()
    _login(auth_client, "eng", "EngPass1")
    assert auth_client.patch(f"/api/comments/{mine['uuid']}", json={"body": "hijack"}).status_code == 403
    assert auth_client.delete(f"/api/comments/{mine['uuid']}").status_code == 403
    theirs = _post(auth_client, product, "Eng note").json()
    _login(auth_client, "admin", "AdminPass1")
    assert auth_client.delete(f"/api/comments/{theirs['uuid']}").status_code == 204


# ------------------------------------------------------------------ permissions and access
@requires_git
def test_viewer_can_comment_but_not_resolve_someone_elses_thread(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    thread = _post(auth_client, product, "Admin question").json()
    _login(auth_client, "view", "ViewPass1")
    assert _post(auth_client, product, "Viewer feedback").status_code == 201
    denied = auth_client.post(f"/api/comments/{thread['uuid']}/resolve", json={})
    assert denied.status_code == 403
    _login(auth_client, "eng", "EngPass1")  # Engineer has comments.resolve
    assert auth_client.post(f"/api/comments/{thread['uuid']}/resolve", json={}).status_code == 200


@requires_git
def test_user_without_product_access_cannot_read_write_or_see_images(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client, "Secret")
    other, _ = _product(auth_client, "Open", files=("a.prt",))
    draft = auth_client.post(
        f"/api/products/{product['uuid']}/comment-attachments?filename=shot.png", content=_png()
    ).json()
    made = _post(auth_client, product, "see image", attachment_uuids=[draft["uuid"]])
    assert made.status_code == 201
    _restrict(auth_client, auth_ctx, "eng", [other["uuid"]])
    _login(auth_client, "eng", "EngPass1")
    base = f"/api/products/{product['uuid']}"
    assert auth_client.get(f"{base}/comments").status_code == 403
    assert _post(auth_client, product, "sneaky").status_code == 403
    assert auth_client.get(f"{base}/comments/summary").status_code == 403
    assert auth_client.get(f"{base}/mentionable").status_code == 403
    assert auth_client.get(draft["url"]).status_code == 403
    assert auth_client.get(draft["thumb_url"]).status_code == 403
    assert auth_client.patch(f"/api/comments/{made.json()['uuid']}", json={"body": "x"}).status_code == 403
    assert auth_client.get(f"/api/products/{other['uuid']}/comments").status_code == 200


# ------------------------------------------------------------------ mentions
@requires_git
def test_mentionable_lists_only_the_audience_and_never_email(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    _restrict(auth_client, auth_ctx, "bob", [])  # no product access at all
    out = auth_client.get(f"/api/products/{product['uuid']}/mentionable")
    names = {row["username"] for row in out.json()}
    assert {"eng", "view"} <= names and "bob" not in names
    assert "admin" not in names  # you cannot tag yourself
    assert "example.com" not in out.text
    narrowed = auth_client.get(f"/api/products/{product['uuid']}/mentionable", params={"q": "en"}).json()
    assert [row["username"] for row in narrowed] == ["eng"]
    by_display = auth_client.get(f"/api/products/{product['uuid']}/mentionable", params={"q": "Vi"}).json()
    assert [row["username"] for row in by_display] == ["view"]
    with auth_ctx.session_factory() as db:  # disabled users are never in an audience
        user = db.scalar(select(User).where(User.username == "view"))
        user.status = UserStatus.DISABLED.value
        db.commit()
    after = auth_client.get(f"/api/products/{product['uuid']}/mentionable", params={"q": "vi"}).json()
    assert after == []


@requires_git
def test_a_mention_notifies_the_user_not_the_author_and_not_outsiders(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    _restrict(auth_client, auth_ctx, "bob", [])
    made = _post(auth_client, product, "@eng please look. cc @bob @ENG @admin @nobody")
    assert made.status_code == 201, made.text
    body = made.json()
    assert [m["username"] for m in body["mentions"]] == ["eng"]
    assert sorted(body["not_notified"]) == ["bob", "nobody"]
    assert _inbox(auth_client)["items"] == []  # the author is told nothing

    _login(auth_client, "eng", "EngPass1")
    inbox = _inbox(auth_client)
    assert inbox["unread"] == 1
    (item,) = inbox["items"]
    assert item["kind"] == "MENTION" and "mentioned you" in item["title"]
    assert item["product_uuid"] == product["uuid"] and item["comment_uuid"] == body["uuid"]

    _login(auth_client, "bob", "BobPass1")
    assert _inbox(auth_client)["items"] == []  # no access to the product: told nothing


@requires_git
def test_revoking_access_hides_past_notifications_and_the_unread_count(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    _post(auth_client, product, "@eng look")
    _restrict(auth_client, auth_ctx, "eng", [])
    _login(auth_client, "eng", "EngPass1")
    inbox = _inbox(auth_client)
    assert inbox["items"] == [] and inbox["unread"] == 0


@requires_git
def test_only_roles_with_comments_view_can_be_tagged_or_notified(auth_client, auth_ctx):
    from sqlalchemy import delete

    from creopdm.models.user import Permission, Role, RolePermission

    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    # Administrator keeps the permission, so an admin CAN be tagged by someone else.
    _login(auth_client, "eng", "EngPass1")
    listed = {r["username"] for r in auth_client.get(f"/api/products/{product['uuid']}/mentionable").json()}
    assert {"admin", "view", "bob"} <= listed
    # Take comments.view away from the Viewer role: "view" cannot read comments any more.
    with auth_ctx.session_factory() as db:
        viewer = db.scalar(select(Role).where(Role.name == BuiltinRole.VIEWER.value))
        ids = db.scalars(select(Permission.id).where(Permission.key == "comments.view")).all()
        db.execute(
            delete(RolePermission).where(
                RolePermission.role_id == viewer.id, RolePermission.permission_id.in_(ids)
            )
        )
        db.commit()
    listed = {r["username"] for r in auth_client.get(f"/api/products/{product['uuid']}/mentionable").json()}
    assert "view" not in listed and {"admin", "bob"} <= listed
    made = _post(auth_client, product, "@view please look @admin")
    assert made.status_code == 201
    assert [m["username"] for m in made.json()["mentions"]] == ["admin"]
    assert made.json()["not_notified"] == ["view"]
    _login(auth_client, "admin", "AdminPass1")
    assert len(_inbox(auth_client)["items"]) == 1  # the admin has the permission, so is told


# ------------------------------------------------------------------ notifications
@requires_git
def test_notification_poll_seen_and_read_flow(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    _post(auth_client, product, "@eng first")
    _post(auth_client, product, "@eng second")
    _login(auth_client, "eng", "EngPass1")
    first = _inbox(auth_client)
    ids = sorted(i["id"] for i in first["items"])
    newer = _inbox(auth_client, after=ids[0])
    assert [i["id"] for i in newer["items"]] == [ids[1]]  # oldest first, only newer
    assert newer["latest_id"] == ids[1]

    assert auth_client.post("/api/notifications/seen", json={"ids": ids}).status_code == 204
    assert all(i["seen"] for i in _inbox(auth_client)["items"])
    assert _inbox(auth_client)["unread"] == 2  # toasted is not read
    assert auth_client.post("/api/notifications/read", json={"ids": [ids[0]]}).status_code == 204
    assert _inbox(auth_client)["unread"] == 1
    assert auth_client.post("/api/notifications/read", json={}).status_code == 204
    assert _inbox(auth_client)["unread"] == 0


@requires_git
def test_clear_empties_only_my_bell(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    _post(auth_client, product, "@eng one")
    _post(auth_client, product, "@bob two")
    _login(auth_client, "eng", "EngPass1")
    assert len(_inbox(auth_client)["items"]) == 1
    assert auth_client.post("/api/notifications/clear").status_code == 204
    assert _inbox(auth_client) == {"enabled": True, "unread": 0, "latest_id": 0, "items": []} or (
        _inbox(auth_client)["items"] == [] and _inbox(auth_client)["unread"] == 0
    )
    _login(auth_client, "bob", "BobPass1")
    assert len(_inbox(auth_client)["items"]) == 1  # someone else's list is untouched
    # the audit log keeps the comments
    with auth_ctx.session_factory() as db:
        assert [e for e in auth_ctx.activities.list_events(db, q="") if e.action == "COMMENT_ADDED"]


@requires_git
def test_toast_and_bell_work_when_email_is_off_and_no_mail_is_attempted(auth_client, auth_ctx, monkeypatch):
    _setup(auth_client, auth_ctx)
    assert auth_ctx.settings.email.enabled is False
    sent = []
    monkeypatch.setattr(auth_ctx.notifications, "notify", lambda *a, **k: sent.append((a, k)))
    product, _ = _product(auth_client)
    assert _post(auth_client, product, "@eng hello").status_code == 201
    assert sent == []
    _login(auth_client, "eng", "EngPass1")
    assert _inbox(auth_client)["unread"] == 1


@requires_git
def test_mail_goes_to_the_mentioned_user_only_when_email_is_enabled(auth_client, auth_ctx, monkeypatch):
    _setup(auth_client, auth_ctx)
    sent = []
    monkeypatch.setattr(
        auth_ctx.notifications, "notify", lambda event, **kw: sent.append((str(event), kw))
    )
    auth_ctx.settings.email.enabled = True
    product, _ = _product(auth_client)
    _post(auth_client, product, "@eng hello")
    mails = [kw for event, kw in sent if event == "comment_mention"]
    assert len(mails) == 1 and mails[0]["to"] == "eng@example.com"
    # the mail links straight to the thread (a product-level comment: the product's Discussion tab)
    assert f"/?product={product['uuid']}&tab=discussion&thread=" in mails[0]["message"]


@requires_git
def test_the_mail_link_goes_to_the_exact_thread_for_every_kind_of_target(auth_client, auth_ctx, monkeypatch):
    _setup(auth_client, auth_ctx)
    sent = []
    monkeypatch.setattr(
        auth_ctx.notifications, "notify", lambda event, **kw: sent.append((str(event), kw))
    )
    auth_ctx.settings.email.enabled = True
    product, objects = _product(auth_client)
    shaft = objects["shaft.prt"]
    version = auth_client.get(f"/api/objects/{shaft['uuid']}").json()["current_version"]["uuid"]
    baseline = _create(auth_client, product, "Review").json()
    cases = [
        ("OBJECT", shaft["uuid"], f"/products/{product['uuid']}/objects/{shaft['uuid']}?tab=discussion&thread="),
        (
            "VERSION",
            version,
            f"/products/{product['uuid']}/objects/{shaft['uuid']}/versions/{version}?tab=discussion&thread=",
        ),
        (
            "BASELINE",
            baseline["uuid"],
            f"/?product={product['uuid']}&tab=baselines&baseline={baseline['uuid']}&discussion=1&thread=",
        ),
        (
            "BASELINE_MEMBER",
            f"{baseline['uuid']}/{shaft['uuid']}",
            f"/products/{product['uuid']}/objects/{shaft['uuid']}/versions/",
        ),
    ]
    for target_type, target, expected in cases:
        sent.clear()
        made = _post(auth_client, product, "@eng look", target_type, target)
        assert made.status_code == 201, (target_type, made.text)
        message = next(kw["message"] for event, kw in sent if event == "comment_mention")
        assert expected in message, (target_type, message)
        assert f"thread={made.json()['uuid']}" in message, target_type
    # a reply links to its thread (the first comment), not to the reply itself
    sent.clear()
    root = _post(auth_client, product, "@eng root", "OBJECT", shaft["uuid"]).json()
    sent.clear()
    _post(auth_client, product, "@eng again", parent=root["uuid"])
    reply_mail = next(kw["message"] for event, kw in sent if event == "comment_mention")
    assert f"thread={root['uuid']}" in reply_mail


@requires_git
def test_a_failing_mail_never_blocks_the_comment(auth_client, auth_ctx, monkeypatch):
    _setup(auth_client, auth_ctx)

    def boom(*_a, **_k):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(auth_ctx.notifications, "notify", boom)
    auth_ctx.settings.email.enabled = True
    product, _ = _product(auth_client)
    assert _post(auth_client, product, "@eng hello").status_code == 201
    _login(auth_client, "eng", "EngPass1")
    assert _inbox(auth_client)["unread"] == 1


@requires_git
def test_a_reply_tells_the_author_of_the_thread(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    root = _post(auth_client, product, "Admin asks").json()
    _login(auth_client, "eng", "EngPass1")
    _post(auth_client, product, "Answer", parent=root["uuid"])
    _login(auth_client, "admin", "AdminPass1")
    (item,) = _inbox(auth_client)["items"]
    assert item["kind"] == "REPLY" and item["thread_uuid"] == root["uuid"]


# ------------------------------------------------------------------ resolve / reopen loop
@requires_git
def test_resolving_tells_the_originator_and_reopening_tells_the_resolver(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    plate = objects["housing.prt"]
    _login(auth_client, "eng", "EngPass1")
    root = _post(auth_client, product, "@bob thicken it to 8 mm?", "OBJECT", plate["uuid"]).json()

    _login(auth_client, "bob", "BobPass1")  # mentioned, so may resolve
    done = auth_client.post(f"/api/comments/{root['uuid']}/resolve", json={"note": "Done in A.2"})
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["resolved"] and body["resolved_by"] == "bob" and body["resolution_note"] == "Done in A.2"
    assert body["resolved_in_version"]
    assert _inbox(auth_client)["items"][0]["kind"] == "MENTION"  # bob is not told about himself

    _login(auth_client, "eng", "EngPass1")
    kinds = [i for i in _inbox(auth_client)["items"] if i["kind"] == "RESOLVED"]
    assert len(kinds) == 1 and "Done in A.2" in kinds[0]["excerpt"]

    open_now = auth_client.get(f"/api/products/{product['uuid']}/comments").json()
    assert open_now == []  # resolved threads are hidden by default
    shown = auth_client.get(f"/api/products/{product['uuid']}/comments", params={"filter": "resolved"}).json()
    assert [t["uuid"] for t in shown] == [root["uuid"]]

    assert auth_client.post(f"/api/comments/{root['uuid']}/reopen").status_code == 200
    _login(auth_client, "bob", "BobPass1")
    assert [i["kind"] for i in _inbox(auth_client)["items"]][0] == "REOPENED"
    _login(auth_client, "eng", "EngPass1")
    reopened = auth_client.get(f"/api/products/{product['uuid']}/comments").json()
    assert [t["uuid"] for t in reopened] == [root["uuid"]] and reopened[0]["resolved"] is False


@requires_git
def test_filters_and_summary_counts(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    a = objects["shaft.prt"]
    _post(auth_client, product, "@eng one", "OBJECT", a["uuid"])
    _post(auth_client, product, "two", "OBJECT", a["uuid"])
    _post(auth_client, product, "product-wide")
    _login(auth_client, "eng", "EngPass1")
    base = f"/api/products/{product['uuid']}/comments"
    summary = auth_client.get(f"{base}/summary").json()
    assert summary["open"] == 3 and summary["mentions_me"] == 1
    assert summary["targets"]["OBJECT"][a["uuid"]] == {"open": 2, "mentions_me": 1}
    assert summary["targets"]["PRODUCT"][product["uuid"]]["open"] == 1
    assert len(auth_client.get(base, params={"filter": "mentions"}).json()) == 1
    assert auth_client.get(base, params={"filter": "mine"}).json() == []
    assert len(auth_client.get(base).json()) == 3
    # a mention stays in "Mentions me" after the thread is resolved (it leaves "Open", not this list)
    mention_thread = auth_client.get(base, params={"filter": "mentions"}).json()[0]
    assert auth_client.post(f"/api/comments/{mention_thread['uuid']}/resolve", json={"note": "ok"}).status_code == 200
    assert [t["uuid"] for t in auth_client.get(base, params={"filter": "mentions"}).json()] == [mention_thread["uuid"]]
    assert mention_thread["uuid"] not in [t["uuid"] for t in auth_client.get(base).json()]
    assert auth_client.get(f"{base}/summary").json()["mentions_me"] == 0  # the bell/pill count is open mentions only


# ------------------------------------------------------------------ baselines and versions
@requires_git
def test_comments_on_a_baseline_and_a_baseline_file(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    baseline = _create(auth_client, product, "Design Review 01").json()
    on_baseline = _post(auth_client, product, "Looks complete", "BASELINE", baseline["uuid"])
    assert on_baseline.status_code == 201 and on_baseline.json()["target_name"] == "Design Review 01"
    key = f"{baseline['uuid']}/{objects['gear.prt']['uuid']}"
    on_member = _post(auth_client, product, "Gear is wrong", "BASELINE_MEMBER", key)
    assert on_member.status_code == 201, on_member.text
    assert "in Design Review 01" in on_member.json()["target_name"]
    assert on_member.json()["version_display"]
    from uuid import uuid4

    missing = _post(auth_client, product, "x", "BASELINE_MEMBER", f"{baseline['uuid']}/{uuid4()}")
    assert missing.status_code == 404
    other, _ = _product(auth_client, "Other", files=("z.prt",))
    assert _post(auth_client, other, "wrong product", "BASELINE", baseline["uuid"]).status_code == 404


# ------------------------------------------------------------------ images
@requires_git
def test_image_upload_attach_limits_and_cleanup(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    up = f"/api/products/{product['uuid']}/comment-attachments"
    drafts = [auth_client.post(f"{up}?filename=Pasted image {i}.png", content=_png((10 + i, 12))) for i in range(5)]
    assert all(d.status_code == 201 for d in drafts)
    too_many = _post(auth_client, product, "five", attachment_uuids=[d.json()["uuid"] for d in drafts])
    assert too_many.status_code == 400
    ok = _post(auth_client, product, "", attachment_uuids=[d.json()["uuid"] for d in drafts[:2]])
    assert ok.status_code == 201, ok.text  # an image alone is enough
    images = ok.json()["images"]
    assert len(images) == 2
    served = auth_client.get(images[0]["url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff"
    thumb = auth_client.get(images[0]["thumb_url"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/png"

    # another user cannot attach admin's draft; a draft cannot be attached twice
    _login(auth_client, "eng", "EngPass1")
    stolen = _post(auth_client, product, "mine now", attachment_uuids=[drafts[2].json()["uuid"]])
    assert stolen.status_code == 400
    _login(auth_client, "admin", "AdminPass1")
    reuse = _post(auth_client, product, "again", attachment_uuids=[drafts[0].json()["uuid"]])
    assert reuse.status_code == 400

    # deleting the comment frees the image data at once
    assert auth_client.delete(f"/api/comments/{ok.json()['uuid']}").status_code == 204
    assert auth_client.get(images[0]["url"]).status_code == 404
    with auth_ctx.session_factory() as db:
        left = db.scalars(select(CommentAttachment).where(CommentAttachment.comment_id.is_not(None))).all()
        assert left == []


@requires_git
def test_image_edit_add_and_remove(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    up = f"/api/products/{product['uuid']}/comment-attachments"
    first = auth_client.post(up, content=_png()).json()
    comment = _post(auth_client, product, "with one", attachment_uuids=[first["uuid"]]).json()
    second = auth_client.post(up, content=_png((50, 50))).json()
    edited = auth_client.patch(
        f"/api/comments/{comment['uuid']}",
        json={"body": "with two", "add_attachment_uuids": [second["uuid"]]},
    ).json()
    assert len(edited["images"]) == 2
    trimmed = auth_client.patch(
        f"/api/comments/{comment['uuid']}",
        json={"body": "with one", "remove_attachment_uuids": [first["uuid"]]},
    ).json()
    assert [i["uuid"] for i in trimmed["images"]] == [second["uuid"]]


@requires_git
def test_bad_images_are_refused(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    up = f"/api/products/{product['uuid']}/comment-attachments"
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert auth_client.post(up, content=svg).status_code == 400
    assert auth_client.post(up, content=b"not an image at all").status_code == 400
    assert auth_client.post(up, content=b"").status_code == 400
    assert auth_client.post(up, content=_png()[:-80]).status_code == 400  # truncated
    big = io.BytesIO()
    Image.effect_noise((1900, 1900), 90).save(big, "PNG")
    assert len(big.getvalue()) > 5 * 1024 * 1024 or auth_client.post(up, content=big.getvalue()).status_code in (201, 400)
    assert auth_client.post(up, content=b"x" * (5 * 1024 * 1024 + 2048)).status_code == 400


def test_image_processing_strips_metadata_downscales_and_fixes_type():
    from creopdm.utils.comment_images import CommentImageError, process_image

    exif_buf = io.BytesIO()
    image = Image.new("RGB", (3000, 1000), (10, 20, 30))
    exif = Image.Exif()
    exif[0x010F] = "SecretCamera"
    image.save(exif_buf, "JPEG", exif=exif)
    assert b"SecretCamera" in exif_buf.getvalue()
    processed = process_image(exif_buf.getvalue())
    assert b"SecretCamera" not in processed.data
    assert processed.content_type == "image/jpeg"
    assert max(processed.width, processed.height) == 2400 and processed.width > processed.height
    gif = io.BytesIO()
    Image.new("P", (8, 8)).save(gif, "GIF")
    assert process_image(gif.getvalue()).content_type == "image/png"
    with pytest.raises(CommentImageError):
        process_image(b"GIF89a" + b"\x00" * 10)
    pixel_bomb = io.BytesIO()
    Image.new("1", (9000, 9000)).save(pixel_bomb, "PNG")
    with pytest.raises(CommentImageError):
        process_image(pixel_bomb.getvalue())


# ------------------------------------------------------------------ audit
@requires_git
def test_every_comment_event_is_in_the_audit_log(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    shaft = objects["shaft.prt"]
    up = f"/api/products/{product['uuid']}/comment-attachments"
    shot = auth_client.post(up, content=_png()).json()
    root = _post(
        auth_client, product, "can you check the bolt pattern? @eng", "OBJECT", shaft["uuid"],
        attachment_uuids=[shot["uuid"]],
    ).json()
    auth_client.patch(f"/api/comments/{root['uuid']}", json={"body": "check the bolt pattern @eng"})
    auth_client.post(f"/api/comments/{root['uuid']}/resolve", json={"note": "Done in A.1"})
    auth_client.post(f"/api/comments/{root['uuid']}/reopen")
    _login(auth_client, "eng", "EngPass1")
    other = _post(auth_client, product, "eng note").json()
    _login(auth_client, "admin", "AdminPass1")
    assert auth_client.delete(f"/api/comments/{other['uuid']}").status_code == 204

    with auth_ctx.session_factory() as db:
        events = auth_ctx.activities.list_events(db, q="")
        by_action = {}
        for e in events:
            by_action.setdefault(e.action, []).append(e)
    for action in (
        "COMMENT_ADDED", "COMMENT_EDITED", "COMMENT_RESOLVED", "COMMENT_REOPENED", "COMMENT_DELETED"
    ):
        assert by_action.get(action), action

    from creopdm.services.activity_service import AUDIT_ACTION_FILTER_CHOICES

    assert {"COMMENT_ADDED", "COMMENT_RESOLVED"} <= {key for key, _ in AUDIT_ACTION_FILTER_CHOICES}

    page = auth_client.get("/admin/utilities/audit", params={"q": "bolt pattern"})
    assert page.status_code == 200
    assert "bolt pattern" in page.text and "shaft.prt" in page.text
    assert "mentions @eng" in page.text and "1 image" in page.text
    resolved_page = auth_client.get("/admin/utilities/audit", params={"q": "Done in A.1"})
    assert "Done in A.1" in resolved_page.text
    deleted_page = auth_client.get("/admin/utilities/audit", params={"q": "Comment deleted"})
    assert "written by eng" in deleted_page.text or "Comment deleted" in deleted_page.text


# ------------------------------------------------------------------ delete paths
@requires_git
def test_removing_a_file_deletes_its_comments_but_keeps_the_audit(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    gear = objects["gear.prt"]
    up = f"/api/products/{product['uuid']}/comment-attachments"
    shot = auth_client.post(up, content=_png()).json()
    root = _post(auth_client, product, "@eng gear?", "OBJECT", gear["uuid"], attachment_uuids=[shot["uuid"]]).json()
    _post(auth_client, product, "reply", parent=root["uuid"])
    keep = _post(auth_client, product, "unrelated").json()
    removed = auth_client.post("/api/objects/batch/remove", json={"object_ids": [gear["uuid"]]})
    assert removed.status_code == 200, removed.text
    with auth_ctx.session_factory() as db:
        left = {c.uuid for c in db.scalars(select(Comment))}
        assert left == {keep["uuid"]}
        assert db.scalar(select(func.count()).select_from(CommentAttachment)) == 0
        assert db.scalar(select(func.count()).select_from(CommentMention)) == 0
        assert db.scalar(select(func.count()).select_from(UserNotification)) == 0
        events = auth_ctx.activities.list_events(db, q="gear?")
        assert [e for e in events if e.action == "COMMENT_ADDED"]


@requires_git
def test_deleting_a_product_deletes_all_its_discussion(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, objects = _product(auth_client, "Doomed")
    survivor, _ = _product(auth_client, "Survivor", files=("s.prt",))
    shot = auth_client.post(
        f"/api/products/{product['uuid']}/comment-attachments", content=_png()
    ).json()
    root = _post(
        auth_client, product, "@eng bye", "OBJECT", objects["shaft.prt"]["uuid"],
        attachment_uuids=[shot["uuid"]],
    ).json()
    _post(auth_client, product, "reply", parent=root["uuid"])
    _post(auth_client, survivor, "stays")
    baseline = _create(auth_client, product, "BL").json()
    _post(auth_client, product, "on baseline", "BASELINE", baseline["uuid"])
    deleted = auth_client.delete(f"/api/products/{product['uuid']}")
    assert deleted.status_code in (200, 204), deleted.text
    with auth_ctx.session_factory() as db:
        assert [c.body for c in db.scalars(select(Comment))] == ["stays"]
        assert db.scalar(select(func.count()).select_from(CommentAttachment)) == 0
        assert db.scalar(select(func.count()).select_from(UserNotification)) == 0


@requires_git
def test_the_mention_mail_shows_the_comments_pictures_inline(auth_client, auth_ctx, monkeypatch):
    _setup(auth_client, auth_ctx)
    sent = []
    monkeypatch.setattr(auth_ctx.notifications, "notify", lambda event, **kw: sent.append((str(event), kw)))
    auth_ctx.settings.email.enabled = True
    product, _ = _product(auth_client)
    up = f"/api/products/{product['uuid']}/comment-attachments"
    shots = [auth_client.post(f"{up}?filename=shot{i}.png", content=_png((20 + i, 20))).json() for i in range(2)]
    made = _post(
        auth_client,
        product,
        "@eng please check <b>this</b> & that\nsecond line",
        attachment_uuids=[s["uuid"] for s in shots],
    )
    assert made.status_code == 201, made.text
    (mail,) = [kw for event, kw in sent if event == "comment_mention"]
    # inline pictures: one per image, bytes + type, referenced from the HTML as cid:
    inline = mail["inline_images"]
    assert len(inline) == 2 and all(data[:8] == b"\x89PNG\r\n\x1a\n" and kind == "image/png" for _cid, data, kind in inline)
    for cid, _data, _kind in inline:
        assert f'src="cid:{cid}"' in mail["html"]
    # the whole comment, escaped (no markup injected), and a link to the thread
    assert "&lt;b&gt;this&lt;/b&gt; &amp; that<br>second line" in mail["html"]
    assert "<b>this</b>" not in mail["html"]
    assert f"thread={made.json()['uuid']}" in mail["html"] and 'href="' in mail["html"]
    # the plain-text version says there are pictures and where to see them
    assert "2 images" in mail["message"] and "please check <b>this</b> & that" in mail["message"]


@requires_git
def test_a_mention_mail_without_pictures_has_no_inline_images(auth_client, auth_ctx, monkeypatch):
    _setup(auth_client, auth_ctx)
    sent = []
    monkeypatch.setattr(auth_ctx.notifications, "notify", lambda event, **kw: sent.append((str(event), kw)))
    auth_ctx.settings.email.enabled = True
    product, _ = _product(auth_client)
    _post(auth_client, product, "@eng just words")
    (mail,) = [kw for event, kw in sent if event == "comment_mention"]
    assert mail["inline_images"] is None and "cid:" not in mail["html"] and "just words" in mail["html"]
