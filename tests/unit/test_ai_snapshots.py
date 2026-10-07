"""Experimental AI model snapshots — service, API contracts, Details tab."""

from __future__ import annotations

from pathlib import Path

import pytest

from creopdm.ai_prompts import (
    build_snapshot_compare_user_prompt,
    resolve_snapshot_compare_prompt,
    slim_snapshot_for_compare,
)
from creopdm.exceptions import ValidationAppError
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


def test_drawing_ai_snapshot_skips_solid_walk():
    """Regression: tip A.1 for wedge.drw stored PART solid (ROUND/CHAMFER) vs pending DRAWING."""
    text = BASE_HTML.read_text(encoding="utf-8")
    assert "function creoIsDrawingModel(" in text
    assert "function creoGatherDrawingViews(" in text
    assert "List2DViews" in text
    assert "GetNumberOfSheets" in text
    assert "Never creoAsSolid" in text
    assert "creoIsDrawingModel(model, filename || identity.file_name)" in text
    assert "snapIsDrw" in text
    # Bare FileName must not override wedge.drw — that skipped views (empty features).
    assert "bare FileName" in text
    assert 'identity.model_type || "").toUpperCase() === "DRAWING"' in text
    assert "function creoModelMatchesRequestedFile(" in text
    assert "stem-only collisions" in text
    find_fn = text.split("function creoFindSessionModel(", 1)[1].split(
        "function creoSessionModelKeys(", 1
    )[0]
    assert "creoModelMatchesRequestedFile(item, shortName)" in find_fn
    assert "creoModelMatchesRequestedFile(model, shortName)" in find_fn
    # Drawing branch gathers views as type VIEW; solid branch still uses creoAsSolid.
    gather = text.split("function gatherAiModelSnapshot(", 1)[1].split(
        "function creoFeatureNameWeak(", 1
    )[0]
    assert 'type: "VIEW"' in gather or "type: \"VIEW\"" in gather
    assert "isDrawing" in gather
    assert "creoAsSolid(session, model, solidDbg)" in gather
    # Solid walk only in the else (part/asm) branch after the drawing early path.
    drawing_idx = gather.find("if (isDrawing)")
    solid_idx = gather.find("creoAsSolid(session, model, solidDbg)")
    assert drawing_idx >= 0
    assert solid_idx > drawing_idx
    assert "function creoView2DIsErased(" in text
    assert "NUMBER_OF_ERASED_VIEWS" in text
    assert "NUMBER_OF_VISIBLE_VIEWS" in text
    views_fn = text.split("function creoGatherDrawingViews(", 1)[1].split(
        "function creoGatherDrawingSheetCount(", 1
    )[0]
    assert 'stableId = name ? ("view:" + name)' in views_fn
    assert "scale:" in views_fn
    assert "model:" in views_fn
    assert 'status = "erased"' in views_fn
    assert "erased:" in views_fn
    assert "Creo Erase View keeps the view in List2DViews" in text
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
    # Modified Collect must not poison tip snapshot (A.1/A.2 identical after view delete).
    assert "function objectAiSnapshotTipIsStale(" in script
    assert "objectAiSnapshotTipIsStale(objectUuid)" in script
    assert "force: true" in script
    assert "function clearAiSnapshotClientCache(" in script
    assert "clearAiSnapshotClientCache()" in script
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
    assert "async function askAiCheckinComment(" in script
    assert "/ai-snapshot/compare-pending" in script
    assert 'withBusy("Collecting modified model…"' in script
    assert "function syncCheckinAiAskRow(" in script
    assert "function aiSnapshotBodyFromGather(" in script
    # Tip snapshot vs local modified tip — never vault tip materialize.
    assert "function resolvePendingCheckinLocalPath(" in script
    assert "never Erase" in script
    assert 'gatherSource = snapshot ? "session"' in script
    assert "prepareLocalPathForMetadata(objectId, filename)" not in script.split(
        "async function askAiCheckinComment(", 1
    )[1].split("checkinBtn?.addEventListener", 1)[0]
    base_html = BASE_HTML.read_text(encoding="utf-8")
    assert "preferDisk" in base_html
    assert "Never Erase" in base_html
    assert "creoEraseModelQuiet(stale)" not in base_html
    assert "VIEW_NAMES" in base_html
    assert "objectFilename: target.filename" in script
    assert "session stem matched wedge.prt" in script
    assert 'nextDisplay !== "—"' in script
    assert "abortSignalAfter(120_000)" in script
    assert "Ollama timed out after 2 minutes" in script
    assert 'id="checkin-ask-ai"' in (
        ROOT / "src" / "creopdm" / "templates" / "app.html"
    ).read_text(encoding="utf-8")
    assert "Ask AI for comment" in (
        ROOT / "src" / "creopdm" / "templates" / "app.html"
    ).read_text(encoding="utf-8")


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
    assert "Ask AI for comment" in docs
    assert (
        "fresh gather of the model open in Creo" in docs
        or "fresh gather of the local modified tip" in docs
        or "Collect metadata on the modified" in docs
    )
    assert 'id="checkin-ask-ai"' in html


