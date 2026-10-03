"""Product lock must not hang Delete forever after a cancelled Add."""

from __future__ import annotations

import threading
import time

import pytest

from creopdm.exceptions import ProductBusyError
from creopdm.services.lock_manager import ProductLockManager
from creopdm.services.where_used_index_jobs import WhereUsedIndexJobs, WhereUsedIndexStatus


def test_product_lock_acquire_timeout_raises_busy():
    locks = ProductLockManager()
    held = threading.Event()
    release = threading.Event()

    def holder():
        with locks.acquire("prod-busy"):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    assert held.wait(2)
    with pytest.raises(ProductBusyError):
        with locks.acquire("prod-busy", timeout=0.2):
            pass
    release.set()
    thread.join(2)


def test_where_used_cancel_stops_running_status():
    jobs = WhereUsedIndexJobs(session_factory=None, metadata=None)  # type: ignore[arg-type]
    jobs._status["prod-x"] = WhereUsedIndexStatus(
        product_id="prod-x",
        state="running",
        started_at=time.time(),
    )
    jobs.cancel("prod-x")
    assert jobs.get("prod-x").state == "cancelled"
    assert jobs._cancelled("prod-x") is True
