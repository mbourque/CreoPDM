"""Audit: Collect metadata and Where Used write ONE summary row per run (never one per file)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.models.activity import Activity
from creopdm.models.product import Product
from creopdm.services.where_used_index_jobs import WhereUsedIndexStatus
from creopdm.utils.identity import UserIdentity
from tests.conftest import requires_git
from tests.unit.test_auth import _login
from tests.unit.test_baselines import _product, _signed_in_admin

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def _events(auth_ctx, action):
    with auth_ctx.session_factory() as db:
        return [
            (e.user, json.loads(e.details_json or "{}"), e.product_name)
            for e in db.scalars(select(Activity).where(Activity.action == action).order_by(Activity.id))
        ]


def _wait_for_where_used(auth_client, product, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = auth_client.get(f"/api/products/{product['uuid']}/rebuild-where-used").json()["state"]
        if state in {"done", "error", "cancelled"}:
            return state
        time.sleep(0.1)
    raise AssertionError("the Where Used job did not finish")


# ---- Collect metadata: one summary per run ---------------------------------------------------


def test_a_collect_run_is_audited_once_with_its_counts(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    url = f"/api/products/{product['uuid']}/metadata-collect-summary"
    posted = auth_client.post(
        url,
        json={"total": 936, "saved": 930, "failed": 3, "skipped": 3, "left_local": 0,
              "cancelled": False, "seconds": 125},
    )
    assert posted.status_code == 204, posted.text

    rows = _events(auth_ctx, "METADATA_COLLECTED")
    assert len(rows) == 1  # one row for 936 files, not 936 rows
    user, details, product_name = rows[0]
    assert user == "admin" and product_name == "Gearbox"
    assert (details["total"], details["saved"], details["failed"]) == (936, 930, 3)

    page = auth_client.get("/admin/utilities/audit", params={"action": "METADATA_COLLECTED"})
    assert page.status_code == 200
    assert "Metadata collected" in page.text
    assert "936 files: 930 saved, 3 failed, 3 skipped in 2 min 5 s" in page.text


def test_a_cancelled_collect_says_so_and_bad_input_is_refused(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    url = f"/api/products/{product['uuid']}/metadata-collect-summary"
    assert auth_client.post(url, json={"total": 10, "saved": 4, "cancelled": True, "seconds": 7}).status_code == 204
    page = auth_client.get("/admin/utilities/audit", params={"action": "METADATA_COLLECTED"})
    assert "10 files: 4 saved (cancelled) in 7 s" in page.text

    assert auth_client.post(url, json={"total": -1, "saved": 0}).status_code == 422
    assert auth_client.post(url, json={"saved": 1}).status_code == 422
    unknown = auth_client.post(
        "/api/products/00000000-0000-4000-8000-000000000000/metadata-collect-summary",
        json={"total": 1, "saved": 1},
    )
    assert unknown.status_code == 404
    assert len(_events(auth_ctx, "METADATA_COLLECTED")) == 1


def test_only_someone_who_may_update_metadata_can_report_a_collect(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    _login(auth_client, "view", "ViewPass1")
    refused = auth_client.post(
        f"/api/products/{product['uuid']}/metadata-collect-summary", json={"total": 1, "saved": 1}
    )
    assert refused.status_code == 403
    assert _events(auth_ctx, "METADATA_COLLECTED") == []


# ---- Where Used: one row per run, manual or automatic ----------------------------------------


@requires_git
def test_a_where_used_run_is_audited_once_in_the_name_of_who_started_it(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    started = auth_client.post(f"/api/products/{product['uuid']}/rebuild-where-used")
    assert started.status_code == 200, started.text
    assert _wait_for_where_used(auth_client, product) == "done"

    rows = _events(auth_ctx, "WHERE_USED_REBUILT")
    assert len(rows) == 1
    user, details, product_name = rows[0]
    assert user == "admin" and product_name == "Gearbox"
    assert details["state"] == "done" and details["parents_total"] >= 0 and details["seconds"] >= 0
    page = auth_client.get("/admin/utilities/audit", params={"action": "WHERE_USED_REBUILT"})
    assert "Where Used rebuilt" in page.text and "links added" in page.text


@requires_git
def test_a_failed_where_used_run_is_audited_with_the_reason(auth_client, auth_ctx, monkeypatch):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)

    def boom(*_args, **_kwargs):
        raise RuntimeError("vault scan exploded")

    monkeypatch.setattr(auth_ctx.metadata, "rebuild_where_used_from_vault", boom)
    assert auth_client.post(f"/api/products/{product['uuid']}/rebuild-where-used").status_code == 200
    assert _wait_for_where_used(auth_client, product) == "error"
    (user, details, _name), = _events(auth_ctx, "WHERE_USED_REBUILT")
    assert details["state"] == "error" and "vault scan exploded" in details["error"]
    page = auth_client.get("/admin/utilities/audit", params={"action": "WHERE_USED_REBUILT"})
    assert "failed: vault scan exploded" in page.text


def test_a_cancelled_where_used_run_is_audited_and_an_unattributed_run_is_not(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product, _objects = _product(auth_client)
    jobs = auth_ctx.where_used_index
    who = UserIdentity(user_name="admin", machine_name="PC-1")

    jobs._status[product["uuid"]] = WhereUsedIndexStatus(
        product_id=product["uuid"], state="running", started_at=time.time() - 3,
        edges_added=5, parents_total=20, started_by=who,
    )
    jobs.cancel(product["uuid"])
    (user, details, _name), = _events(auth_ctx, "WHERE_USED_REBUILT")
    assert user == "admin" and details["state"] == "cancelled" and details["edges_added"] == 5

    # A run nobody started (internal use) writes no audit row.
    jobs._status[product["uuid"]] = WhereUsedIndexStatus(
        product_id=product["uuid"], state="running", started_at=time.time(),
    )
    jobs.cancel(product["uuid"])
    assert len(_events(auth_ctx, "WHERE_USED_REBUILT")) == 1


# ---- the page sends the summary: manual Collect and the automatic one after Add ------------


def test_manual_collect_and_add_collect_send_one_summary_not_one_per_file():
    metadata = (ROOT / "src" / "creopdm" / "static" / "js" / "metadata.js").read_text(encoding="utf-8")
    assert "/metadata-collect-summary" in metadata and "state.startedAt = runStartedAt;" in metadata
    assert "captured + failed + expectedSkipped + leftLocal > 0" in metadata

    workspace = (ROOT / "src" / "creopdm" / "static" / "js" / "creo_workspace.js").read_text(encoding="utf-8")
    assert "async function reportMetadataCollectSummary" in workspace
    assert "if (opts.audit && !sessionOnly)" in workspace  # Open and Check-in stay quiet

    add = (ROOT / "src" / "creopdm" / "static" / "js" / "add.js").read_text(encoding="utf-8")
    assert add.count("{ audit: true }") == 2  # both Add paths (files and folders)
    # The per-file save never audits: only the summary does.
    assert "metadata-collect-summary" not in (
        ROOT / "src" / "creopdm" / "api" / "objects.py"
    ).read_text(encoding="utf-8")
