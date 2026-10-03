"""Where Used after Add: start once when Add finishes; refresh Files when done."""

from __future__ import annotations

from pathlib import Path

from creopdm.services.where_used_index_jobs import WHERE_USED_AUTO_INDEX_MIN_FILES


def test_add_endpoints_do_not_start_where_used_mid_chunk():
    """Chunked Add must not kick indexing per request (SQLite contention)."""
    root = Path(__file__).resolve().parents[2]
    products = (root / "src" / "creopdm" / "api" / "products.py").read_text(encoding="utf-8")
    assert "maybe_start_after_add" not in products
    assert WHERE_USED_AUTO_INDEX_MIN_FILES == 1


def test_add_starts_where_used_after_all_chunks_then_reloads_on_done():
    """Browser starts indexing after the last Add chunk; poll soft-reloads Files."""
    root = Path(__file__).resolve().parents[2]
    script = (root / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert "rebuild-where-used" in script
    assert "Start Where Used only after every Add chunk finished" in script
    watch = script.split("function watchWhereUsedIndex(", 1)[1].split(
        "async function resumeWhereUsedIndexWatch(", 1
    )[0]
    assert 'state === "done"' in watch
    assert "reloadPage()" in watch
    docs = (root / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "start **Where Used** indexing in the background for any successful Add" in docs
