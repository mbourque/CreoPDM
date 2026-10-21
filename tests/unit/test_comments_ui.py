"""Collaboration UI wiring: tabs, panels, bell, lazy/eager modules, help and docs."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from creopdm.app import build_context, create_app
from creopdm.auth_constants import BuiltinRole
from creopdm.config import ConfigManager
from creopdm.models.user import Permission, Role, RolePermission
from tests.conftest import requires_git
from tests.unit.test_auth import _login, _setup_admin_and_users
from tests.unit.test_baselines import _create, _product

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "src" / "creopdm" / "static" / "js"


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _setup(auth_client, auth_ctx):
    _setup_admin_and_users(auth_client, auth_ctx, ("view", BuiltinRole.VIEWER.value))
    _login(auth_client, "admin", "AdminPass1")


# ------------------------------------------------------------------ server-rendered pages
@requires_git
def test_product_page_has_the_discussion_tab_panel_pill_bell_and_toast_stack(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    page = auth_client.get(f"/?product={product['uuid']}")
    assert page.status_code == 200
    html = page.text
    assert 'data-tab="discussion"' in html
    assert 'id="panel-discussion"' in html and 'data-feed="1"' in html
    assert 'id="discussion-pill-item"' in html and 'data-tab-link="discussion"' in html
    assert 'id="notif-bell"' in html and 'id="notif-panel"' in html and 'id="toast-stack"' in html
    assert 'data-can-view-comments="1"' in html and 'data-can-add-comments="1"' in html
    assert 'id="baseline-browse-discussion"' in html and 'id="baseline-discussion-dialog"' in html


@requires_git
def test_details_discussion_targets_file_version_and_baseline_file(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, objects = _product(auth_client)
    shaft = objects["shaft.prt"]
    live = auth_client.get(f"/products/{product['uuid']}/objects/{shaft['uuid']}").text
    assert 'data-tab="discussion"' in live
    assert f'data-target-type="OBJECT" data-target="{shaft["uuid"]}"' in live

    version_uuid = auth_client.get(f"/api/objects/{shaft['uuid']}").json()["current_version"]["uuid"]
    version_url = f"/products/{product['uuid']}/objects/{shaft['uuid']}/versions/{version_uuid}"
    exact = auth_client.get(version_url).text
    assert f'data-target-type="VERSION" data-target="{version_uuid}"' in exact

    baseline = _create(auth_client, product, "Review").json()
    member = auth_client.get(f"{version_url}?baseline={baseline['uuid']}").text
    assert f'data-target-type="BASELINE_MEMBER" data-target="{baseline["uuid"]}/{shaft["uuid"]}"' in member


@requires_git
def test_a_role_without_comments_view_sees_no_discussion_surface(auth_client, auth_ctx):
    _setup(auth_client, auth_ctx)
    product, _ = _product(auth_client)
    with auth_ctx.session_factory() as db:
        viewer = db.scalar(select(Role).where(Role.name == BuiltinRole.VIEWER.value))
        key_ids = db.scalars(select(Permission.id).where(Permission.key.like("comments.%"))).all()
        db.execute(
            delete(RolePermission).where(
                RolePermission.role_id == viewer.id, RolePermission.permission_id.in_(key_ids)
            )
        )
        db.commit()
    _login(auth_client, "view", "ViewPass1")
    html = auth_client.get(f"/?product={product['uuid']}").text
    for marker in ('data-tab="discussion"', 'id="notif-bell"', 'id="panel-discussion"', 'id="discussion-pill-item"'):
        assert marker not in html
    assert 'data-can-view-comments="0"' in html
    assert auth_client.get("/api/notifications").status_code == 403


def test_the_two_client_modules_are_served(auth_client, auth_ctx):
    for name in ("comments", "notifications"):
        served = auth_client.get(f"/client/js/{name}.js")
        assert served.status_code == 200, name
        assert "__creopdmModules" in served.text


# ------------------------------------------------------------------ client script wiring
def test_comments_module_wires_mentions_images_and_resolve():
    text = (JS / "comments.js").read_text(encoding="utf-8")
    # @mention list: opens on "@", narrows per letter, inserts @username, never e-mail
    assert "/mentionable?q=" in text and "[A-Za-z0-9_]*)$" in text
    assert 'event.key === "ArrowDown"' in text and 'event.key === "Tab"' in text
    assert "@${person.username} " in text
    # images: paste, drop, attach, limits, lightbox with download
    for needle in ('addEventListener("paste"', 'addEventListener("drop"', "Attach image", "MAX_IMAGES = 4", 'download'):
        assert needle in text, needle
    assert "/comment-attachments?filename=" in text and "5 * 1024 * 1024" in text
    # Reply only once someone else is in the thread (not to your own lone comment)
    assert "const othersTalked = live.some((c) => !c.can_edit)" in text
    # resolve / reopen / edit / delete / reply
    for act in ("resolve", "reopen", "edit", "delete", "reply"):
        assert f'data-act="{act}"' in text, act
    # dates use the app's formatters, never raw ISO or locale strings
    assert "shell.formatStamp(" in text and "shell.formatStampPretty(" in text
    assert "toLocale" not in text


def test_notifications_module_polls_dedupes_and_stops_on_403():
    text = (JS / "notifications.js").read_text(encoding="utf-8")
    assert "/api/notifications?after=" in text and "POLL_MS = 15000" in text
    assert "response.status === 403" in text and "function stop()" in text
    assert '"/api/notifications/seen"' in text and '"/api/notifications/read"' in text
    assert "keepalive: true" in text
    # sticky mentions, auto-hiding others, at most three popups
    assert 'new Set(["MENTION", "RESOLVED", "REOPENED"])' in text and "MAX_TOASTS = 3" in text
    # tab title and glyphs
    assert "document.title" in text and "discuss-glyph" in text
    # Mark all read only while something is unread: not on an empty list, not once all is read
    assert "readAll.hidden = !items.length || state.unread <= 0" in text
    # Clear is offered only once everything is read (and there is something to clear)
    assert "clear.hidden = state.unread > 0 || !items.length" in text and '"/api/notifications/clear"' in text
    # a refused product (403 on its summary) must not stop the poll
    assert "Plain fetch" in text


def test_app_js_opens_the_discussion_tab_and_starts_notifications_only_when_allowed():
    app = (JS / "app.js").read_text(encoding="utf-8")
    assert 'name === "discussion"' in app and 'initJobModule("comments"' in app
    assert 'dataset.canViewComments === "1"' in app
    assert "openBaselineDiscussion" in app
    assert re.search(r'get\("tab"\) === "discussion"', app)


def test_right_click_comment_on_a_single_file_row():
    menu = (JS / "files_context_menu.js").read_text(encoding="utf-8")
    assert 'action: "comment"' in menu and 'label: "Comment…"' in menu
    assert "canComment" in menu and "comment: caps.canComment" in menu
    app = (JS / "app.js").read_text(encoding="utf-8")
    assert 'action === "comment"' in app and "tab=discussion&compose=1" in app
    assert 'dataset?.canAddComments === "1"' in app
    # the comment box is focused when the page opens with compose=1
    assert '"compose") === "1"' in (JS / "comments.js").read_text(encoding="utf-8")
    # the Creo navigator uses the same shared item: it only has to say who may comment, and where to go
    nav = (JS / "embed_explorer.js").read_text(encoding="utf-8")
    assert 'getAttribute("data-can-comment") === "1"' in nav and "canComment: canComment" in nav
    assert 'action === "comment"' in nav and "?tab=discussion&compose=1" in nav
    page = (ROOT / "src" / "creopdm" / "templates" / "embed_explorer.html").read_text(encoding="utf-8")
    assert 'data-can-comment="' in page
    # one file only, never a folder or a multi-selection (shared rules, Node-free check)
    assert "canDetails && !one.isFolder" in menu


def test_product_discussion_intro_reads_comments_on_the_product_at_the_file_page_size():
    page = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(encoding="utf-8")
    assert '<p class="muted discussion-intro">Comments on <strong>{{ selected.name }}</strong>.</p>' in page
    detail = (ROOT / "src" / "creopdm" / "templates" / "object_detail.html").read_text(encoding="utf-8")
    assert "Comments on <strong>{{ object.filename }}</strong>." in detail  # the name is bold on a file too
    assert "Every conversation in this product" not in page
    css = (ROOT / "src" / "creopdm" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    # same size as the file's Discussion intro (.detail text is 0.95rem)
    assert ".discussion-intro { font-size: 0.95rem;" in css
    # spacing above the filter pills equals the file page (flex margins would add up otherwise)
    assert ".content .tab-panel > .discussion-intro { margin: 0.7rem 0 0; }" in css
    assert ".cm-bar { display: flex; gap: 0.35rem; margin: 0.95rem 0 0.6rem;" in css
    detail = (ROOT / "src" / "creopdm" / "templates" / "object_detail.html").read_text(encoding="utf-8")
    assert '<p class="muted small discussion-intro">' in detail  # the file page uses the same line style


def test_comment_box_starts_short_and_grows_with_css_alone():
    css = (ROOT / "src" / "creopdm" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    rule = css.split(".cm-input { width", 1)[1].split("}", 1)[0]
    assert "field-sizing: content" in rule and "min-height: 4.2rem" in rule and "max-height: 16rem" in rule
    js = (JS / "comments.js").read_text(encoding="utf-8")
    assert "cfg.rows || 2" in js  # two lines to start with
    # CSS only: no script resizes the box
    assert "scrollHeight" not in js and "style.height" not in js


def test_discussion_pages_do_not_repeat_the_mention_hint():
    """The comment box's own placeholder already says "Type @ to mention someone"."""
    for name in ("app.html", "object_detail.html"):
        text = (ROOT / "src" / "creopdm" / "templates" / name).read_text(encoding="utf-8")
        assert "Type @ to mention someone who has access to this product" not in text, name
    assert "Type @ to mention someone" in (JS / "comments.js").read_text(encoding="utf-8")  # the placeholder stays


