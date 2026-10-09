"""Experimental AI model snapshots — service, API contracts, Details tab."""

from __future__ import annotations

from pathlib import Path

import pytest

from creopdm.ai_prompts import (
    build_snapshot_compare_user_prompt,
    format_snapshot_compare_diff_text,
    format_snapshot_compare_text,
    prepare_snapshot_for_compare,
    resolve_snapshot_compare_prompt,
    slim_snapshot_for_compare,
)
from creopdm.exceptions import ValidationAppError
from creopdm.services.ai_snapshot_service import (
    AI_SNAPSHOT_SCHEMA_VERSION,
    AiSnapshotService,
    _snapshot_with_bom_fallback,
)
from tests.conftest import requires_git

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "creopdm" / "static" / "js" / "app.js"
BASE_HTML = ROOT / "src" / "creopdm" / "templates" / "base.html"
DETAIL_HTML = ROOT / "src" / "creopdm" / "templates" / "object_detail.html"
DOCS = ROOT / "docs" / "user-interactions.md"


def test_compare_outline_never_leaves_bare_dimension_value():
    """Unitless dims must not look like bare numbers (Ask AI invents deg)."""
    from creopdm.ai_prompts import format_snapshot_compare_text, prepare_snapshot_for_compare

    prepared = prepare_snapshot_for_compare(
        {
            "identity": {"filename": "wedge.drw", "model_type": "DRAWING"},
            "dimensions": [
                {"symbol": "add2", "value": 13, "units": "deg", "dim_type": "ANGULAR"},
                {"symbol": "add6", "value": 90, "units": "", "dim_type": "LINEAR"},
            ],
            "parameters": [{"name": "PTC_UNITS_LENGTH", "value": "in"}],
        }
    )
    text = format_snapshot_compare_text(prepared)
    assert "add2 = 13 deg" in text
    assert "add6 = 90 in" in text
    bare = format_snapshot_compare_text(
        prepare_snapshot_for_compare(
            {
                "identity": {"filename": "wedge.drw", "model_type": "DRAWING"},
                "dimensions": [
                    {"symbol": "add9", "value": 90, "units": "", "dim_type": ""},
                ],
            }
        )
    )
    assert "add9 = 90 [unit unknown]" in bare
    assert "Never leave a bare number" in (
        ROOT / "src" / "creopdm" / "ai_prompts.py"
    ).read_text(encoding="utf-8")


def test_feature_outline_lines_include_creo_id():
    """Compare outlines always carry Creo feature id so the UI can align by id."""
    text = format_snapshot_compare_text(
        {
            "identity": {"filename": "1234.prt", "model_type": "PART"},
            "features": [
                {"id": 95, "name": "CUT", "type": "CUT"},
                {"id": 146, "name": "ROUND", "type": "ROUND"},
                {"id": 39, "name": "RIGHT", "type": "DATUM PLANE"},
                {"id": 40, "name": "PROTRUSION (40)", "type": "PROTRUSION"},
            ],
        }
    )
    assert "- CUT (95)" in text
    assert "- ROUND (146)" in text
    assert "- RIGHT (DATUM PLANE) (39)" in text
    assert "- PROTRUSION (40)" in text
    assert "(40) (40)" not in text
    diff = format_snapshot_compare_diff_text(
        {
            "identity": {"filename": "1234.prt", "model_type": "PART"},
            "features": [{"id": 95, "name": "CUT", "type": "CUT"}],
        },
        {
            "identity": {"filename": "1234.prt", "model_type": "PART"},
            "features": [
                {"id": 146, "name": "ROUND", "type": "ROUND"},
                {"id": 168, "name": "CHAMFER", "type": "CHAMFER"},
            ],
        },
    )
    assert "CUT (95)" in diff
    assert "ROUND (146)" in diff
    assert "CHAMFER (168)" in diff