def test_snapshot_compare_prompt_requires_saved_text():
    with pytest.raises(ValidationAppError) as exc:
        resolve_snapshot_compare_prompt("")
    assert "No snapshot compare prompt is saved" in str(exc.value)
    assert resolve_snapshot_compare_prompt("  Custom prompt.  ") == "Custom prompt."
    user = build_snapshot_compare_user_prompt(
        older_snapshot={"dimensions": [{"symbol": "d0", "value": 6}]},
        newer_snapshot={"dimensions": [{"symbol": "d0", "value": 8}]},
        older_revision="A.1",
        newer_revision="A.2",
    )
    assert "Both revisions below are required" in user
    assert "Older revision (A.1):" in user
    assert "Newer revision (A.2):" in user
    assert "following your instructions" in user
    assert "Never claim a revision is missing" in user
    assert '"value":6' in user or '"value": 6' in user
    assert '"value":8' in user or '"value": 8' in user
    import creopdm.ai_prompts as ai_prompts

    assert not hasattr(ai_prompts, "DEFAULT_SNAPSHOT_COMPARE_PROMPT")
    assert not hasattr(ai_prompts, "SNAPSHOT_COMPARE_SYSTEM_PROMPT")
    src = Path(ai_prompts.__file__).read_text(encoding="utf-8")
    assert "± allowance" not in src
    assert "change notice" not in src
    assert "slim_snapshot_for_compare" in src
    # View outlines must not go to Ollama (they hung check-in Ask AI).
    bulky = {
        "features": [
            {
                "name": "VIEW_TEMPLATE_1",
                "type": "VIEW",
                "outline": [[1.23456789, 2.0, 3.0], [4.0, 5.0, 6.0]],
                "parent_ids": [],
                "erased": None,
            }
        ],
        "parameters": [
            {
                "name": "MC_VOLUME",
                "value": "",
                "data_type": "DOUBLE",
                "owner": "model",
            },
            {
                "name": "NUMBER_OF_VIEWS",
                "value": 4,
                "data_type": "INTEGER",
                "owner": "model",
            },
        ],
        "item": {"display_revision": "A.1"},
        "capture": {"captured_at": "2026-01-01T00:00:00Z", "status": "ok"},
    }
    slim = slim_snapshot_for_compare(bulky)
    assert "outline" not in slim["features"][0]
    assert "item" not in slim
    assert "captured_at" not in slim.get("capture", {})
    assert slim["capture"]["status"] == "ok"
    assert all(p["name"] != "MC_VOLUME" for p in slim["parameters"])
    assert any(p["name"] == "NUMBER_OF_VIEWS" for p in slim["parameters"])
    noisy = {
        "parameters": [
            {
                "name": "BUW_ID",
                "value": "092826_162440_2",
                "owner": "feature:13225",
                "data_type": "STRING",
            },
            {
                "name": "DESCRIPTION",
                "value": "Bolt",
                "owner": "model",
                "data_type": "STRING",
            },
        ]
    }
    slim_noisy = slim_snapshot_for_compare(noisy)
    assert all(p["name"] != "BUW_ID" for p in slim_noisy["parameters"])
    assert any(p["name"] == "DESCRIPTION" for p in slim_noisy["parameters"])
    dash_prompt = build_snapshot_compare_user_prompt(
        older_snapshot={"features": []},
        newer_snapshot={"features": []},
        older_revision="A.1",
        newer_revision="—",
    )
    assert "Newer revision (newer):" in dash_prompt
    assert "Newer revision (—):" not in dash_prompt
    prompt = build_snapshot_compare_user_prompt(
        older_snapshot=bulky,
        newer_snapshot={"features": [{"name": "A", "type": "VIEW"}]},
        older_revision="A.1",
        newer_revision="pending",
    )
    assert "outline" not in prompt
    assert "1.23456789" not in prompt
    assert "VIEW_TEMPLATE_1" in prompt
    # Large solids must keep BOTH revision labels (context overflow looked like "no A.1").
    fat_features = [
        {
            "id": i,
            "name": f"FEAT_{i}",
            "type": "CUT",
            "subtype": "Extrude",
            "status": "active",
            "regen_order": i,
            "parent_ids": [1, 2, 3],
            "outline": [[float(i), 0.0, 0.0], [1.0, 2.0, 3.0]],
        }
        for i in range(1, 140)
    ]
    fat_prompt = build_snapshot_compare_user_prompt(
        older_snapshot={"identity": {"filename": "bolt.prt", "model_type": "PART"}, "features": fat_features},
        newer_snapshot={
            "identity": {"filename": "bolt.prt", "model_type": "PART"},
            "features": fat_features[:-1],
        },
        older_revision="A.1",
        newer_revision="A.2",
    )
    assert fat_prompt.index("Older revision (A.1):") < fat_prompt.index("Newer revision (A.2):")
    # Pattern-member shells ("Feature 15775", IFX_ID_*) must collapse so Ollama
    # still sees a deleted PATTERN head (false "No model changes" on plate_3).
    pattern_head = {
        "id": 15775,
        "name": "PATTERN",
        "type": "PATTERN",
        "subtype": "",
        "status": "active",
        "regen_order": 62,
        "parent_ids": [4460, 1],
    }
    member_shells = [
        {
            "id": 15780 + i,
            "name": f"Feature {15780 + i}",
            "type": "",
            "subtype": "",
            "status": "active",
            "regen_order": None,
            "parent_ids": [],
        }
        for i in range(80)
    ]
    ifx_shell = {
        "id": 10703,
        "name": "IFX_ID_10703",
        "type": "",
        "subtype": "",
        "status": "active",
        "regen_order": None,
        "parent_ids": [],
    }
    older_pat = {
        "identity": {"filename": "plate_3.prt", "model_type": "PART"},
        "features": [
            {"id": 4460, "name": "Extrude", "type": "PROTRUSION", "subtype": "Extrude"},
            {"id": 10776, "name": "PATTERN", "type": "PATTERN", "subtype": "PATTERN"},
            ifx_shell,
            *member_shells[:20],
            pattern_head,
            *member_shells[20:],
        ],
        "dimensions": [
            {"id": 221, "symbol": "T", "value": 0.5, "units": "in"},
            {"id": 245, "symbol": "d245", "value": 2, "units": "in", "dim_type": "DIAMETER"},
        ],
    }
    newer_pat = {
        "identity": {"filename": "plate_3.prt", "model_type": "PART"},
        "features": [
            {"id": 4460, "name": "Extrude", "type": "PROTRUSION", "subtype": "Extrude"},
            {"id": 10776, "name": "PATTERN", "type": "PATTERN", "subtype": "PATTERN"},
            ifx_shell,
            *member_shells[:20],
        ],
        "dimensions": [
            {"id": 221, "symbol": "T", "value": 0.5, "units": "in"},
        ],
    }
    slim_older = slim_snapshot_for_compare(older_pat)
    slim_newer = slim_snapshot_for_compare(newer_pat)
    assert slim_older["feature_summary"]["pattern_count"] == 2
    assert slim_newer["feature_summary"]["pattern_count"] == 1
    older_patterns = [f for f in slim_older["features"] if f.get("name") == "PATTERN"]
    assert len(older_patterns) == 2
    assert any(f.get("id") == 15775 and f.get("pattern_member_count", 0) >= 60 for f in older_patterns)
    assert not any(
        str(f.get("name") or "").startswith("Feature ") for f in slim_older["features"]
    )
    assert not any(
        str(f.get("name") or "").startswith("IFX_ID_") for f in slim_older["features"]
    )
    pat_prompt = build_snapshot_compare_user_prompt(
        older_snapshot=older_pat,
        newer_snapshot=newer_pat,
        older_revision="A.1",
        newer_revision="A.2",
    )
    assert '"pattern_count":2' in pat_prompt
    assert '"pattern_count":1' in pat_prompt
    assert "Feature 15780" not in pat_prompt
    assert '"id":15775' in pat_prompt
    assert '"id":15775' not in pat_prompt.split("Newer revision (A.2):", 1)[1]
    assert "FEAT_1" in fat_prompt
    assert "outline" not in fat_prompt


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
def test_ai_snapshot_rejects_part_json_on_drawing_object(client, repo_parent, tmp_path):
    """Regression: A.2 for wedge.drw stored wedge.prt solid after stem session match."""
    product = client.post(
        "/api/products",
        json={"name": "Drw Snap Guard", "number": "SNAP-DRW"},
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["uuid"]
    drw = tmp_path / "wedge.drw.1"
    drw.write_bytes(b"FAKE CREO DRAWING")
    added = client.post(
        f"/api/products/{product_id}/objects",
        files={"file": ("wedge.drw.1", drw.read_bytes(), "application/octet-stream")},
        data={"comment": "seed drawing"},
    )
    assert added.status_code == 201, added.text
    obj = added.json()
    object_id = obj["uuid"]
    version_id = obj["current_version"]["uuid"]
    poisoned = {
        "version_id": version_id,
        "schema_version": AI_SNAPSHOT_SCHEMA_VERSION,
        "capture_status": "ok",
        "capture_errors": [],
        "snapshot": {
            "identity": {
                "filename": "wedge.prt",
                "model_type": "PART",
                "generic_name": "",
                "instance_name": "WEDGE",
                "units": None,
            },
            "features": [{"id": 40, "name": "BASE", "type": "PROTRUSION"}],
            "dimensions": [],
            "parameters": [],
        },
    }
    bad = client.post(f"/api/objects/{object_id}/ai-snapshot", json=poisoned)
    assert bad.status_code == 400, bad.text
    assert "drawing cannot be a part" in bad.text.lower() or "drawing" in bad.text.lower()
    empty = client.get(f"/api/objects/{object_id}/ai-snapshot")
    assert empty.status_code == 200
    assert empty.json()["has_snapshot"] is False


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
            "snapshot_compare_prompt": "Use only facts from the JSON.",
        },
    )
    assert saved.status_code == 200, saved.text

    captured: dict = {}

    def fake_chat(base_url, model, messages, *, timeout_s=300.0):
        captured["base_url"] = base_url
        captured["model"] = model
        captured["messages"] = messages
        assert messages[0]["content"] == "Use only facts from the JSON."
        assert "Older revision" in messages[1]["content"]
        assert "Newer revision" in messages[1]["content"]
        assert "following your instructions" in messages[1]["content"]
        assert "5.0" in messages[1]["content"]
        assert "7.5" in messages[1]["content"]
        return "Dimension d0 increased from 5 mm to 7.5 mm."

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


