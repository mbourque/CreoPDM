"""Background vault → Dependency indexing for Where Used."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from creopdm.logging_setup import get_logger
from creopdm.services.metadata_service import MetadataService

logger = get_logger("where_used_index")

# Start background Where Used after any successful Add (1+ files).
WHERE_USED_AUTO_INDEX_MIN_FILES = 1
_CHUNK = 20


@dataclass
class WhereUsedIndexStatus:
    product_id: str
    state: str = "idle"  # idle | queued | running | done | error
    parents_total: int = 0
    parents_done: int = 0
    edges_added: int = 0
    edges_existing: int = 0
    parents_missing_vault: int = 0
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None

    @property
    def done(self) -> bool:
        return self.state in {"done", "error", "idle"}


@dataclass
class WhereUsedIndexJobs:
    """One background index thread per product (re-entrant start is a no-op)."""

    session_factory: sessionmaker[Session]
    metadata: MetadataService
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _status: dict[str, WhereUsedIndexStatus] = field(default_factory=dict)

    def get(self, product_uuid: str) -> WhereUsedIndexStatus:
        with self._lock:
            current = self._status.get(product_uuid)
            if current is None:
                return WhereUsedIndexStatus(product_id=product_uuid, state="idle")
            return WhereUsedIndexStatus(
                product_id=current.product_id,
                state=current.state,
                parents_total=current.parents_total,
                parents_done=current.parents_done,
                edges_added=current.edges_added,
                edges_existing=current.edges_existing,
                parents_missing_vault=current.parents_missing_vault,
                error=current.error,
                started_at=current.started_at,
                finished_at=current.finished_at,
            )

    def start(self, product_uuid: str) -> WhereUsedIndexStatus:
        with self._lock:
            current = self._status.get(product_uuid)
            if current is not None and current.state in {"queued", "running"}:
                return self.get(product_uuid)
            status = WhereUsedIndexStatus(
                product_id=product_uuid,
                state="queued",
                started_at=time.time(),
            )
            self._status[product_uuid] = status
        thread = threading.Thread(
            target=self._run,
            args=(product_uuid,),
            name=f"where-used-{product_uuid[:8]}",
            daemon=True,
        )
        thread.start()
        return self.get(product_uuid)

    def maybe_start_after_add(self, product_uuid: str, added_count: int) -> WhereUsedIndexStatus | None:
        if added_count < WHERE_USED_AUTO_INDEX_MIN_FILES:
            return None
        return self.start(product_uuid)

    def _run(self, product_uuid: str) -> None:
        with self._lock:
            status = self._status.get(product_uuid)
            if status is None:
                return
            status.state = "running"
        edges_added = 0
        edges_existing = 0
        missing = 0
        offset = 0
        try:
            while True:
                # Short DB session: list + write only. Vault byte scans happen inside
                # rebuild_where_used_from_vault without holding a write lock.
                session = self.session_factory()
                try:
                    result = self.metadata.rebuild_where_used_from_vault(
                        session,
                        product_uuid,
                        offset=offset,
                        limit=_CHUNK,
                    )
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
                finally:
                    session.close()

                edges_added += result.edges_added
                edges_existing += result.edges_existing
                missing += result.parents_missing_vault
                offset = result.next_offset
                with self._lock:
                    status = self._status.get(product_uuid)
                    if status is None:
                        return
                    status.parents_total = result.parents_total
                    status.parents_done = min(offset, result.parents_total)
                    status.edges_added = edges_added
                    status.edges_existing = edges_existing
                    status.parents_missing_vault = missing
                # Yield so other requests can use SQLite between chunks.
                time.sleep(0.05)
                if result.done:
                    break
            with self._lock:
                status = self._status.get(product_uuid)
                if status is None:
                    return
                status.state = "done"
                status.finished_at = time.time()
            logger.info(
                "Where Used index done for %s: +%s edges (%s existing), %s missing vault",
                product_uuid,
                edges_added,
                edges_existing,
                missing,
            )
        except Exception as exc:
            logger.exception("Where Used index failed for %s", product_uuid)
            with self._lock:
                status = self._status.get(product_uuid)
                if status is None:
                    return
                status.state = "error"
                status.error = str(exc) or exc.__class__.__name__
                status.finished_at = time.time()


__all__ = [
    "WHERE_USED_AUTO_INDEX_MIN_FILES",
    "WhereUsedIndexJobs",
    "WhereUsedIndexStatus",
]