def test_discussion_tab_hides_the_count_pills_and_the_file_toolbar():
    """A conversation page needs neither the Folders / Files / Parts pills above it nor the
    Add / Open / Checkout toolbar below it (the baseline list hides them the same way)."""
    app = (JS / "app.js").read_text(encoding="utf-8")
    assert 'name === "discussion" && Boolean($("#metric-filters"))' in app
    assert '"is-baseline-browse", "is-baseline-list", "is-discussion-tab"' in app  # reset on every page
    css = (ROOT / "src" / "creopdm" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert "body.is-discussion-tab #metric-filters" in css and "body.is-discussion-tab #selection-summary" in css
    assert "body.is-discussion-tab footer.toolbar .toolbar-actions" in css


def test_comments_and_bell_have_styles():
    css = (ROOT / "src" / "creopdm" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    # the product Discussion panel scrolls inside the fixed-height Files layout
    assert ".content .tab-panel > .cm-panel-host" in css and "overflow-y: auto" in css
    assert ".cm-panel-host.cm-host { max-width: none" in css  # scrollbar at the far right
    for selector in (".notif-bell", ".toast-stack", ".discuss-glyph", ".cm-thread", ".cm-mention-list", ".cm-lightbox"):
        assert selector in css, selector


# ------------------------------------------------------------------ help and docs
def test_help_and_docs_describe_discussion():
    user = (ROOT / "src" / "creopdm" / "static" / "help" / "index.html").read_text(encoding="utf-8")
    admin = (ROOT / "src" / "creopdm" / "static" / "help" / "admin.html").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert 'id="discussion"' in user and 'href="#discussion"' in user and "Ctrl+V" in user and "Resolve" in user
    assert 'id="collaboration"' in admin and "comments.resolve" in admin and "E-mail is optional" in admin
    assert "## 19. Discussion" in docs and "toast" in docs.lower()
