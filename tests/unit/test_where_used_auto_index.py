"""Where Used after Add: wait under busy overlay, then one Files reload."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from creopdm.app import build_context
from creopdm.config import ConfigManager
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product
from creopdm.services.where_used_index_jobs import (
    WHERE_USED_AUTO_INDEX_MIN_FILES,
    WhereUsedIndexStatus,
)
from creopdm.utils.identity import StaticUserProvider


def _product_with_asm_parents(ctx, folder: str, name: str) -> str:
    vault = ctx.config.workspace_for_product(folder)
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "a.asm").write_bytes(b"asm")
    (vault / "b.asm").write_bytes(b"asm")
    (vault / "c.prt").write_bytes(b"prt")
    with ctx.session_factory() as db:
        product = Product(
            uuid=str(uuid.uuid4()),
            name=name,
            vault_folder=folder,
            repository_path=str(vault),
            default_branch="main",
        )
        db.add(product)
        db.flush()
        for filename, otype in (
            ("a.asm", "CREO_ASSEMBLY"),
            ("b.asm", "CREO_ASSEMBLY"),
            ("c.prt", "CREO_PART"),
        ):
            db.add(
                EngineeringObject(
                    uuid=str(uuid.uuid4()),
                    product_id=product.id,
                    name=filename,
                    filename=filename,
                    extension=filename.rsplit(".", 1)[-1],
                    object_type=otype,
                    relative_path=filename,
                )
            )
        db.commit()
        return product.uuid


def test_where_used_job_primes_parents_total_before_first_chunk(
    data_dir, identity: StaticUserProvider
):
    """Busy overlay needs 0 of N before the first slow vault scan returns."""
    ctx = build_context(ConfigManager(), users=identity)
    product_uuid = _product_with_asm_parents(ctx, "wu-prime", "WU Prime")

    started = ctx.where_used_index.start(product_uuid)
    # Start() primes synchronously — overlay can show 0 of N on the Start response.
    assert started.parents_total == 2, started
    assert started.state in {"queued", "running", "done"}
    # Wait so the daemon does not race the next test's DB teardown.
    for _ in range(200):
        if ctx.where_used_index.get(product_uuid).state in {"done", "error", "cancelled"}:
            break
        time.sleep(0.02)


def test_where_used_reentrant_start_primes_total(
    data_dir, identity: StaticUserProvider
):
    """Second Start (utilities JS) must not return parents_total=0 while priming."""
    ctx = build_context(ConfigManager(), users=identity)
    product_uuid = _product_with_asm_parents(ctx, "wu-reenter", "WU Reenter")
    jobs = ctx.where_used_index
    # Simulate BackgroundTask that created the job but has not primed yet.
    with jobs._lock:
        jobs._status[product_uuid] = WhereUsedIndexStatus(
            product_id=product_uuid,
            state="queued",
            started_at=time.time(),
            parents_total=0,
        )
    again = jobs.start(product_uuid)
    assert again.parents_total == 2, again
    jobs.cancel(product_uuid)


def test_cancel_where_used_api_is_wired():
    """Escape on busy overlay must hit DELETE so the overlay can clear."""
    root = Path(__file__).resolve().parents[2]
    products = (root / "src" / "creopdm" / "api" / "products.py").read_text(encoding="utf-8")
    assert "def cancel_rebuild_where_used" in products
    assert "ctx.where_used_index.cancel(product_id)" in products
    script = (root / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'method: "DELETE"' in script
    assert "forceClearBusy" in script
    assert "invokeBusyCancel" in script
    assert "recoverStuckBusyOverlay" in script
    # Hung Start used to ignore Escape — abort in-flight Start/poll fetches.
    assert "ac.abort()" in script or "signal.aborted" in script
    assert "__creopdmBusyCancelHandler" in script
    assert "signal: ac.signal" in script
    base = (root / "src" / "creopdm" / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'id="busy-overlay"' in base
    assert 'id="busy-cancel-btn"' not in base


def test_where_used_cancel_marks_job_cancelled(data_dir, identity: StaticUserProvider):
    """Cancel must flip status so the busy poll exits and the overlay can clear."""
    ctx = build_context(ConfigManager(), users=identity)
    product_uuid = str(uuid.uuid4())
    with ctx.session_factory() as db:
        db.add(
            Product(
                uuid=product_uuid,
                name="WU Cancel",
                vault_folder="wu-cancel",
                repository_path=str(ctx.config.workspace_for_product("wu-cancel")),
                default_branch="main",
            )
        )
        db.commit()
    started = ctx.where_used_index.start(product_uuid)
    assert started.state in {"queued", "running", "done"}
    ctx.where_used_index.cancel(product_uuid)
    status = ctx.where_used_index.get(product_uuid)
    # Already-finished jobs stay done; in-flight jobs become cancelled.
    assert status.state in {"cancelled", "done"}
    if status.state == "cancelled":
        assert status.error == "Cancelled."


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
    assert "async function runWhereUsedProgress(" in script
    # Nested under Add/zip busyDepth — do not clearBusy between import and index.
    assert "if (busyDepth > 0)" in script
    assert "no Files flash" in script
    # Reject stale/early done so the overlay cannot finish before parents_done catches up.
    assert "sawActive" in script
    assert "doneCount < total" in script
    add_tail = script.split("Keep the same busy overlay through Where Used", 1)[1].split(
        "} finally {\n      addInFlight = false;",
        1,
    )[0]
    assert "indexWhereUsedUnderBusy(productId)" in add_tail
    assert "canGatherCreoMetadata()" in add_tail
    assert "pushCreoMetadataForItems(metadataTargetsFromResult(out))" in add_tail
    # Where Used first; metadata only when Creo.JS is hosted (any count).
    assert add_tail.index("indexWhereUsedUnderBusy(productId)") < add_tail.index(
        "pushCreoMetadataForItems(metadataTargetsFromResult(out))"
    )
    assert "okN <= 50" not in add_tail
    assert "reloadPage({ keepBusy: true" in add_tail
    assert "indexing started in the background" not in add_tail
    # Compressed zip is a separate submit — must also index before refresh on one overlay.
    zip_submit = script.split('compressedForm?.addEventListener("submit"', 1)[1].split(
        "function useNativePicker(",
        1,
    )[0]
    assert "indexWhereUsedUnderBusy(productId)" in zip_submit
    assert "canGatherCreoMetadata()" in zip_submit
    assert "pushCreoMetadataForItems(metadataTargetsFromResult(result))" in zip_submit
    assert zip_submit.index("indexWhereUsedUnderBusy(productId)") < zip_submit.index(
        "pushCreoMetadataForItems(metadataTargetsFromResult(result))"
    )
    assert "import-zip" in zip_submit
    assert "pollZipImportJob" in zip_submit
    assert "zip-import/jobs" in zip_submit
    assert "jobFilesTotal" in zip_submit
    assert "One busy session for upload/import AND Where Used" in zip_submit
    assert "reloadPage({ keepBusy: true" in zip_submit
    assert "function metadataBusyText(" in script
    assert "Collecting Creo metadata…" in script
    assert "hostedCreoJS()" in script.split("function canGatherCreoMetadata(", 1)[1].split(
        "async function tryEraseModelsFromCreoSession(", 1
    )[0]
    docs = (root / "docs" / "user-interactions.md").read_text(encoding="utf-8")
    assert "keep the busy overlay and run **Where Used** indexing there" in docs
    assert "never clear the overlay and return to Files before indexing finishes" in docs
    assert "Same Where Used (+ Creo metadata when Connected) overlay step" in docs
    assert "only inside Creo" in docs
    assert "phase text" in docs
    assert "clear the overlay and return you to Files before Where Used finishes" in docs
    assert "cap metadata at 50 files" in docs
    assert "≤50" not in docs.split("| Collect Creo metadata |", 1)[1].split("|", 1)[0]

def test_await_where_used_rejects_unfinished_done_status():
    """Regression: zip refresh with ~every asm as Top Level when poll accepted early done."""
    root = Path(__file__).resolve().parents[2]
    script = (root / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    await_fn = script.split("async function awaitWhereUsedIndex(", 1)[1].split(
        "function watchWhereUsedIndex(",
        1,
    )[0]
    assert "let sawActive = false" in await_fn
    assert 'if (start && !sawActive)' in await_fn
    assert "doneCount < total" in await_fn
    assert "parentsTotal: total" in await_fn
    assert "parentsDone: doneCount" in await_fn