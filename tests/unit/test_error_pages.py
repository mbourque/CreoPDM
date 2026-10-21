"""A person who opens a link they cannot use sees a readable page; scripts keep the JSON error."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from creopdm.api.errors import _PAGE_TEXT, _wants_page
from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from tests.conftest import requires_git
from tests.unit.test_baselines import _signed_in_admin

BROWSER = {"accept": "text/html,application/xhtml+xml", "sec-fetch-dest": "document"}


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


@requires_git
def test_a_link_to_something_missing_opens_a_page_in_the_browser(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product = auth_client.post("/api/products", json={"name": "Links"}).json()
    url = f"/products/{product['uuid']}/objects/{uuid4()}"
    page = auth_client.get(url, headers=BROWSER)
    assert page.status_code == 404
    assert "text/html" in page.headers["content-type"]
    assert "Not found" in page.text and 'href="/"' in page.text and '"code"' not in page.text
    # the same request from a script still gets the JSON envelope
    api = auth_client.get(url, headers={"accept": "application/json"})
    assert api.status_code == 404 and api.json()["error"]["code"]


@requires_git
def test_api_paths_always_answer_json_even_when_asked_for_html(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    reply = auth_client.get(f"/api/objects/{uuid4()}", headers=BROWSER)
    assert reply.status_code == 404 and reply.json()["error"]["code"]


def test_the_page_is_for_navigations_only():
    class _Req:
        def __init__(self, method, path, headers):
            self.method, self.headers = method, headers

            class _Url:
                pass

            self.url = _Url()
            self.url.path = path

    assert _wants_page(_Req("GET", "/products/x", BROWSER), 403)
    assert not _wants_page(_Req("POST", "/products/x", BROWSER), 403)
    assert not _wants_page(_Req("GET", "/api/x", BROWSER), 403)
    assert not _wants_page(_Req("GET", "/products/x", {"accept": "application/json"}), 403)
    assert not _wants_page(_Req("GET", "/products/x", {**BROWSER, "sec-fetch-dest": "empty"}), 403)  # a fetch()
    assert not _wants_page(_Req("GET", "/products/x", BROWSER), 500)
    assert {401, 403, 404} == set(_PAGE_TEXT)
    assert "different person" in _PAGE_TEXT[403][2]