def test_gather_ai_snapshot_contract_in_creo_js():
    text = BASE_HTML.read_text(encoding="utf-8")
    assert "function gatherAiModelSnapshot(" in text
    assert "listFeaturesForModel" in text
    assert "creoInventoryFeatureRows" in text
    assert "function creoGatherFeatureDimensions(" in text
    assert "function creoGatherModelLevelDimensions(" in text
    assert "function creoListFeaturesForSnapshot(" in text
    assert "function creoFeatureIsVisibleForSnapshot(" in text
    assert "function creoEnrichAiSnapshotFromMetadata(" in text
    assert "creoEnrichAiSnapshotFromMetadata(ai_snapshot," in text
    # Assemblies: Structure/BOM must enrich the AI snapshot (Features skip COMPONENT).
    assert "snapshot.bom = m.bom" in text
    assert "bom: bom" in text
    assert "function creoBomTipFileName(" in text
    assert "replace(/<<[^>]*>>/g" in text
    assert "function creoMergeDimensionRows(" in text
    assert "function creoStampDimensionFeatureNames(" in text
    assert "function creoApplyDimOwnerMap(" in text
    assert "function creoBuildDimensionOwnerIndex(" in text
    assert "function creoListFeaturesForDimOwnerSearch(" in text
    assert "function creoListFeatureDimensionItems(" in text
    assert "function creoResolveDimOwnerFeature(" in text
    assert "creoStampDimensionFeatureNames(dimensions, features" in text
    assert "creoBuildDimensionOwnerIndex(solid, patternLabelById" in text
    assert "creoApplyDimOwnerMap(dimensions, ownerIdx.byDimId, ownerIdx.bySymbol)" in text
    assert "Pass 1 — number PATTERN heads" in text
    # Creo.JS getDimensionFeature advice: ListSubItems reverse lookup + internals.
    assert "getDimensionFeature" in text
    assert "ListFeaturesByType(null, false)" in text
    assert "ListSubItems" in text.split("function creoListFeatureDimensionItems(", 1)[1].split(
        "function creoGatherFeatureDimensions(", 1
    )[0]
    assert "climb to a visible parent" in text
    # Configurator path: model.ListItems(ITEM_DIMENSION) + ListItems(ITEM_FEATURE).
    assert "ListItems(ITEM_DIMENSION)" in text or "ListItems(types[t])" in text
    assert "creoGatherModelLevelDimensions(solid, errors)" in text
    assert "creoListFeaturesForSnapshot(solid, errors)" in text
    # Visible-first like Features tab — internals under patterns looked like plane deletes.
    snap_list = text.split("function creoListFeaturesForSnapshot(", 1)[1].split(
        "function creoFeatureIsVisibleForSnapshot(", 1
    )[0]
    assert "ListFeaturesByType(true" in snap_list
    assert snap_list.find("ListFeaturesByType(true") < snap_list.find("ListItems(")
    assert "creoFeatureIsVisibleForSnapshot(feat)" in text
    assert 'typeU === "PATTERN"' in text
    assert "isPatternHead" in text


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
    # Drawing views are type VIEW (helper); solid branch still uses creoAsSolid.
    views_gather = text.split("function creoGatherDrawingViews(", 1)[1].split(
        "function creoGatherDrawingSheetCount(", 1
    )[0]
    assert 'type: "VIEW"' in views_gather
    gather = text.split("function gatherAiModelSnapshot(", 1)[1].split(
        "function creoFeatureNameWeak(", 1
    )[0]
    assert "isDrawing" in gather
    assert "listDrawingStructureForModel" in gather
    assert "creoInventoryDrawingFeatureRows" in gather
    assert (
        "listDrawingStructureForModel(model, session)" in gather
        or "creoGatherDrawingViews(" in gather
    )
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
    assert "Drawings often have null snapshot.units" in text
    assert "else if (lengthUnit)" in text
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
    assert "function syncAiSnapshotTabChrome(" in script
    assert "function fillAiSnapshotPendingSelects(" in script
    assert "function aiSnapshotPanel(" in script
    assert 'mode === "pending"' in script or '=== "pending"' in script
    assert "aiSnapshotCompareVersions.length >= 2" in script
    assert "await copyTextToClipboard(text)" in script
    # Must not bail out silently when Clipboard API is missing (Creo embedded).
    assert "!navigator.clipboard?.writeText" not in script
    assert "materials: ai.materials" in script
    assert "units: ai.units" in script
    assert "family_table: ai.family_table" in script
    assert "Prefer snapshot.bom" in script or "gatherSnapshot?.bom" in script
    body_fn = script.split("function aiSnapshotBodyFromGather(", 1)[1].split(
        "function objectAiSnapshotTipIsStale(", 1
    )[0]
    assert "bom," in body_fn
    assert "structure" in body_fn
    assert "gatherSnapshot?.structure" in body_fn
    # Defaults: NEW = latest snap, OLD = one prior; dropdowns cannot invert order.
    assert "NEW = latest snap, OLD = one prior" in script
    assert "function fillAiSnapshotOrderedSelects(" in script
    assert "OLD may only pick indexes > NEW" in script
    assert 'pane === "a" ? "old" : "new"' in script
    assert 'labelA.textContent = "OLD"' in script
    assert 'labelA.textContent = "Checked in"' in script
    assert 'labelB.textContent = "Not checked in"' in script
    assert 'optionB.textContent = "Workspace"' in script
    assert "function syncAiSnapshotAskVisibility(" in script
    assert "aiSnapshotPendingGather" in script
    assert "function formatAiSnapshotOutlineDisplay(" in script
    assert "=== Snapshot (${rev}) ===" not in script
    pending_render = script.split("async function renderAiSnapshotPending(", 1)[1].split(
        "async function renderAiSnapshotCompare(", 1
    )[0]
    assert "formatAiSnapshotOutlineDisplay(" in pending_render
    assert '"pending"' in pending_render
    assert "syncAiSnapshotAskVisibility(true)" in pending_render
    assert "function buildAiSnapshotLineDiff(" in script
    assert "function aiSnapshotLineIdentity(" in script
    assert "function aiSnapshotLinesAlign(" in script
    assert "function formatAiSnapshotDiffLine(" in script
    assert "function renderAiSnapshotDiffBodies(" in script
    assert "async function renderAiSnapshotCompare(" in script
    assert "async function renderAiSnapshotPending(" in script
    assert "async function refreshAiSnapshotPanelModifiedFlag(" in script
    assert "async function gatherLiveCompareNewSnapshot(" in script
    assert "async function postAiSnapshotOutline(" in script
    assert "/ai-snapshot/outline" in script
    assert "function setAiSnapshotPendingPlaceholder(" in script
    assert "aiSnapshotPendingCleanPlaceholder" in script
    assert "function latestLocalCacheTipForObject(" in script
    assert "function indexLocalCacheTipsByLogical(" in script
    assert "Highest on-disk Creo .N" in script
    # Live gather must wait for Creo.JS (hard refresh) and stamp tip .N on Model:.
    gather_fn = script.split("async function gatherLiveCompareNewSnapshot(", 1)[1].split(
        "async function postAiSnapshotOutline(", 1
    )[0]
    assert "waitForCreoMetadataBridge" in gather_fn
    assert "latestLocalCacheTipForObject" in script.split(
        "async function resolvePendingCheckinLocalPath(", 1
    )[1].split("async function askAiCheckinCommentForOne(", 1)[0]
    assert "body.identity.filename = pending.diskName" in gather_fn
    assert "Workspace ·" in gather_fn or "Workspace · ${pending.diskName}" in gather_fn
    # Local Modified must match Files via refreshPendingCheckinIds (+ agent fallback).
    mod_fn = script.split("async function refreshAiSnapshotPanelModifiedFlag(", 1)[1].split(
        "async function renderAiSnapshotPending(", 1
    )[0]
    assert "pendingCheckinIds.has(objectId)" in mod_fn
    assert "await refreshPendingCheckinIds(productId)" in mod_fn
    assert "resolveNewerLocalCacheSaves" in mod_fn
    assert "Same sources as Files → Modified" in script
    # Pending Compare must try live gather even when Modified flags are wrong.
    pending_fn = script.split("async function renderAiSnapshotPending(", 1)[1].split(
        "async function renderAiSnapshotCompare(", 1
    )[0]
    assert "Always try gather first" in pending_fn
    assert "await gatherLiveCompareNewSnapshot(panel)" in pending_fn
    assert "if (!isModified)" not in pending_fn
    assert "vaultFolder: panelVault" in script
    detail_html = DETAIL_HTML.read_text(encoding="utf-8")
    assert "data-product-id=" in detail_html
    assert "data-vault-folder=" in detail_html
    base_html = BASE_HTML.read_text(encoding="utf-8")
    assert "compare-live-tip" in base_html
    assert 'type: "same"' in script
    assert 'type: "removed"' in script
    assert 'type: "added"' in script
    assert 'type: "changed"' in script
    # Regression: align/highlight by Creo id — not list position.
    assert "aligned by Creo id" in script
    assert "CUT (95) vs ROUND (146) stay red/blue" in script
    assert "return `feat:${last}`" in script
    # Git unified markers: - removed, + added, space same (not outline bullets).
    assert "Git unified-diff markers" in script
    assert 'marker = side === "new" ? "+" : "-"' in script
    assert "async function fetchAiSnapshotOutline(" in script
    assert "=== ${roleLabel} snapshot (${rev}) ===" in script
    assert "function syncAiSnapshotScrollLayout(" in script
    assert "ai-snapshot-scroll-rail" in script or "ai-snapshot-scroll" in script
    assert "async function askAiSnapshotCompare(" in script
    assert "/ai-snapshot/compare" in script
    assert 'withBusy("Asking AI what changed…"' in script
    assert "function syncAiSnapshotAskVisibility(" in script
    assert "ai-snapshot-ai-answer-body" in script
    assert "/ai-snapshot/compare-pending" in script.split(
        "async function askAiSnapshotCompare(", 1
    )[1].split("function bindAiSnapshotControls(", 1)[0]
    assert "async function askAiCheckinComment(" in script
    assert "async function askAiCheckinCommentForOne(" in script
    assert "async function synthesizeCheckinComment(" in script
    assert "function formatCheckinBatchCommentFallback(" in script
    assert "/ai-snapshot/compare-pending" in script
    assert "/ai/checkin-comment-synthesize" in script
    # Check In Ask AI must use the same gather body + server compare path as Compare.
    assert "Same body as postAiSnapshotFromGather" in script
    assert "prepare_snapshot_for_compare" in script
    assert 'withBusy("Collecting modified model…"' in script
    assert "Summarizing check-in comment…" in script
    assert "function syncCheckinAiAskRow(" in script
    assert "candidates.length > 0" in script.split("function syncCheckinAiAskRow(", 1)[1].split(
        "async function resolvePendingCheckinLocalPath(", 1
    )[0]
    assert "dataset.aiCandidates" in script
    assert "function aiFeaturesEnabled(" in script
    assert "aiFeaturesEnabled()" in script
    assert "AI features are turned off" in script
    assert "function aiSnapshotBodyFromGather(" in script
    # Tip snapshot vs local modified tip — never vault tip materialize.
    assert "function resolvePendingCheckinLocalPath(" in script
    assert "never Erase" in script
    assert 'gatherSource = snapshot ? "session"' in script
    ask_fn = script.split("async function askAiCheckinComment(", 1)[1].split(
        "checkinBtn?.addEventListener", 1
    )[0]
    assert "prepareLocalPathForMetadata(objectId, filename)" not in ask_fn
    # Multi-file: serial per-model gather/compare, then one shared comment (no carousel).
    assert "askAiCheckinCommentForOne" in ask_fn
    assert "synthesizeCheckinComment" in ask_fn
    assert "carousel" not in ask_fn.lower()
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
    app_html = (ROOT / "src" / "creopdm" / "templates" / "app.html").read_text(
        encoding="utf-8"
    )
    assert 'id="checkin-ask-ai"' in app_html
    assert "Ask AI for comment" in app_html
    assert "Summarize modified Creo model(s)" in app_html
    docs = DOCS.read_text(encoding="utf-8")
    assert "one or more** modified Creo models" in docs
    assert "synthesize one shared check-in comment" in docs
    assert "per-file comment carousel" in docs


