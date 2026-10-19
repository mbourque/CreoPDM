"""Product watchers are told about a new baseline and about a revision."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from tests.conftest import requires_git
from tests.unit.test_baselines import _create, _product, _signed_in_admin


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _spy(auth_ctx, monkeypatch):
    calls: list[dict] = []
    real = auth_ctx.product_watches.notify_product_activity

    def spy(db, **kwargs):
        # read while the request session is open (the product detaches afterwards)
        calls.append({**kwargs, "product_name": kwargs["product"].name})
        return real(db, **kwargs)

    monkeypatch.setattr(auth_ctx.product_watches, "notify_product_activity", spy)
    return calls


@requires_git
def test_creating_a_baseline_notifies_the_watchers(auth_client, auth_ctx, monkeypatch):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client, "Gearbox")
    calls = _spy(auth_ctx, monkeypatch)
    created = _create(auth_client, product, "Design Review 01", description="Before the customer review")
    assert created.status_code == 201, created.text
    (call,) = [c for c in calls if c["action"] == "Baseline created"]
    assert call["what_label"] == "Baseline" and call["what"] == "Design Review 01 (3 files)"
    assert call["comment"] == "Before the customer review" and call["product_name"] == "Gearbox"


@requires_git
def test_a_refused_baseline_notifies_nobody(auth_client, auth_ctx, monkeypatch):
    _signed_in_admin(auth_client, auth_ctx)
    product = auth_client.post("/api/products", json={"name": "Empty"}).json()  # nothing to baseline
    calls = _spy(auth_ctx, monkeypatch)
    refused = _create(auth_client, product, "Nothing")
    assert refused.status_code >= 400
    assert not [c for c in calls if c["action"] == "Baseline created"]


def test_the_email_names_the_baseline_not_a_file(auth_ctx):
    """The mail body says "Baseline: …" where a file change says "Files: …"."""
    source = open(
        auth_ctx.product_watches.notify_product_activity.__code__.co_filename, encoding="utf-8"
    ).read()
    assert "{what_label}: {what if what else files_block}" in source


@requires_git
def test_a_revision_notifies_the_watchers(auth_client, auth_ctx, monkeypatch):
    from tests.unit.test_revise import _released_under_change

    product, obj = _released_under_change(auth_client, auth_ctx)
    calls = _spy(auth_ctx, monkeypatch)
    done = auth_client.post(f"/api/objects/{obj['uuid']}/revise", json={"reason": "Bearing redesign"})
    assert done.status_code == 200, done.text
    assert [c for c in calls if c["action"] == "Revision created"]
