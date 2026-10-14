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
    assert 'data-initial-folder="CAD"' in page.text
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
    assert "Default Embed" in page.text
    assert empty["name"] not in page.text  # last-used wins over newer empty product
    assert "Loading files" in page.text
    assert 'id="ex-retry"' in page.text

    # Client auto-fetches after DOM ready (not only on Refresh click).
    script = EMBED_JS.read_text(encoding="utf-8")
    assert "function loadObjects(" in script
    assert "DOMContentLoaded" in script
    boot = script.split("function boot()", 1)[1].split("if (document.readyState", 1)[0]
    assert "loadObjects(" in boot
    assert 'refreshBtn.addEventListener("click"' in script
    assert boot.index("loadObjects(") > 0  # auto-load in boot, not only via refresh listener
    assert "This product has no files yet." in script
    assert 'listState = "ok"' in script
    assert 'credentials: "same-origin"' in script
    assert 'cache: "no-store"' in script

    # File list API for that default product already has the tip (page will fetch it).
    listing = client.get(f"/api/products/{product['uuid']}/objects")
    assert listing.status_code == 200, listing.text
    names = {row["filename"] for row in listing.json()}
    assert "bracket.prt" in names


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
    assert 'agentBase() + "/toolkit/open"' in script
    assert "/api/creo/open" in script
    assert "/materialize" in script
    assert 'fetch("http://127.0.0.1:8767' not in script
    assert "fetch(`http://127.0.0.1:8767" not in script
    assert 'addEventListener("dblclick"' in script
    assert "void onOpen()" in script
    assert 'id="embed-explorer"' in EMBED_HTML.read_text(encoding="utf-8")
    css = (ROOT / "src/creopdm/static/css/embed_explorer.css").read_text(encoding="utf-8")
    assert "ex-tree" in css
    assert "ex-actions" in css
    assert "ex-loading" in css
    docs = (ROOT / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "**Double-click** a file" in docs


def test_agent_exposes_toolkit_open_proxy():
    text = (ROOT / "src/creopdm_agent/server.py").read_text(encoding="utf-8")
    assert '@app.get("/toolkit/open")' in text
    assert "/open?" in text
    assert "fileName=" in text