def test_snapshot_tab_template_and_docs():
    html = DETAIL_HTML.read_text(encoding="utf-8")
    docs = DOCS.read_text(encoding="utf-8")
    assert 'data-tab="snapshot"' in html
    assert "snapshot_tab_label" in html
    assert "show_snapshot_tab" in html
    assert 'id="panel-snapshot"' in html
    assert 'id="ai-snapshot-compare"' in html
    assert 'data-mode="{{ snapshot_tab_mode }}"' in html
    assert 'data-workspace-pending=' in html
    assert 'data-next-display=' in html
    assert 'id="ai-snapshot-scroll"' in html
    assert 'id="ai-snapshot-diff-row"' in html
    assert "ai-snapshot-head-row" in html
    assert 'id="ai-snapshot-clip-a"' in html
    assert 'id="ai-snapshot-clip-b"' in html
    assert "ai-snapshot-scroll-rail" in html
    css = (ROOT / "src" / "creopdm" / "static" / "css" / "app.css").read_text(
        encoding="utf-8"
    )
    assert ".ai-snapshot-diff-row" in css
    assert ".ai-snapshot-placeholder" in css
    assert 'data-mode="view"' not in css
    assert "flex-direction: row" in css
    assert "flex: 0 0 16px" in css
    assert "IDE-style diff" in css
    assert ".ai-snapshot-line--same" in css
    assert ".ai-snapshot-line--removed" in css
    assert ".ai-snapshot-line--changed" in css
    assert ".ai-snapshot-line--added" in css
    assert "#e6ffec" in css  # match
    assert "#ffebe9" in css  # removed
    assert "#fff8c5" in css  # changed
    assert "#ddf4ff" in css  # new/added
    assert 'id="ai-snapshot-rev-a"' in html
    assert 'id="ai-snapshot-rev-b"' in html
    assert 'id="ai-snapshot-label-a"' in html
    assert 'id="ai-snapshot-label-b"' in html
    assert "Checked in" in html and "Not checked in" in html
    assert "OLD" in html and "NEW" in html
    assert 'id="ai-snapshot-copy-a"' in html
    assert 'id="ai-snapshot-copy-b"' in html
    assert 'id="ai-snapshot-ask-ai"' in html
    assert "Ask AI what changed" in html
    assert 'id="ai-snapshot-ai-answer"' in html
    assert 'id="ai-snapshot-ask-row" hidden' in html
    assert "Side-by-side outlines for two revisions" not in html
    assert "plain text, not JSON" not in html
    assert "Compare Revisions" in docs
    assert "live" in docs.lower()
    assert "boxed placeholder" in docs
    assert "label the tab **Snapshot**" in docs
    assert "Checked in" in docs and "Not checked in" in docs
    assert "Workspace" in docs
    assert "highest local Creo" in docs or ".N" in docs
    assert "NEW snapshot (pending)" in docs
    assert "re-select the tab" in docs or "open/re-select" in docs
    assert "OLD" in docs and "NEW" in docs
    assert "light green" in docs and "light blue" in docs
    assert "yellow" in docs
    pages = (ROOT / "src" / "creopdm" / "api" / "pages.py").read_text(encoding="utf-8")
    assert "show_snapshot_tab" in pages
    assert 'snapshot_count >= 1' in pages
    assert 'snapshot_tab_mode = "compare" if snapshot_count >= 2 else "pending"' in pages
    assert 'snapshot_tab_label = "Compare Revisions"' in pages
    assert "FEATTYPE_COMPONENT" in docs
    assert "prepare_snapshot_for_compare" in docs
    assert "parts, assemblies, and drawings" in docs
    assert "d258 (Extrude) = 95.461 in" in docs
    assert "never the Creo feature id" in docs
    assert "Ask AI what changed" in docs
    assert "outline" in docs.lower()
    assert "not raw JSON" in docs or "not JSON" in docs
    assert "Ask AI for comment" in docs
    assert "fresh gather" in docs
    assert "prepare_snapshot_for_compare" in docs
    assert 'id="checkin-ask-ai"' in html


