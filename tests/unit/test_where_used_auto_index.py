"""Where Used auto-index after Add: always start; UI refreshes when done."""

from __future__ import annotations

from pathlib import Path

from creopdm.services.where_used_index_jobs import (
    WHERE_USED_AUTO_INDEX_MIN_FILES,
    WhereUsedIndexJobs,
    WhereUsedIndexStatus,
)


def test_where_used_auto_index_starts_after_any_successful_add():
    """Any Add with 1+ files must kick background indexing (not only bulk ≥50)."""
    assert WHERE_USED_AUTO_INDEX_MIN_FILES == 1
    started: list[str] = []

    class GateOnly(WhereUsedIndexJobs):
        def start(self, product_uuid: str) -> WhereUsedIndexStatus:
            started.append(product_uuid)
            return WhereUsedIndexStatus(product_id=product_uuid, state="queued")

    jobs = object.__new__(GateOnly)
    assert GateOnly.maybe_start_after_add(jobs, "prod-a", 0) is None
    assert started == []
    assert GateOnly.maybe_start_after_add(jobs, "prod-a", 1) is not None
    assert started == ["prod-a"]
    assert GateOnly.maybe_start_after_add(jobs, "prod-b", 12) is not None
    assert started == ["prod-a", "prod-b"]


def test_add_and_where_used_watch_refresh_files_when_index_done():
    """After indexing finishes, Files soft-reloads so Top Level can appear."""
    root = Path(__file__).resolve().parents[2]
    script = (root / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    watch = script.split("function watchWhereUsedIndex(", 1)[1].split(
        "async function resumeWhereUsedIndexWatch(", 1
    )[0]
    assert 'state === "done"' in watch
    assert "reloadPage()" in watch
    assert "creopdmNotice" in watch
    assert 'combined.where_used_index = "started"' in script
    docs = (root / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "start **Where Used** indexing in the background for any successful Add" in docs
