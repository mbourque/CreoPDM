"""Where Used after Add: wait under busy overlay, then one Files reload."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from creopdm.app import build_context
from creopdm.config import ConfigManager
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product
from creopdm.services.where_used_index_jobs import WHERE_USED_AUTO_INDEX_MIN_FILES
from creopdm.utils.identity import StaticUserProvider


def test_where_used_job_primes_parents_total_before_first_chunk(
    data_dir, identity: StaticUserProvider
):
    """Busy overlay needs 0 of N before the first slow vault scan returns."""
    ctx = build_context(ConfigManager(), users=identity)
    vault = ctx.config.workspace_for_product("wu-prime")
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "a.asm").write_bytes(b"asm")
    (vault / "b.asm").write_bytes(b"asm")
    (vault / "c.prt").write_bytes(b"prt")
    with ctx.session_factory() as db:
        product = Product(
            uuid=str(uuid.uuid4()),
            name="WU Prime",
            vault_folder="wu-prime",
            repository_path=str(vault),
            default_branch="main",
        )
        db.add(product)
        db.flush()
        for name, otype in (
            ("a.asm", "CREO_ASSEMBLY"),
            ("b.asm", "CREO_ASSEMBLY"),
            ("c.prt", "CREO_PART"),
        ):
            db.add(
                EngineeringObject(
                    uuid=str(uuid.uuid4()),
                    product_id=product.id,
                    name=name,
                    filename=name,
                    extension=name.rsplit(".", 1)[-1],
                    object_type=otype,
                    relative_path=name,
                )
            )
        db.commit()
        product_uuid = product.uuid

    started = ctx.where_used_index.start(product_uuid)
    # Start() primes synchronously — overlay can show 0 of N on the Start response.
    assert started.parents_total == 2, started
    assert started.state in {"queued", "running", "done"}
    # Wait so the daemon does not race the next test's DB teardown.
    for _ in range(200):
        if ctx.where_used_index.get(product_uuid).state in {"done", "error", "cancelled"}:
            break
        time.sleep(0.02)


def test_cancel_where_used_api_is_wired():
    """Busy Cancel must hit DELETE so the overlay can clear."""
    root = Path(__file__).resolve().parents[2]
    products = (root / "src" / "creopdm" / "api" / "products.py").read_text(encoding="utf-8")
    assert "def cancel_rebuild_where_used" in products
    assert "ctx.where_used_index.cancel(product_id)" in products
    script = (root / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'method: "DELETE"' in script
    assert "forceClearBusy" in script
    assert "invokeBusyCancel" in script
    assert "recoverStuckBusyOverlay" in script
    base = (root / "src" / "creopdm" / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'id="busy-cancel-btn"' in base


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