def test_snapshot_compare_prompt_requires_saved_text():
    with pytest.raises(ValidationAppError) as exc:
        resolve_snapshot_compare_prompt("")
    assert "No snapshot compare prompt is saved" in str(exc.value)
    assert resolve_snapshot_compare_prompt("  Custom prompt.  ") == "Custom prompt."
    from creopdm.ai_prompts import format_snapshot_compare_text

    user = build_snapshot_compare_user_prompt(
        older_snapshot={"dimensions": [{"symbol": "d0", "value": 6}]},
        newer_snapshot={"dimensions": [{"symbol": "d0", "value": 8}]},
        older_revision="A.1",
        newer_revision="A.2",
    )
    assert "=== OLD snapshot (A.1) ===" in user
    assert "=== NEW snapshot (A.2) ===" in user
    assert "=== Computed differences ===" in user
    # Narrative rules belong in Administration → AI prompt, not this user message.
    assert "Do not swap them" not in user
    assert "following your instructions" not in user
    assert "Never claim a revision is missing" not in user
    assert user.index("=== OLD snapshot (A.1) ===") < user.index(
        "=== NEW snapshot (A.2) ==="
    )
    assert "d0 = 6" in user
    assert "d0 = 8" in user
    assert '"value":' not in user
    import creopdm.ai_prompts as ai_prompts

    assert not hasattr(ai_prompts, "DEFAULT_SNAPSHOT_COMPARE_PROMPT")
    assert not hasattr(ai_prompts, "SNAPSHOT_COMPARE_SYSTEM_PROMPT")
    src = Path(ai_prompts.__file__).read_text(encoding="utf-8")
    assert "± allowance" not in src
    assert "change notice" not in src
    assert "slim_snapshot_for_compare" in src
    assert "format_snapshot_compare_text" in src
    # Drawing views + sheets + referenced models; never view outline floats.
    bulky = {
        "identity": {"filename": "plate.drw", "model_type": "DRAWING"},
        "features": [
            {
                "name": "VIEW_TEMPLATE_1",
                "type": "VIEW",
                "sheet": 1,
                "scale": 0.5,
                "model": "plate_3.prt",
                "outline": [[1.23456789, 2.0, 3.0], [4.0, 5.0, 6.0]],
                "parent_ids": [],
                "erased": None,
            },
            {
                "name": "FRONT",
                "type": "VIEW",
                "sheet": 1,
                "status": "erased",
                "erased": True,
            },
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
                "value": 2,
                "data_type": "INTEGER",
                "owner": "model",
            },
            {
                "name": "DESCRIPTION",
                "value": "Plate drawing",
                "owner": "model",
                "data_type": "STRING",
            },
        ],
        "item": {"display_revision": "A.1"},
        "capture": {
            "captured_at": "2026-01-01T00:00:00Z",
            "status": "ok",
            "sheet_count": 2,
            "drawing_models": [{"filename": "plate_3.prt", "model_type": "PART"}],
        },
    }
    slim = slim_snapshot_for_compare(bulky)
    assert "outline" not in slim["features"][0]
    assert "item" not in slim
    assert "captured_at" not in slim.get("capture", {})
    assert slim["capture"]["sheet_count"] == 2
    assert all(p["name"] != "MC_VOLUME" for p in slim.get("parameters", []))
    assert all(p["name"] != "NUMBER_OF_VIEWS" for p in slim.get("parameters", []))
    drw_text = format_snapshot_compare_text(bulky)
    assert "Views:" in drw_text
    assert "VIEW_TEMPLATE_1" in drw_text
    assert "sheet 1" in drw_text
    assert "scale 0.5" in drw_text
    assert "erased" in drw_text
    assert "Sheets: 2" in drw_text
    assert "Referenced models:" in drw_text
    assert "plate_3.prt" in drw_text
    assert "1.23456789" not in drw_text
    assert "NUMBER_OF_VIEWS" not in drw_text
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
    assert "=== NEW snapshot (newer) ===" in dash_prompt
    assert "=== NEW snapshot (—) ===" not in dash_prompt
    prompt = build_snapshot_compare_user_prompt(
        older_snapshot=bulky,
        newer_snapshot={
            "identity": {"filename": "plate.drw", "model_type": "DRAWING"},
            "features": [{"name": "A", "type": "VIEW", "sheet": 1}],
            "capture": {"sheet_count": 1, "drawing_models": []},
        },
        older_revision="A.1",
        newer_revision="pending",
    )
    # Must not dump raw feature outline coordinates (footer may say "outlines").
    assert '"outline"' not in prompt
    assert "1.23456789" not in prompt
    assert "VIEW_TEMPLATE_1" in prompt
    assert "Views:" in prompt
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
    assert fat_prompt.index("=== OLD snapshot (A.1) ===") < fat_prompt.index(
        "=== NEW snapshot (A.2) ==="
    )
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
            # Pattern item dim — must not reach Ollama (was cited with feature id).
            {
                "id": 253,
                "symbol": "d253",
                "value": 0,
                "units": "in",
                "dim_type": "ITEM_DIMENSION",
                "feature_id": 15775,
            },
        ],
        "materials": {"current": "STEEL_LOW_ALLOY", "names": ["STEEL_LOW_ALLOY"]},
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
        "materials": {"current": "STEEL_LOW_ALLOY", "names": ["STEEL_LOW_ALLOY"]},
    }
    slim_older = slim_snapshot_for_compare(older_pat)
    slim_newer = slim_snapshot_for_compare(newer_pat)
    older_patterns = [f for f in slim_older["features"] if f.get("name") == "PATTERN"]
    newer_patterns = [f for f in slim_newer["features"] if f.get("name") == "PATTERN"]
    assert len(older_patterns) == 2
    assert len(newer_patterns) == 1
    # Keep feature id so dimension lines can show the owner **name**.
    assert any(f.get("id") is not None for f in slim_older["features"])
    # Member shells after a PATTERN head stay collapsed (not listed as Feature N).
    assert not any(
        str(f.get("name") or "").startswith("Feature ") for f in slim_older["features"]
    )
    assert not any(
        str(f.get("name") or "").startswith("IFX_ID_") for f in slim_older["features"]
    )

    # Standalone Feature 189 (empty type, no PATTERN head) must NOT become a
    # fake "PATTERN 1 (1 members)" — Features tab shows Feature 189.
    lone_placeholder = format_snapshot_compare_text(
        {
            "identity": {"filename": "block.prt", "model_type": "PART"},
            "features": [
                {"id": 40, "name": "Extrude", "type": "PROTRUSION", "subtype": "Extrude"},
                {"id": 146, "name": "ROUND", "type": "ROUND"},
                {"id": 167, "name": "ROUND", "type": "ROUND"},
                {"id": 189, "name": "Feature 189", "type": "", "subtype": ""},
            ],
        }
    )
    assert "Feature 189" in lone_placeholder
    assert "PATTERN" not in lone_placeholder
    assert all(d.get("symbol") != "d253" for d in slim_older["dimensions"])
    pat_prompt = build_snapshot_compare_user_prompt(
        older_snapshot=older_pat,
        newer_snapshot=newer_pat,
        older_revision="A.1",
        newer_revision="A.2",
    )
    assert "Features:" in pat_prompt
    older_half, after_old = pat_prompt.split("=== NEW snapshot (A.2) ===", 1)
    newer_half, _, diff_half = after_old.partition(
        "=== Computed differences ==="
    )
    # Number PATTERNs in tree order so Ask AI can say "deleted PATTERN 2", not
    # "deleted pattern instances" when only one PATTERN line disappears.
    assert "- PATTERN 1" in older_half
    assert "- PATTERN 2" in older_half
    assert older_half.count("PATTERN ") >= 2
    assert "PATTERN 1" in newer_half
    assert "PATTERN 2" not in newer_half
    assert "PATTERN 2" in diff_half
    assert "Features removed" in diff_half
    assert "members)" in older_half
    assert "Feature 15780" not in pat_prompt
    # Outline lines end with Creo feature id (compare aligns on id); must not
    # resurrect dropped pattern-item dims that only cited that id.
    assert "(15775)" in older_half
    assert "d253" not in pat_prompt
    assert "T = 0.5 in" in pat_prompt
    assert "Material: STEEL_LOW_ALLOY" in pat_prompt
    assert "{" not in pat_prompt
    assert "FEAT_1" in fat_prompt
    assert '"outline"' not in fat_prompt
    assert "1.0, 2.0, 3.0" not in fat_prompt

    # Pattern-owned unnamed DATUM PLANE is internal — not a user plane delete.
    ghost_plane_snap = {
        "identity": {"filename": "plate_3.prt", "model_type": "PART"},
        "features": [
            {"name": "PATTERN", "type": "PATTERN", "id": 100},
            {
                "name": "DATUM PLANE",
                "type": "DATUM PLANE",
                "id": 101,
                "pattern_id": 100,
            },
            {"name": "PATTERN", "type": "PATTERN", "id": 200},
            {
                "name": "DATUM PLANE",
                "type": "DATUM PLANE",
                "id": 201,
                "pattern_id": 200,
                "visible": False,
            },
            {"name": "ATTACH_PLANE", "type": "DATUM PLANE", "id": 50},
        ],
    }
    ghost_text = format_snapshot_compare_text(ghost_plane_snap)
    assert "PATTERN 1" in ghost_text
    assert "PATTERN 2" in ghost_text
    assert "ATTACH_PLANE (DATUM PLANE) (50)" in ghost_text
    # Unnamed pattern-owned planes stay out; type on ATTACH_PLANE is fine.
    assert "- DATUM PLANE" not in ghost_text
    assert ghost_text.count("DATUM PLANE") == 1
    ghost_diff = format_snapshot_compare_diff_text(
        ghost_plane_snap,
        {
            "identity": {"filename": "plate_3.prt", "model_type": "PART"},
            "features": [
                {"name": "PATTERN", "type": "PATTERN", "id": 100},
                {"name": "ATTACH_PLANE", "type": "DATUM PLANE", "id": 50},
            ],
        },
    )
    assert "PATTERN 2" in ghost_diff
    assert "DATUM PLANE" not in ghost_diff.split("Features removed", 1)[-1].split(
        "Features added", 1
    )[0]

    # Regression: removed d248=7 and d255=6 must not become "reduced d248 to 6".
    plate_old = {
        "identity": {"filename": "plate_3.prt", "model_type": "PART"},
        "features": [
            {"name": "PATTERN", "type": "PATTERN"},
            {"name": "PATTERN", "type": "PATTERN"},
            {"name": "PATTERN", "type": "PATTERN", "pattern_member_count": 1012},
        ],
        "dimensions": [
            {"symbol": "d245", "value": 2, "units": "in"},
            {"symbol": "d248", "value": 7, "units": "in"},
            {"symbol": "d255", "value": 6, "units": "in"},
            {"symbol": "T", "value": 0.5, "units": "in"},
        ],
    }
    plate_new = {
        "identity": {"filename": "plate_3.prt", "model_type": "PART"},
        "features": [
            {"name": "PATTERN", "type": "PATTERN"},
            {"name": "PATTERN", "type": "PATTERN"},
        ],
        "dimensions": [
            {"symbol": "T", "value": 0.5, "units": "in"},
        ],
    }
    plate_diff = format_snapshot_compare_diff_text(plate_old, plate_new)
    assert "d248 = 7 in" in plate_diff
    assert "d255 = 6 in" in plate_diff
    assert "Dimensions removed:" in plate_diff
    assert "Dimensions changed (same symbol): (none)" in plate_diff
    assert "→ 6" not in plate_diff
    plate_prompt = build_snapshot_compare_user_prompt(
        older_snapshot=plate_old,
        newer_snapshot=plate_new,
        older_revision="A.1",
        newer_revision="A.2",
    )
    assert "Computed differences" in plate_prompt
    assert "pairing two different symbols" not in plate_prompt
    assert "PATTERN 3" in plate_diff

    # Dimension lines show owning feature **name**, never the Creo feature id
    # in the owner slot (feature list lines may still end with (4460)).
    dim_owner_snap = {
        "identity": {"filename": "plate_3.prt", "model_type": "PART"},
        "features": [
            {"id": 4460, "name": "Extrude", "type": "PROTRUSION", "subtype": "Extrude"},
            {"id": 5000, "name": "Hole 1", "type": "HOLE"},
        ],
        "dimensions": [
            {
                "symbol": "d258",
                "value": 95.461,
                "units": "in",
                "feature_id": 4460,
            },
            {
                "symbol": "d259",
                "value": 21.7,
                "units": "in",
                "feature_id": 4460,
            },
            {
                "symbol": "d300",
                "value": 1,
                "units": "in",
                "feature_id": 5000,
            },
        ],
    }
    dim_owner_text = format_snapshot_compare_text(dim_owner_snap)
    assert "d258 (Extrude) = 95.461 in" in dim_owner_text
    assert "d259 (Extrude) = 21.7 in" in dim_owner_text
    assert "d300 (Hole 1) = 1 in" in dim_owner_text
    assert "Extrude (4460)" in dim_owner_text  # feature row id suffix
    assert "d258 (4460)" not in dim_owner_text
    assert "d259 (4460)" not in dim_owner_text
    assert "d300 (5000)" not in dim_owner_text
    assert "feature_id" not in dim_owner_text
    # feature_name alone (no id lookup) also works after gather stamp.
    named_only = format_snapshot_compare_text(
        {
            "identity": {"filename": "plate_3.prt", "model_type": "PART"},
            "features": [],
            "dimensions": [
                {
                    "symbol": "d258",
                    "value": 95.461,
                    "units": "in",
                    "feature_name": "Extrude",
                }
            ],
        }
    )
    assert "d258 (Extrude) = 95.461 in" in named_only
    dim_owner_diff = format_snapshot_compare_diff_text(
        dim_owner_snap,
        {
            **dim_owner_snap,
            "dimensions": [
                {"symbol": "d258", "value": 95.461, "units": "in", "feature_id": 4460},
                {"symbol": "d259", "value": 21.7, "units": "in", "feature_id": 4460},
            ],
        },
    )
    assert "d300 (Hole 1) = 1 in" in dim_owner_diff
    assert "d300 (5000)" not in dim_owner_diff

    # Assemblies: Structure/BOM drives component add/remove (Features omit COMPONENT).
    asm_old = {
        "identity": {"filename": "conveyor.asm", "model_type": "ASSEMBLY"},
        "features": [
            {"name": "ACS2", "type": "COORDINATE SYSTEM"},
            {"name": "DEFAULT_CSYS", "type": "COORDINATE SYSTEM"},
        ],
        "bom": [
            {
                "filename": "conveyor.asm",
                "quantity": 1,
                "dependency_type": "ASSEMBLY_ROOT",
                "children": [
                    {
                        "filename": "PLATE_3.prt",
                        "quantity": 1,
                        "dependency_type": "ASSEMBLY_MEMBER",
                        "children": [],
                    },
                    {
                        "filename": "SQUARE_TUBE_1.prt",
                        "quantity": 2,
                        "dependency_type": "ASSEMBLY_MEMBER",
                        "children": [],
                    },
                    {
                        "filename": "HEXBOLT-1-8X6_75.prt",
                        "quantity": 50,
                        "dependency_type": "ASSEMBLY_MEMBER",
                        "children": [],
                    },
                ],
            }
        ],
    }
    asm_new = {
        "identity": {"filename": "conveyor.asm", "model_type": "ASSEMBLY"},
        "features": [
            {"name": "ACS2", "type": "COORDINATE SYSTEM"},
            {"name": "DEFAULT_CSYS", "type": "COORDINATE SYSTEM"},
        ],
        "bom": [
            {
                "filename": "conveyor.asm",
                "quantity": 1,
                "dependency_type": "ASSEMBLY_ROOT",
                "children": [
                    {
                        "filename": "SQUARE_TUBE_1.prt",
                        "quantity": 1,
                        "dependency_type": "ASSEMBLY_MEMBER",
                        "children": [],
                    },
                    {
                        "filename": "HEXBOLT-1-8X6_75.prt",
                        "quantity": 50,
                        "dependency_type": "ASSEMBLY_MEMBER",
                        "children": [],
                    },
                ],
            }
        ],
    }
    asm_outline = format_snapshot_compare_text(asm_old)
    assert "Structure:" in asm_outline
    assert "PLATE_3.prt" in asm_outline
    assert "SQUARE_TUBE_1.prt × 2" in asm_outline
    assert "Assembly features (non-component):" in asm_outline
    asm_diff = format_snapshot_compare_diff_text(asm_old, asm_new)
    assert "Components removed:" in asm_diff
    assert "PLATE_3.prt" in asm_diff
    assert "Components quantity changed:" in asm_diff
    assert "SQUARE_TUBE_1.prt: × 2 → × 1" in asm_diff
    assert "Components removed:" in asm_diff
    assert "trust Structure/BOM" not in asm_diff
    asm_prompt = build_snapshot_compare_user_prompt(
        older_snapshot=asm_old,
        newer_snapshot=asm_new,
        older_revision="A.1",
        newer_revision="A.2",
    )
    assert "=== Computed differences ===" in asm_prompt
    assert "prefer components removed/added" not in asm_prompt.lower()
    slim_asm = slim_snapshot_for_compare(asm_old)
    assert slim_asm.get("bom")
    assert slim_asm["bom"][0]["filename"] == "conveyor.asm"

    # Check In gather FullName vs tip Structure name — not remove+add.
    skel_old = {
        "identity": {"filename": "conveyor.asm", "model_type": "ASSEMBLY"},
        "features": [
            {"name": "ACS0", "type": "COORDINATE SYSTEM"},
            {"name": "ACS1", "type": "COORDINATE SYSTEM"},
        ],
        "bom": [
            {
                "filename": "conveyor.asm",
                "quantity": 1,
                "dependency_type": "ASSEMBLY_ROOT",
                "children": [
                    {
                        "filename": "CONVEYOR_SKEL<<CONVEYOR>.prt",
                        "quantity": 1,
                        "dependency_type": "ASSEMBLY_MEMBER",
                        "children": [],
                    },
                    {
                        "filename": "ENDCAP_SQUARE_2.prt",
                        "quantity": 6,
                        "dependency_type": "ASSEMBLY_MEMBER",
                        "children": [],
                    },
                ],
            }
        ],
    }
    skel_new = {
        "identity": {"filename": "conveyor.asm", "model_type": "ASSEMBLY"},
        "features": [],  # pending gather often thinner — must not invent feature removes
        "bom": [
            {
                "filename": "conveyor.asm",
                "quantity": 1,
                "dependency_type": "ASSEMBLY_ROOT",
                "children": [
                    {
                        "filename": "CONVEYOR_SKEL.prt",
                        "quantity": 1,
                        "dependency_type": "ASSEMBLY_MEMBER",
                        "children": [],
                    },
                    {
                        "filename": "ENDCAP_SQUARE_2.prt",
                        "quantity": 5,
                        "dependency_type": "ASSEMBLY_MEMBER",
                        "children": [],
                    },
                ],
            }
        ],
    }
    skel_diff = format_snapshot_compare_diff_text(skel_old, skel_new)
    assert "CONVEYOR_SKEL" in format_snapshot_compare_text(skel_old)
    assert "<<" not in format_snapshot_compare_text(skel_old)
    assert "Components removed: (none)" in skel_diff
    assert "Components added: (none)" in skel_diff
    assert "ENDCAP_SQUARE_2.prt: × 6 → × 5" in skel_diff
    # Both sides have Structure → do not invent feature removes from thinner pending.
    assert "Features removed: (none)" in skel_diff
    assert "ACS0" not in skel_diff

    # Check In + Compare share prepare → outline/diff for parts and drawings too.
    assert "def prepare_snapshot_for_compare(" in (
        ROOT / "src" / "creopdm" / "ai_prompts.py"
    ).read_text(encoding="utf-8")
    part_a = {
        "identity": {"filename": "plate_3.prt", "model_type": "PART"},
        "features": [{"name": "Extrude", "type": "PROTRUSION"}],
        "dimensions": [{"symbol": "d1", "value": 10, "units": "in"}],
    }
    part_b = {
        "identity": {"filename": "plate_3.prt", "model_type": "PART"},
        "features": [{"name": "Extrude", "type": "PROTRUSION"}],
        "dimensions": [{"symbol": "d1", "value": 12, "units": "in"}],
    }
    part_prompt = build_snapshot_compare_user_prompt(
        older_snapshot=part_a,
        newer_snapshot=part_b,
        older_revision="A.1",
        newer_revision="pending",
    )
    assert "d1" in part_prompt and "10" in part_prompt and "12" in part_prompt
    drw_a = {
        "identity": {"filename": "plate_3.drw", "model_type": "DRAWING"},
        "features": [
            {"name": "VIEW_1", "type": "VIEW"},
            {"name": "VIEW_2", "type": "VIEW"},
        ],
        "capture": {"sheet_count": 1},
    }
    drw_b = {
        "identity": {"filename": "plate_3.drw", "model_type": "DRAWING"},
        "features": [{"name": "VIEW_1", "type": "VIEW"}],
        "capture": {"sheet_count": 1},
    }
    drw_prompt = build_snapshot_compare_user_prompt(
        older_snapshot=drw_a,
        newer_snapshot=drw_b,
        older_revision="A.1",
        newer_revision="pending",
    )
    assert "Views:" in drw_prompt
    assert "VIEW_2" in drw_prompt
    assert prepare_snapshot_for_compare(part_a)["identity"]["filename"] == "plate_3.prt"
    svc = (
        ROOT / "src" / "creopdm" / "services" / "ai_snapshot_service.py"
    ).read_text(encoding="utf-8")
    assert "prepare_snapshot_for_compare" in svc
    assert "Same Ask AI path as compare_with_ollama" in svc

    # Old snapshots without bom still outline Structure via version.bom_json.
    class _Ver:
        bom_json = (
            '[{"filename":"conveyor.asm","quantity":1,'
            '"dependency_type":"ASSEMBLY_ROOT","children":'
            '[{"filename":"GONE.prt","quantity":1,'
            '"dependency_type":"ASSEMBLY_MEMBER","children":[]}]}]'
        )

    merged = _snapshot_with_bom_fallback(
        {"identity": {"filename": "conveyor.asm", "model_type": "ASSEMBLY"}, "features": []},
        _Ver(),  # type: ignore[arg-type]
    )
    assert merged is not None
    assert merged.get("bom")
    assert "GONE.prt" in format_snapshot_compare_text(merged)