@requires_git
def test_ai_snapshot_compare_pending_uses_tip_and_client_newer(
    client, repo_parent, tmp_path, monkeypatch
):
    """Check-in path: tip snapshot vs gathered newer JSON (no newer version id yet)."""
    product = client.post(
        "/api/products",
        json={"name": "Snap Pending", "number": "SNAP-PEND"},
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["uuid"]
    prt = tmp_path / "block.prt.1"
    prt.write_bytes(b"FAKE CREO PART")
    added = client.post(
        f"/api/products/{product_id}/objects",
        files={"file": ("block.prt.1", prt.read_bytes(), "application/octet-stream")},
        data={"comment": "v1"},
    )
    assert added.status_code == 201, added.text
    object_id = added.json()["uuid"]
    tip_version_id = added.json()["current_version"]["uuid"]

    tip_snap = {
        "version_id": tip_version_id,
        "schema_version": AI_SNAPSHOT_SCHEMA_VERSION,
        "capture_status": "ok",
        "snapshot": {
            "identity": {"filename": "block.prt", "model_type": "PART"},
            "features": [{"id": 1, "name": "ROUND", "type": "Round"}],
            "dimensions": [{"symbol": "width", "value": 120.0, "units": "mm"}],
            "parameters": [],
        },
    }
    assert client.post(f"/api/objects/{object_id}/ai-snapshot", json=tip_snap).status_code == 200

    assert (
        client.put(
            "/api/settings",
            json={
                "ollama_model": "qwen3-8b-64k:latest",
                "snapshot_compare_prompt": "Facts only.",
            },
        ).status_code
        == 200
    )

    def fake_chat(base_url, model, messages, *, timeout_s=300.0):
        assert model == "qwen3-8b-64k:latest"
        assert messages[0]["content"] == "Facts only."
        assert "Older revision" in messages[1]["content"]
        assert "Newer revision (A.2)" in messages[1]["content"]
        assert "120" in messages[1]["content"]
        assert "100" in messages[1]["content"]
        assert "ROUND" in messages[1]["content"]
        return "Reduced width from 120 to 100 mm and removed the round feature."

    monkeypatch.setattr(
        "creopdm.services.ai_snapshot_service.chat_ollama",
        fake_chat,
    )

    pending = client.post(
        f"/api/objects/{object_id}/ai-snapshot/compare-pending",
        json={
            "newer_display_revision": "A.2",
            "newer_snapshot": {
                "identity": {"filename": "block.prt", "model_type": "PART"},
                "features": [],
                "dimensions": [{"symbol": "width", "value": 100.0, "units": "mm"}],
                "parameters": [],
            },
        },
    )
    assert pending.status_code == 200, pending.text
    body = pending.json()
    assert body["summary"].startswith("Reduced width")
    assert body["older_version_id"] == tip_version_id
    assert body["newer_version_id"] == ""
    assert body["newer_display_revision"] == "A.2"
