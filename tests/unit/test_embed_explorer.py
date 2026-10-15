"""Compact /embed/explorer for Creo navigator — additive to the full Files UI."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import requires_git

ROOT = Path(__file__).resolve().parents[2]
EMBED_JS = ROOT / "src" / "creopdm" / "static" / "js" / "embed_explorer.js"
EMBED_HTML = ROOT / "src" / "creopdm" / "templates" / "embed_explorer.html"


def _add_prt(client, product_uuid: str, *, name: str, relative_path: str) -> dict:
    response = client.post(
        f"/api/products/{product_uuid}/objects/from-uploads",
        files=[("files", (name, b"FAKE CREO PART", "application/octet-stream"))],
        data={"relative_paths": [relative_path], "comment": "seed"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("ok"), body
    return body["ok"][0]


@requires_git
def test_embed_explorer_route_and_assets(client):
    product = client.post("/api/products", json={"name": "Embed Nav"}).json()
    _add_prt(client, product["uuid"], name="pin.prt", relative_path="CAD/pin.prt")

    page = client.get(
        "/embed/explorer",
        params={
            "product": product["uuid"],
            "file": "pin.prt",
            "folder": "CAD",
        },
    )
    assert page.status_code == 200, page.text
    assert 'id="embed-explorer"' in page.text
    assert "Embed Nav" in page.text
    assert "embed_explorer.css" in page.text
    assert "embed_explorer.js" in page.text
    assert "Loading files" in page.text
    assert 'data-product-uuid="%s"' % product["uuid"] in page.text
    assert 'data-follow-active="0"' in page.text  # pinned ?product= stays put
    assert 'data-initial-folder="CAD"' in page.text
    assert "files_context_menu.js" in page.text
    assert 'id="ex-retry"' in page.text
    # Must not pull in the full Files shell.
    assert 'id="object-table"' not in page.text
    assert "/client/app.js" not in page.text


@requires_git
def test_embed_explorer_no_query_defaults_product_and_autoload(client):
    """Toolkit opens /embed/explorer with no params — files must load without Refresh."""
    product = client.post("/api/products", json={"name": "Default Embed"}).json()
    _add_prt(client, product["uuid"], name="bracket.prt", relative_path="bracket.prt")
    # Match Files home: visit product so last_product_uuid is remembered.
    home = client.get(f"/?product={product['uuid']}")
    assert home.status_code == 200, home.text

    empty = client.post("/api/products", json={"name": "Empty Later"}).json()
    page = client.get("/embed/explorer")
    assert page.status_code == 200, page.text
    assert f'data-product-uuid="{product["uuid"]}"' in page.text
    assert 'data-follow-active="1"' in page.text
    assert "Default Embed" in page.text
    assert empty["name"] not in page.text  # last-used wins over newer empty product
    assert "Loading files" in page.text
    assert 'id="ex-retry"' in page.text

    # Client auto-fetches after DOM ready (not only on Refresh click).
    script = EMBED_JS.read_text(encoding="utf-8")
    assert "function loadObjects(" in script
    assert "function syncActiveProduct(" in script
    assert "DOMContentLoaded" in script
    boot = script.split("function boot()", 1)[1].split("if (document.readyState", 1)[0]
    assert "syncActiveProduct(" in boot
    assert 'refreshBtn.addEventListener("click"' in script
    assert "This product has no files yet." in script
    assert 'listState = "ok"' in script
    assert 'credentials: "same-origin"' in script
    assert 'cache: "no-store"' in script
    assert "visibilitychange" in script
    assert "pageshow" in script
    assert "startFollowActivePoll" in script
    assert "FOLLOW_POLL_MS" in script
    assert "onlyIfChanged" in script
    assert 'root.addEventListener("mouseenter"' in script

    # File list API for that default product already has the tip (page will fetch it).
    listing = client.get(f"/api/products/{product['uuid']}/objects")
    assert listing.status_code == 200, listing.text
    names = {row["filename"] for row in listing.json()}
    assert "bracket.prt" in names


@requires_git
def test_embed_explorer_context_follows_switched_product(client):
    """After Files switches product, context API (and poll/Refresh) must follow last-used."""
    first = client.post("/api/products", json={"name": "Alpha Pane"}).json()
    second = client.post("/api/products", json={"name": "Beta Pane"}).json()
    _add_prt(client, first["uuid"], name="a.prt", relative_path="a.prt")
    _add_prt(client, second["uuid"], name="b.prt", relative_path="b.prt")

    assert client.get(f"/?product={first['uuid']}").status_code == 200
    ctx1 = client.get("/api/embed/explorer/context")
    assert ctx1.status_code == 200, ctx1.text
    body1 = ctx1.json()
    assert body1["product"]["uuid"] == first["uuid"]
    # Role ∩ lifecycle — same chrome Files uses (not lifecycle-only allows_*).
    assert "show_checkout" in body1
    assert "show_checkin" in body1
    assert "show_open" in body1
    assert "allows_content" in body1

    assert client.get(f"/?product={second['uuid']}").status_code == 200
    ctx2 = client.get("/api/embed/explorer/context")
    assert ctx2.status_code == 200, ctx2.text
    assert ctx2.json()["product"]["uuid"] == second["uuid"]
    assert ctx2.json()["product"]["name"] == "Beta Pane"

    script = EMBED_JS.read_text(encoding="utf-8")
    assert "/api/embed/explorer/context" in script
    assert "followActive" in script
    assert "Switched to " in script
    assert "setInterval" in script
    assert "onlyIfChanged" in script
    assert "showCheckout" in script
    assert "body.show_checkout" in script
    # Must not enable Checkout from lifecycle-only allows_checkout after sync.
    assert "product.allows_checkout !== false" not in script
    # RMB hide rules come from shared files_context_menu.js (same as Files).
    assert "CreoPdmFilesContextMenu" in script
    assert "menuCapabilitiesFor" in script
    assert "needsEmbeddedBrowser" in script
    # Check In: navigator detects Modified itself (shared local_cache_pending + agent), no cookie.
    assert "checkin-preview" in script
    assert "pendingCheckinIds" in script
    assert "tipHasCheckinWork" in script
    assert "mergeAgentPendingCheckinIds" in script
    assert "CreoPdmLocalCachePending" in script
    assert "resolvePendingCheckinUuids" in script
    assert "listAgentCacheFilesPreferringVault" in script
    assert "/files?" in script
    assert "/hash-paths" in script
    assert "hashAgentCachePaths" in script
    # Must not abort /files early (large workspaces; Files has no abort on list).
    list_fn = script.split("async function listAgentCacheFiles(", 1)[1].split(
      "async function listAgentCacheFilesPreferringVault(", 1
    )[0]
    assert "abortAfter" not in list_fn
    refresh_fn = script.split("async function refreshPendingCheckinIds(", 1)[1].split(
      "function rowStateFromObject(", 1
    )[0]
    assert "mergeAgentPendingCheckinIds(next)" in refresh_fn
    assert "readPendingCheckinIds" not in refresh_fn
    assert "writePendingCheckinIds" not in refresh_fn
    assert "creopdm:pending-checkin:" not in script
    shared = (ROOT / "src/creopdm/static/js/files_context_menu.js").read_text(encoding="utf-8")
    assert "creopdm_pending_checkin" not in shared
    assert "writePendingCheckinIds" not in shared
    assert "readPendingCheckinIds" not in shared
    app_js = (ROOT / "src/creopdm/static/js/app.js").read_text(encoding="utf-8")
    assert "writePendingCheckinIds" not in app_js
    html = EMBED_HTML.read_text(encoding="utf-8")
    assert "files_context_menu.js" in html
    assert "local_cache_pending.js" in html
    assert "data-purgeable=" in html


@requires_git
def test_embed_explorer_resolves_product_by_name(client):
    product = client.post("/api/products", json={"name": "Wedge Desk"}).json()
    page = client.get("/embed/explorer", params={"product": "Wedge Desk"})
    assert page.status_code == 200, page.text
    assert f'data-product-uuid="{product["uuid"]}"' in page.text
    assert "Wedge Desk" in page.text


@requires_git
def test_embed_explorer_infers_product_from_file(client):
    product = client.post("/api/products", json={"name": "Infer Me"}).json()
    _add_prt(client, product["uuid"], name="shaft.prt", relative_path="mech/shaft.prt")
    page = client.get(
        "/embed/explorer",
        params={"file": "shaft.prt", "folder": "mech"},
    )
    assert page.status_code == 200, page.text
    assert product["uuid"] in page.text
    assert 'data-initial-folder="mech"' in page.text


@requires_git
def test_embed_explorer_unknown_product_rejected(client):
    response = client.get("/embed/explorer", params={"product": "does-not-exist-xyz"})
    assert response.status_code == 400
    body = response.json()
    assert "error" in body
    message = body["error"]["message"].lower()
    assert "match" in message or "not found" in message or "does-not-exist" in message


def test_embed_js_never_calls_toolkit_from_browser():
    """Regression: navigator page must not hit 8767 (CORS / credentials)."""
    script = EMBED_JS.read_text(encoding="utf-8")
    shared = (ROOT / "src/creopdm/static/js/files_context_menu.js").read_text(encoding="utf-8")
    assert "/toolkit/url?" in script
    assert "openInMainEmbeddedBrowser" in script
    assert "tryCreoJsSetUrl" in script
    assert "thumb-preview-target" not in script
    # RMB actions that need Files hand off — no in-pane prepare/materialize/check-in.
    assert "/api/creo/open" not in script
    assert "/materialize" not in script
    assert "needsEmbeddedBrowser" in script
    assert "CreoPdmFilesContextMenu" in script
    assert 'label: "Open selected"' in shared
    assert "needsEmbedded: true" in shared
    assert 'fetch("http://127.0.0.1:8767' not in script
    assert "fetch(`http://127.0.0.1:8767" not in script
    assert "window.location.href" not in script  # Open/Details must not navigate the pane
    assert 'addEventListener("dblclick"' in script
    assert "void onOpen()" in script
    assert "function openContextMenu(" in script
    assert "filesDeepLink" in script
    assert "filesDeepLink(action)" in script
    assert "contextmenu" in script
    assert "ex-open-dialog" not in script
    assert 'agentBase() + "/toolkit/open"' not in script  # Open hand-off is main browser
    html = EMBED_HTML.read_text(encoding="utf-8")
    assert 'id="embed-explorer"' in html
    assert "files_context_menu.js" in html
    assert "thumbnail_preview.js" not in html
    assert 'data-thumb-place=' not in html
    assert 'id="ex-context-menu"' in html
    assert 'id="ex-open-dialog"' not in html
    assert 'id="ex-open"' not in html
    assert 'id="ex-actions"' not in html
    css = (ROOT / "src/creopdm/static/css/embed_explorer.css").read_text(encoding="utf-8")
    assert "ex-tree" in css
    assert "ex-context-menu" in css
    assert "ex-dialog" not in css
    assert "thumb-preview" not in css
    assert "overflow: hidden" in css
    assert "ex-loading" in css
    app_js = (ROOT / "src/creopdm/static/js/app.js").read_text(encoding="utf-8")
    assert "consumeNavigatorDeepLink" in app_js
    assert "selectOnlyForNavigator" in app_js
    assert "clearStickyMetricSelectionForNavigator" in app_js
    assert "CreoPdmFilesContextMenu" in app_js
    assert 'action === "open"' in app_js
    assert 'action === "checkout"' in app_js
    assert 'action === "checkin"' in app_js
    assert 'action === "download"' in app_js
    assert 'action === "export"' in app_js
    assert 'action === "undo"' in app_js
    # Must not use plain selectOnly (sticky Parts pill keeps hundreds selected).
    deep = app_js.split("async function consumeNavigatorDeepLink(", 1)[1].split(
        "if (isListPage)", 1
    )[0]
    assert "findNavigatorTargetRow" in deep
    assert "resolveNavigatorTargetFolder" in deep
    assert "prepareNavigatorFilesView" in deep
    assert "runNavigatorDeepLinkAction" in deep
    assert "softNavigate" in deep
    assert "selectOnly(row)" not in deep
    # Check In hand-off must seed pending Modified (navigator already detected it).
    action_fn = app_js.split("async function runNavigatorDeepLinkAction(", 1)[1].split(
        "async function consumeNavigatorDeepLink(", 1
    )[0]
    assert 'action === "checkin"' in action_fn
    assert "rememberPendingCheckinIds([uid], { merge: true })" in action_fn
    assert 'row.dataset.modifiedLocally = "1"' in action_fn
    assert "no Modified work detected" not in action_fn
    # Embed always sends folder= (even root) + cache-bust so Files finds the tip.
    link_fn = script.split("function filesDeepLink(", 1)[1].split(
        "async function onOpen(", 1
    )[0]
    assert 'q.set("folder", folder)' in link_fn
    assert 'q.set("_nav"' in link_fn
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "**Double-click** a file" in docs
    assert "**Right-click** a file" in docs
    assert "files_context_menu.js" in docs
    assert "main embedded browser" in docs
    assert "hands off" in docs.lower() or "hand off" in docs.lower()
    assert "No hover thumbnail" in docs
    assert "one scrollbar" in docs.lower() or "Only the tree scrolls" in docs
    assert "Could not find that file" in docs


def test_agent_exposes_toolkit_open_proxy():
    text = (ROOT / "src/creopdm_agent/server.py").read_text(encoding="utf-8")
    assert '@app.get("/toolkit/open")' in text
    assert '@app.get("/toolkit/url")' in text
    assert "/open?" in text
    assert "/url?url=" in text
    assert "fileName=" in text