@requires_git
def test_ai_snapshot_api_upsert_list_and_detail_tab(client, repo_parent, tmp_path):
    """POST tip snapshot, list by rev, GET returns JSON; one snap → pending Compare Revisions."""
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
    assert "Features:" in (body.get("outline") or "")
    assert "Extrude 1" in (body.get("outline") or "")
    assert "d0 (Extrude 1) = 6 mm" in (body.get("outline") or "")
    assert '"id":' not in (body.get("outline") or "")

    got_get = client.get(
        f"/api/objects/{object_id}/ai-snapshot?version={version_id}"
    )
    assert got_get.status_code == 200, got_get.text
    assert "Extrude 1" in (got_get.json().get("outline") or "")

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
    # One snapshot — Compare Revisions (pending NEW); not a "Snapshot" tab label.
    assert 'data-tab="snapshot"' in detail.text
    assert 'data-tab="snapshot">Compare Revisions</button>' in detail.text
    assert 'data-tab="snapshot">Snapshot</button>' not in detail.text
    assert 'id="panel-snapshot"' in detail.text
    assert 'data-mode="pending"' in detail.text
    assert 'data-workspace-pending=' in detail.text

    ctx = client.app.state.ctx
    with ctx.session_factory() as db:
        svc = AiSnapshotService(ctx.objects)
        got = svc.get(db, object_id, version_id)
        assert got.has_snapshot is True
        assert got.snapshot["dimensions"][0]["value"] == 8.0
        listed_svc = svc.list_for_object(db, object_id)
        assert any(item.has_snapshot for item in listed_svc.items)
        assert svc.count_with_snapshot(db, object_id) == 1


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
    """Compare endpoint loads both snapshots, sends prompt + outlines to Ollama, returns summary."""
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

    detail_two = client.get(f"/products/{product_id}/objects/{object_id}")
    assert detail_two.status_code == 200, detail_two.text
    assert 'data-tab="snapshot">Compare Revisions</button>' in detail_two.text
    assert 'data-tab="snapshot">Snapshot</button>' not in detail_two.text
    assert 'id="panel-snapshot"' in detail_two.text
    assert 'data-mode="compare"' in detail_two.text
    assert 'id="ai-snapshot-scroll"' in detail_two.text

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
        assert "=== OLD snapshot" in messages[1]["content"]
        assert "=== NEW snapshot" in messages[1]["content"]
        assert "=== Computed differences ===" in messages[1]["content"]
        assert "Do not swap them" not in messages[1]["content"]
        assert "following your instructions" not in messages[1]["content"]
        assert "d0 = 5 mm" in messages[1]["content"]
        assert "d0 = 7.5 mm" in messages[1]["content"]
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
        assert "=== OLD snapshot" in messages[1]["content"]
        assert "=== NEW snapshot (A.2) ===" in messages[1]["content"]
        assert "=== Computed differences ===" in messages[1]["content"]
        assert "Do not swap them" not in messages[1]["content"]
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

    assert client.put("/api/settings", json={"ai_enabled": False}).status_code == 200
    blocked = client.post(
        f"/api/objects/{object_id}/ai-snapshot/compare-pending",
        json={
            "newer_display_revision": "A.2",
            "newer_snapshot": {
                "identity": {"filename": "block.prt", "model_type": "PART"},
                "features": [],
                "dimensions": [{"symbol": "width", "value": 100.0, "units": "mm"}],
            },
        },
    )
    assert blocked.status_code == 400, blocked.text
    assert "AI features are turned off" in blocked.text


