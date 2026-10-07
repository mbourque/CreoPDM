"""Experimental AI model snapshots — service, API contracts, Details tab."""

from __future__ import annotations

from pathlib import Path

from creopdm.ai_prompts import (
    SNAPSHOT_COMPARE_SYSTEM_PROMPT,
    build_snapshot_compare_user_prompt,
)
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
    assert "function creoEnrichAiSnapshotFromMetadata(" in text
    assert "creoEnrichAiSnapshotFromMetadata(ai_snapshot," in text
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
    assert 'snapshot.materials =' in text
    assert "family_table" in text
    assert '["angle", "UNIT_ANGLE"' in text
    assert "function creoUnitsFromSnapshotParams(" in text
    assert "PTC_UNITS_LENGTH" in text
    assert "creoUnitsFromSnapshotParams(" in text
    assert 'dim.units = angleUnit || "deg"' in text
    assert "Never assign length units to ANGULAR" in text
    read_dim = text.split("function creoReadDimensionRow(", 1)[1].split(
        "function creoGatherFeatureDimensions(", 1
    )[0]
    assert "UpperLimit" in read_dim
    assert "tolerance_type: toleranceType" in read_dim
    assert "defaults count as" in read_dim


def test_app_js_posts_ai_snapshot_soft_fail():
    script = APP_JS.read_text(encoding="utf-8")
    assert "async function postAiSnapshotFromGather(" in script
    assert "/ai-snapshot" in script
    assert "await postAiSnapshotFromGather(" in script
    assert "Soft-fail — AI snapshot must not block Creo metadata save" in script
    assert "async function loadAiSnapshotTab(" in script
    assert "async function copyTextToClipboard(" in script
    assert "navigator.clipboard.writeText" in script
    assert 'document.execCommand("copy")' in script
    assert "Creo's embedded browser often lacks navigator.clipboard" in script
    assert 'name === "snapshot"' in script
    assert "withSnap.length >= 2" in script
    assert 'dataset.mode = canCompare ? "compare" : "single"' in script
    assert "paneB.hidden = !canCompare" in script
    assert "await copyTextToClipboard(text)" in script
    # Must not bail out silently when Clipboard API is missing (Creo embedded).
    assert "!navigator.clipboard?.writeText" not in script
    assert "materials: ai.materials" in script
    assert "units: ai.units" in script
    assert "family_table: ai.family_table" in script
    # Compare defaults: left = older (withSnap[1]), right = newer (withSnap[0]).
    assert "left = older, right = newer" in script
    assert "fillSelect(selectA, olderSnap?.version_id)" in script
    assert "fillSelect(selectB, newerSnap?.version_id)" in script
    assert 'labelA.textContent = canCompare ? "Older" : "Revision"' in script
    assert "async function askAiSnapshotCompare(" in script
    assert "/ai-snapshot/compare" in script
    assert 'withBusy("Asking AI what changed…"' in script
    assert "askRow.hidden = !canCompare" in script
    assert "ai-snapshot-ai-answer-body" in script


def test_snapshot_tab_template_and_docs():
    html = DETAIL_HTML.read_text(encoding="utf-8")
    docs = DOCS.read_text(encoding="utf-8")
    assert 'data-tab="snapshot"' in html
    assert 'id="panel-snapshot"' in html
    assert 'id="ai-snapshot-compare"' in html
    assert 'data-mode="single"' in html
    assert 'id="ai-snapshot-rev-a"' in html
    assert 'id="ai-snapshot-rev-b"' in html
    assert 'id="ai-snapshot-label-a"' in html
    assert 'id="ai-snapshot-label-b"' in html
    assert 'id="ai-snapshot-copy-a"' in html
    assert 'id="ai-snapshot-copy-b"' in html
    assert 'id="ai-snapshot-ask-ai"' in html
    assert "Ask AI what changed" in html
    assert 'id="ai-snapshot-ai-answer"' in html
    assert 'id="ai-snapshot-ask-row" hidden' in html
    assert 'data-pane="b" hidden' in html
    assert "left = older, right = newer" in html
    assert "Open **Snapshot**" in docs
    assert "experimental tab" in docs.lower()
    assert "two or more" in docs.lower() and "snapshot" in docs.lower()
    assert "Older" in docs and "Newer" in docs
    assert "A.1 left, A.2 right" in docs
    assert "Ask AI what changed" in docs
    assert "above** the two JSON panes" in docs or "above the two JSON panes" in docs


def test_snapshot_compare_prompt_forbids_invented_tolerances():
    assert 'No "± allowance"' in SNAPSHOT_COMPARE_SYSTEM_PROMPT
    assert "one short paragraph" in SNAPSHOT_COMPARE_SYSTEM_PROMPT
    assert "change notice" in SNAPSHOT_COMPARE_SYSTEM_PROMPT
    assert "Prefer named dims" in SNAPSHOT_COMPARE_SYSTEM_PROMPT
    assert "bilateral ± tolerance" in SNAPSHOT_COMPARE_SYSTEM_PROMPT
    assert "Never say there is no previous state" in SNAPSHOT_COMPARE_SYSTEM_PROMPT
    user = build_snapshot_compare_user_prompt(
        older_snapshot={"dimensions": [{"symbol": "d0", "value": 6}]},
        newer_snapshot={"dimensions": [{"symbol": "d0", "value": 8}]},
        older_revision="A.1",
        newer_revision="A.2",
    )
    assert "Older revision (A.1):" in user
    assert "Newer revision (A.2):" in user
    assert "one short paragraph change notice" in user
    assert '"value": 6' in user
    assert '"value": 8' in user


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


