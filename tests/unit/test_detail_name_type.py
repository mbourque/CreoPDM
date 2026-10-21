"""Details -> Overview: Name and Type read exactly as in the Files list."""

from __future__ import annotations

import re

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


def _row(html: str, label: str) -> str:
    match = re.search(rf"<tr><td>{label}</td><td>(.*?)</td></tr>", html, re.S)
    assert match, label
    return re.sub(r"\s+", " ", match.group(1)).strip()


@requires_git
def test_details_name_and_type_match_the_files_list(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product = auth_client.post("/api/products", json={"name": "Docs"}).json()
    for filename in ("1_process_mfg.pdf", "Shaft.prt", "notes.txt"):
        added = auth_client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": (filename, b"bytes", "application/octet-stream")},
            data={"comment": "x"},
        )
        assert added.status_code == 201, added.text
    listed = auth_client.get(f"/api/products/{product['uuid']}/objects").json()
    assert len(listed) == 3
    for item in listed:
        page = auth_client.get(f"/products/{product['uuid']}/objects/{item['uuid']}").text
        # exactly what the Files list shows: the file name WITH its extension, and its type label
        assert _row(page, "Name") == item["filename"], item["filename"]
        assert _row(page, "Type") == item["type_label"], item["filename"]
        assert "<td>File name</td>" not in page
    pdf = next(item for item in listed if item["filename"].endswith(".pdf"))
    assert pdf["type_label"] == "PDF Document"
