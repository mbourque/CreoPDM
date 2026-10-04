"""Where Used after Add: wait under busy overlay, then one Files reload."""

from __future__ import annotations

from pathlib import Path

from creopdm.services.where_used_index_jobs import WHERE_USED_AUTO_INDEX_MIN_FILES


def test_add_endpoints_do_not_start_where_used_mid_chunk():
    """Chunked Add must not kick indexing per request (SQLite contention)."""
    root = Path(__file__).resolve().parents[2]
    products = (root / "src" / "creopdm" / "api" / "products.py").read_text(encoding="utf-8")
    assert "maybe_start_after_add" not in products
    assert WHERE_USED_AUTO_INDEX_MIN_FILES == 1


def test_add_runs_where_used_under_busy_overlay_then_reloads_once():
    """After the last Add chunk, overlay stays up for indexing; then one reload."""
    root = Path(__file__).resolve().parents[2]
    script = (root / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "async function awaitWhereUsedIndex(" in script
    assert "async function indexWhereUsedUnderBusy(" in script
    assert "Where Used only after every Add chunk finished" in script
    add_tail = script.split("Where Used only after every Add chunk finished", 1)[1].split(
        "} finally {\n      addInFlight = false;",
        1,
    )[0]
    assert "indexWhereUsedUnderBusy(productId)" in add_tail
    assert "reloadPage()" in add_tail
    assert "indexing started in the background" not in add_tail
    # Compressed zip is a separate submit — must also index before refresh.
    zip_submit = script.split('compressedForm?.addEventListener("submit"', 1)[1].split(
        "function useNativePicker(",
        1,
    )[0]
    assert "indexWhereUsedUnderBusy(productId)" in zip_submit
    assert "import-zip" in zip_submit
    assert "pollZipImportJob" in zip_submit
    assert "zip-import/jobs" in zip_submit
    docs = (root / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "keep the busy overlay and run **Where Used** indexing there" in docs
    assert "Same Where Used overlay step for **Add folder…**" in docs
    assert "phase text" in docs