@requires_git
def test_ai_snapshot_outline_formats_gathered_without_ollama(
    client, repo_parent, tmp_path
):
    """Live NEW path: format client gather as outline text (no save, no Ollama)."""
    product = client.post(
        "/api/products",
        json={"name": "Snap Outline", "number": "SNAP-OUT"},
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["uuid"]
    prt = tmp_path / "plate.prt.1"
    prt.write_bytes(b"FAKE CREO PART")
    added = client.post(
        f"/api/products/{product_id}/objects",
        files={"file": ("plate.prt.1", prt.read_bytes(), "application/octet-stream")},
        data={"comment": "v1"},
    )
    assert added.status_code == 201, added.text
    object_id = added.json()["uuid"]

    outlined = client.post(
        f"/api/objects/{object_id}/ai-snapshot/outline",
        json={
            "display_revision": "A.2",
            "snapshot": {
                "identity": {"filename": "plate.prt", "model_type": "PART"},
                "features": [{"id": 10, "name": "EXTRUDE", "type": "Extrude"}],
                "dimensions": [{"symbol": "d0", "value": 42.0, "units": "mm"}],
                "parameters": [],
            },
        },
    )
    assert outlined.status_code == 200, outlined.text
    body = outlined.json()
    assert body["display_revision"] == "A.2"
    assert "EXTRUDE" in body["outline"]
    assert "d0" in body["outline"] or "42" in body["outline"]

    empty = client.post(
        f"/api/objects/{object_id}/ai-snapshot/outline",
        json={"display_revision": "A.2", "snapshot": {}},
    )
    assert empty.status_code == 422 or empty.status_code == 400


def test_checkin_batch_comment_prompt_and_fallback():
    """Multi-file Ask AI builds one user prompt and a bullet fallback."""
    from creopdm.ai_prompts import (
        CHECKIN_BATCH_COMMENT_SYSTEM,
        build_checkin_batch_comment_user_prompt,
        format_checkin_batch_comment_fallback,
    )

    notes = [
        {"filename": "shaft.prt.2", "summary": "Increased length d0 from 10 to 12."},
        {"filename": "cover.prt.3", "summary": "Added ROUND feature."},
    ]
    prompt = build_checkin_batch_comment_user_prompt(notes)
    assert "=== shaft.prt.2 ===" in prompt
    assert "Increased length d0 from 10 to 12." in prompt
    assert "=== cover.prt.3 ===" in prompt
    assert "Added ROUND feature." in prompt
    assert "one check-in comment" in prompt.lower()
    assert "Reply with only the comment text" in CHECKIN_BATCH_COMMENT_SYSTEM

    fallback = format_checkin_batch_comment_fallback(notes)
    assert fallback.startswith("Check-in summary:")
    assert "- shaft.prt.2: Increased length d0 from 10 to 12." in fallback
    assert "- cover.prt.3: Added ROUND feature." in fallback

    with pytest.raises(ValidationAppError):
        build_checkin_batch_comment_user_prompt([])
    with pytest.raises(ValidationAppError):
        format_checkin_batch_comment_fallback([{"filename": "x.prt", "summary": ""}])


@requires_git
def test_checkin_comment_synthesize_api(client, monkeypatch):
    """Product synthesize endpoint: single passthrough, multi Ollama, fallback, AI off."""
    product = client.post(
        "/api/products",
        json={"name": "Batch Ask AI", "number": "BATCH-AI"},
    )
    assert product.status_code == 201, product.text
    product_id = product.json()["uuid"]

    saved = client.put(
        "/api/settings",
        json={
            "ollama_base_url": "http://michael-desktop:11434",
            "ollama_model": "gemma4:latest",
            "ai_enabled": True,
        },
    )
    assert saved.status_code == 200, saved.text

    single = client.post(
        f"/api/products/{product_id}/ai/checkin-comment-synthesize",
        json={
            "notes": [
                {
                    "filename": "only.prt.2",
                    "summary": "Changed d0 from 1 to 2.",
                }
            ]
        },
    )
    assert single.status_code == 200, single.text
    assert single.json()["summary"] == "Changed d0 from 1 to 2."
    assert single.json()["fallback"] is False

    captured: dict = {}

    def fake_chat(base_url, model, messages, *, timeout_s=300.0):
        captured["messages"] = messages
        return "Updated shaft length and added a round on the cover."

    monkeypatch.setattr(
        "creopdm.services.ai_snapshot_service.chat_ollama",
        fake_chat,
    )
    multi = client.post(
        f"/api/products/{product_id}/ai/checkin-comment-synthesize",
        json={
            "notes": [
                {"filename": "shaft.prt.2", "summary": "Increased length."},
                {"filename": "cover.prt.3", "summary": "Added ROUND."},
            ]
        },
    )
    assert multi.status_code == 200, multi.text
    body = multi.json()
    assert body["summary"] == "Updated shaft length and added a round on the cover."
    assert body["fallback"] is False
    assert body["model"] == "gemma4:latest"
    assert captured["messages"][0]["content"].startswith("You write a single CreoPDM")
    assert "=== shaft.prt.2 ===" in captured["messages"][1]["content"]

    def boom(*_a, **_k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(
        "creopdm.services.ai_snapshot_service.chat_ollama",
        boom,
    )
    fell = client.post(
        f"/api/products/{product_id}/ai/checkin-comment-synthesize",
        json={
            "notes": [
                {"filename": "shaft.prt.2", "summary": "Increased length."},
                {"filename": "cover.prt.3", "summary": "Added ROUND."},
            ]
        },
    )
    assert fell.status_code == 200, fell.text
    fell_body = fell.json()
    assert fell_body["fallback"] is True
    assert fell_body["summary"].startswith("Check-in summary:")
    assert "shaft.prt.2" in fell_body["summary"]

    empty = client.post(
        f"/api/products/{product_id}/ai/checkin-comment-synthesize",
        json={"notes": []},
    )
    assert empty.status_code == 422, empty.text

    assert client.put("/api/settings", json={"ai_enabled": False}).status_code == 200
    blocked = client.post(
        f"/api/products/{product_id}/ai/checkin-comment-synthesize",
        json={
            "notes": [
                {"filename": "a.prt", "summary": "x"},
                {"filename": "b.prt", "summary": "y"},
            ]
        },
    )
    assert blocked.status_code == 400, blocked.text
    assert "AI features are turned off" in blocked.text