@requires_git
def test_ai_snapshot_compare_calls_ollama(client, repo_parent, tmp_path, monkeypatch):
    """Compare endpoint loads both snapshots, sends prompt + JSON to Ollama, returns summary."""
    product = client.post(
        "/api/products",
        json={"name": "Snap Compare", "number": "SNAP-CMP"},
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["uuid"]
    prt = tmp_path / "wedge.prt.1"
    prt.write_bytes(b"FAKE CREO PART")
    added = client.post(
        f"/api/products/{product_id}/objects",
        files={"file": ("wedge.prt.1", prt.read_bytes(), "application/octet-stream")},
        data={"comment": "v1"},
    )
    assert added.status_code == 201, added.text
    object_id = added.json()["uuid"]
    older_version_id = added.json()["current_version"]["uuid"]

    older_snap = {
        "version_id": older_version_id,
        "schema_version": AI_SNAPSHOT_SCHEMA_VERSION,
        "capture_status": "ok",
        "snapshot": {
            "identity": {"filename": "wedge.prt", "model_type": "PART"},
            "features": [{"id": 1, "name": "Extrude 1", "type": "Extrude"}],
            "dimensions": [{"symbol": "d0", "value": 5.0, "units": "mm"}],
            "parameters": [],
        },
    }
    assert client.post(f"/api/objects/{object_id}/ai-snapshot", json=older_snap).status_code == 200

    # Second version via check-in of a new file tip (workspace check-in path may be heavy);
    # use object service version bump via another Add of same name if supported, else
    # save a second snapshot on a new ObjectVersion created through the API.
    from creopdm.models.object import EngineeringObject
    from creopdm.models.version import ObjectVersion
    import uuid as uuid_mod
    from datetime import datetime, timezone

    ctx = client.app.state.ctx
    with ctx.session_factory() as db:
        obj = db.query(EngineeringObject).filter_by(uuid=object_id).one()
        newer = ObjectVersion(
            uuid=str(uuid_mod.uuid4()),
            object_id=obj.id,
            revision="A",
            iteration=2,
            filename="wedge.prt.2",
            content_hash="deadbeef",
            file_size=1,
            created_by="tester",
            created_at=datetime.now(timezone.utc),
            comment="v2",
        )
        db.add(newer)
        obj.current_version_id = newer.id
        db.commit()
        newer_version_id = newer.uuid

    newer_snap = {
        "version_id": newer_version_id,
        "schema_version": AI_SNAPSHOT_SCHEMA_VERSION,
        "capture_status": "ok",
        "snapshot": {
            "identity": {"filename": "wedge.prt", "model_type": "PART"},
            "features": [{"id": 1, "name": "Extrude 1", "type": "Extrude"}],
            "dimensions": [{"symbol": "d0", "value": 7.5, "units": "mm"}],
            "parameters": [],
        },
    }
    assert client.post(f"/api/objects/{object_id}/ai-snapshot", json=newer_snap).status_code == 200

    # Persist Ollama settings used by compare.
    saved = client.put(
        "/api/settings",
        json={
            "ollama_base_url": "http://michael-desktop:11434",
            "ollama_model": "gemma4:latest",
        },
    )
    assert saved.status_code == 200, saved.text

    captured: dict = {}

    def fake_chat(base_url, model, messages, *, timeout_s=300.0):
        captured["base_url"] = base_url
        captured["model"] = model
        captured["messages"] = messages
        assert 'No "± allowance"' in messages[0]["content"]
        assert "change notice" in messages[0]["content"]
        assert "Older revision" in messages[1]["content"]
        assert "Newer revision" in messages[1]["content"]
        assert "one short paragraph change notice" in messages[1]["content"]
        assert "5.0" in messages[1]["content"]
        assert "7.5" in messages[1]["content"]
        return (
            "Dimension d0 increased from 5 mm to 7.5 mm."
        )

    monkeypatch.setattr(
        "creopdm.services.ai_snapshot_service.chat_ollama",
        fake_chat,
    )

    compared = client.post(
        f"/api/objects/{object_id}/ai-snapshot/compare",
        json={
            "older_version_id": older_version_id,
            "newer_version_id": newer_version_id,
        },
    )
    assert compared.status_code == 200, compared.text
    body = compared.json()
    assert body["summary"] == "Dimension d0 increased from 5 mm to 7.5 mm."
    assert body["model"] == "gemma4:latest"
    assert body["older_version_id"] == older_version_id
    assert body["newer_version_id"] == newer_version_id
    assert captured["model"] == "gemma4:latest"
    assert captured["base_url"] == "http://michael-desktop:11434"

    missing_model = client.put("/api/settings", json={"ollama_model": ""})
    assert missing_model.status_code == 200
    rejected = client.post(
        f"/api/objects/{object_id}/ai-snapshot/compare",
        json={
            "older_version_id": older_version_id,
            "newer_version_id": newer_version_id,
        },
    )
    assert rejected.status_code == 400, rejected.text
