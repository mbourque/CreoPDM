"""Experimental AI model snapshots — service, API contracts, Details tab."""

from __future__ import annotations

from pathlib import Path

from creopdm.services.ai_snapshot_service import AI_SNAPSHOT_SCHEMA_VERSION, AiSnapshotService
from tests.conftest import requires_git

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "creopdm" / "static" / "js" / "app.js"
BASE_HTML = ROOT / "src" / "creopdm" / "templates" / "base.html"
DETAIL_HTML = ROOT / "src" / "creopdm" / "templates" / "object_detail.html"
DOCS = ROOT / "docs" / "user-interactions.md"


def test_gather_ai_snapshot_contract_in_creo_js():
    text = BASE_HTML.read_text(encoding="utf-8")
    assert "function gatherAiModelSnapshot(" in text
    assert "function creoGatherFeatureDimensions(" in text
    assert "function creoGatherModelLevelDimensions(" in text
    assert "function creoListFeaturesForSnapshot(" in text
    # Configurator path: model.ListItems(ITEM_DIMENSION) + ListItems(ITEM_FEATURE).
    assert "ListItems(ITEM_DIMENSION)" in text or "ListItems(types[t])" in text
    assert "creoGatherModelLevelDimensions(solid, errors)" in text
    assert "creoListFeaturesForSnapshot(solid, errors)" in text
    assert "ExtendsInNegativeDirection" in text
    assert "extends_negative" in text
    assert "owner: ownerLabel" in text
    assert "ai_snapshot: ai_snapshot" in text
    assert "ListSubItems" in text
    assert "ITEM_DIMENSION" in text
    assert "ITEM_FEATURE" in text


def test_app_js_posts_ai_snapshot_soft_fail():
    script = APP_JS.read_text(encoding="utf-8")
    assert "async function postAiSnapshotFromGather(" in script
    assert "/ai-snapshot" in script
    assert "await postAiSnapshotFromGather(" in script
    assert "Soft-fail — AI snapshot must not block Creo metadata save" in script
    assert "async function loadAiSnapshotTab(" in script
    assert "navigator.clipboard.writeText" in script
    assert 'name === "snapshot"' in script
    assert "withSnap.length >= 2" in script
    assert 'dataset.mode = canCompare ? "compare" : "single"' in script
    assert "paneB.hidden = !canCompare" in script


def test_snapshot_tab_template_and_docs():
    html = DETAIL_HTML.read_text(encoding="utf-8")
    docs = DOCS.read_text(encoding="utf-8")
    assert 'data-tab="snapshot"' in html
    assert 'id="panel-snapshot"' in html
    assert 'id="ai-snapshot-compare"' in html
    assert 'data-mode="single"' in html
    assert 'id="ai-snapshot-rev-a"' in html
    assert 'id="ai-snapshot-rev-b"' in html
    assert 'id="ai-snapshot-copy-a"' in html
    assert 'id="ai-snapshot-copy-b"' in html
    assert 'data-pane="b" hidden' in html
    assert "Open **Snapshot**" in docs
    assert "experimental tab" in docs.lower()
    assert "two or more" in docs.lower() and "snapshot" in docs.lower()


@requires_git
def test_ai_snapshot_api_upsert_list_and_detail_tab(client, repo_parent, tmp_path):
    """POST tip snapshot, list by rev, GET returns JSON; Detail page shows Snapshot tab."""
    product = client.post(
        "/api/products",
        json={"name": "Snap Product", "number": "SNAP-1"},
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["uuid"]
    prt = tmp_path / "bracket.prt.1"
    prt.write_bytes(b"FAKE CREO PART")
    added = client.post(
        f"/api/products/{product_id}/objects",
        files={"file": ("bracket.prt.1", prt.read_bytes(), "application/octet-stream")},
        data={"comment": "seed"},
    )
    assert added.status_code == 201, added.text
    obj = added.json()
    object_id = obj["uuid"]
    version_id = obj["current_version"]["uuid"]

    empty = client.get(f"/api/objects/{object_id}/ai-snapshot")
    assert empty.status_code == 200, empty.text
    assert empty.json()["has_snapshot"] is False

    payload = {
        "version_id": version_id,
        "schema_version": AI_SNAPSHOT_SCHEMA_VERSION,
        "capture_status": "partial",
        "capture_errors": ["dimensions: ITEM_DIMENSION unavailable"],
        "snapshot": {
            "identity": {
                "filename": "bracket.prt",
                "model_type": "PART",
                "generic_name": "",
                "instance_name": "",
                "units": {"system_name": "mmNs"},
            },
            "features": [
                {
                    "id": 12,
                    "name": "Extrude 1",
                    "type": "Extrude",
                    "subtype": "Solid",
                    "status": "active",
                    "regen_order": 1,
                    "parent_ids": [],
                    "group_id": None,
                    "pattern_id": None,
                }
            ],
            "dimensions": [
                {
                    "id": 40,
                    "feature_id": 12,
                    "symbol": "d0",
                    "value": 6.0,
                    "dim_type": "diameter",
                    "units": "mm",
                    "extends_negative": False,
                    "tolerance_type": None,
                    "tolerance_limits": None,
                    "relation_driven": False,
                }
            ],
            "parameters": [
                {
                    "name": "DESCRIPTION",
                    "value": "Bracket",
                    "data_type": "STRING",
                    "units": None,
                    "description": None,
                    "owner": "model",
                }
            ],
        },
    }
    saved = client.post(f"/api/objects/{object_id}/ai-snapshot", json=payload)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["has_snapshot"] is True
    assert body["display_revision"]
    assert body["capture_status"] == "partial"
    assert body["snapshot"]["features"][0]["id"] == 12
    assert body["snapshot"]["item"]["version_uuid"] == version_id

    listed = client.get(f"/api/objects/{object_id}/ai-snapshots")
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) >= 1
    assert items[0]["has_snapshot"] is True
    assert items[0]["version_id"] == version_id

    payload["snapshot"]["dimensions"][0]["value"] = 8.0
    payload["capture_status"] = "ok"
    payload["capture_errors"] = []
    again = client.post(f"/api/objects/{object_id}/ai-snapshot", json=payload)
    assert again.status_code == 200, again.text
    assert again.json()["snapshot"]["dimensions"][0]["value"] == 8.0
    assert again.json()["capture_status"] == "ok"

    detail = client.get(f"/products/{product_id}/objects/{object_id}")
    assert detail.status_code == 200, detail.text
    assert 'data-tab="snapshot"' in detail.text
    assert 'id="panel-snapshot"' in detail.text

    ctx = client.app.state.ctx
    with ctx.session_factory() as db:
        svc = AiSnapshotService(ctx.objects)
        got = svc.get(db, object_id, version_id)
        assert got.has_snapshot is True
        assert got.snapshot["dimensions"][0]["value"] == 8.0
        listed_svc = svc.list_for_object(db, object_id)
        assert any(item.has_snapshot for item in listed_svc.items)
