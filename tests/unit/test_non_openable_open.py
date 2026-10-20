"""System Settings -> Non openable CAD: those files stay in the product but are never opened."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from tests.conftest import requires_git
from tests.unit.test_baselines import _signed_in_admin


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _add(client, product, name):
    added = client.post(
        f"/api/products/{product['uuid']}/objects",
        files={"file": (name, b"bytes", "application/octet-stream")},
        data={"comment": "x"},
    )
    assert added.status_code == 201, added.text
    return added.json()


@requires_git
def test_a_non_openable_extension_is_refused_with_a_clear_message(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    auth_ctx.config.settings.cad.extra_extensions = [".dat", ".creo"]
    product = auth_client.post("/api/products", json={"name": "Types"}).json()
    for name in ("WINDCHILL-424 Bulk Head Plate ASSY.SLDASM.creo", "values.DAT"):
        obj = _add(auth_client, product, name)
        refused = auth_client.post("/api/creo/open", json={"object_id": obj["uuid"], "launch": False})
        assert refused.status_code == 400, (name, refused.text)
        message = refused.json()["error"]["message"]
        assert "non-openable file type" in message and "Non openable CAD" in message


@requires_git
def test_other_files_still_open(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    auth_ctx.config.settings.cad.extra_extensions = [".dat", ".creo"]
    product = auth_client.post("/api/products", json={"name": "Types"}).json()
    obj = _add(auth_client, product, "part.prt")
    opened = auth_client.post("/api/creo/open", json={"object_id": obj["uuid"], "launch": False})
    assert opened.status_code == 200, opened.text


@requires_git
def test_the_page_lists_non_openable_extensions_and_open_js_refuses_before_the_chooser(auth_client, auth_ctx):
    from pathlib import Path

    _signed_in_admin(auth_client, auth_ctx)
    auth_ctx.config.settings.cad.extra_extensions = [".dat", ".creo"]
    product = auth_client.post("/api/products", json={"name": "Types"}).json()
    _add(auth_client, product, "values.dat")
    html = auth_client.get(f"/?product={product['uuid']}").text
    assert 'data-non-openable="' in html
    attr = html.split('data-non-openable="', 1)[1].split('"', 1)[0]
    assert ".creo" in attr.split(",") and ".dat" in attr.split(",")
    js = (Path(__file__).resolve().parents[2] / "src/creopdm/static/js/open.js").read_text(encoding="utf-8")
    app = (Path(__file__).resolve().parents[2] / "src/creopdm/static/js/app.js").read_text(encoding="utf-8")
    # no Open button, Open menu or right-click Open for such a row (they all follow selectedOpenSpec)
    assert "if (rowIsNonOpenable(selected[0])) return null;" in app
    assert "function rowIsNonOpenable(row)" in app
    refuse = js.index("const notOpenable = nonOpenableMessage(")
    assert refuse < js.index("promptOpenCheckout({", refuse)  # before the Open chooser appears
