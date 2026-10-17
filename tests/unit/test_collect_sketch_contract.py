"""Collect all / Rebuild: the sketch reaches the server, and a skipped tip is not "saved"."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
META_JS = ROOT / "src" / "creopdm" / "static" / "js" / "metadata.js"


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_collect_all_posts_the_sketch_with_the_other_metadata():
    # Regression: only pushCreoMetadataForItems sent `sketch`; Collect all / Rebuild build
    # their own body in metadata.js, so a collected sketch was dropped before the server.
    js = META_JS.read_text(encoding="utf-8")
    push = _between(js, "async function pushOneCreoMetadataTarget(", "async function flushPendingMetadataErase(")
    assert 'sketch: snapshot.sketch && typeof snapshot.sketch === "object"' in push
    assert "if (!body.sketch) delete body.sketch;" in push


def test_a_tip_left_for_local_changes_is_not_counted_as_saved():
    # Regression: "left local modifications" returned ok → captured += 1, so a sketch with a
    # newer local save (test-sec.sec.1) showed "1 saved" while nothing was collected.
    js = META_JS.read_text(encoding="utf-8")
    loop = _between(js, "async function runMetadataCollectLoop(", "async function ")
    assert 'String(result.reason || "") === "left local modifications"' in loop
    assert "leftLocal += 1" in loop
    assert "} else if (result.ok) {" in loop
    # Reported to the user with the way out, in progress and in the final message.
    assert "unsaved local changes" in loop
    assert "Check In first" in loop


APP_JS = ROOT / "src" / "creopdm" / "static" / "js" / "app.js"


def test_a_numbered_local_copy_with_the_vault_bytes_is_collected_not_skipped():
    # Regression: right after Add the agent workspace keeps test-sec.sec.1 while the vault
    # tip is test-sec.sec (same bytes). "Higher .N = unsaved" skipped it silently and there
    # was nothing to Check In, so a sketch could never be collected.
    js = META_JS.read_text(encoding="utf-8")
    push = _between(js, "async function pushOneCreoMetadataTarget(", "async function flushPendingMetadataErase(")
    assert "collectPathIsUnsavedTip(filePath, target.filename)" in push
    assert "await localTipMatchesVault(filePath, target)" in push
    helper = _between(js, "async function localTipMatchesVault(", "async function pushOneCreoMetadataTarget(")
    assert "hashAgentCachePaths(productId, [localRel])" in helper
    assert "target?.contentHash" in helper
    # A missing hash keeps the old behaviour (treated as a real local edit).
    assert "return false;" in helper
    assert "contentHash: String(row.current_version?.content_hash" in js
    assert "const hashAgentCachePaths = shell.hashAgentCachePaths;" in js
    assert "    hashAgentCachePaths," in APP_JS.read_text(encoding="utf-8")
