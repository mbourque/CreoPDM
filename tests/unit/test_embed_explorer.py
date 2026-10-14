"""Compact /embed/explorer for Creo navigator — additive to the full Files UI."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import requires_git

ROOT = Path(__file__).resolve().parents[2]


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
    assert "ex-objects-json" in page.text
    assert "pin.prt" in page.text
    assert 'data-focus-filename="pin.prt"' in page.text or 'data-focus-uuid="' in page.text
    assert 'data-initial-folder="CAD"' in page.text
    # Must not pull in the full Files shell.
    assert 'id="object-table"' not in page.text
    assert "/client/app.js" not in page.text


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
    script = (ROOT / "src/creopdm/static/js/embed_explorer.js").read_text(encoding="utf-8")
    assert 'agentBase() + "/toolkit/open"' in script
    assert "/api/creo/open" in script
    assert "/materialize" in script
    assert 'fetch("http://127.0.0.1:8767' not in script
    assert "fetch(`http://127.0.0.1:8767" not in script
    assert 'id="embed-explorer"' in (
        ROOT / "src/creopdm/templates/embed_explorer.html"
    ).read_text(encoding="utf-8")
    css = (ROOT / "src/creopdm/static/css/embed_explorer.css").read_text(encoding="utf-8")
    assert "ex-tree" in css
    assert "ex-actions" in css


def test_agent_exposes_toolkit_open_proxy():
    text = (ROOT / "src/creopdm_agent/server.py").read_text(encoding="utf-8")
    assert '@app.get("/toolkit/open")' in text
    assert "/open?" in text
    assert "fileName=" in text
