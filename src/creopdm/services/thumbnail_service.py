"""Store and serve Creo embedded thumbnails (vault file bytes only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from creopdm.logging_setup import get_logger
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product
from creopdm.models.thumbnail import Thumbnail
from creopdm.creo.file_manager import CreoFileManager
from creopdm.utils.creo_thumbnail import (
    extract_thumbnail,
    is_thumbnail_candidate,
    jpeg_dimensions,
)
from creopdm.services.workspace_service import WorkspaceService

logger = get_logger("thumbnails")

_CHUNK = 40


@dataclass
class ThumbnailBackfillCounts:
    found: dict[str, int] = field(default_factory=lambda: {".prt": 0, ".asm": 0, ".drw": 0})
    missing: dict[str, int] = field(default_factory=lambda: {".prt": 0, ".asm": 0, ".drw": 0})
    failed: dict[str, int] = field(default_factory=lambda: {".prt": 0, ".asm": 0, ".drw": 0})
    skipped_existing: int = 0
    processed: int = 0

    def bump(self, bucket: dict[str, int], ext: str) -> None:
        key = ext if ext in bucket else ".prt"
        bucket[key] = bucket.get(key, 0) + 1


class ThumbnailService:
    def __init__(self, workspaces: WorkspaceService) -> None:
        self._workspaces = workspaces

    def get_by_hash(self, session: Session, content_hash: str) -> Thumbnail | None:
        digest = (content_hash or "").strip().lower()
        if not digest:
            return None
        return session.get(Thumbnail, digest)

    def get_for_object_tip(self, session: Session, obj: EngineeringObject) -> Thumbnail | None:
        version = obj.current_version
        if version is None or not version.content_hash:
            return None
        return self.get_by_hash(session, version.content_hash)

    def ensure_from_path(
        self,
        session: Session,
        *,
        content_hash: str,
        path: Path,
        filename: str = "",
    ) -> str:
        """Extract and store if missing. Returns found|missing|skipped|failed."""
        digest = (content_hash or "").strip().lower()
        if not digest:
            return "failed"
        if session.get(Thumbnail, digest) is not None:
            return "skipped"
        try:
            jpeg = extract_thumbnail(path)
        except Exception:
            logger.debug("thumbnail extract raised for %s", path, exc_info=True)
            return "failed"
        if not jpeg:
            return "missing"
        dims = jpeg_dimensions(jpeg) or (0, 0)
        row = Thumbnail(
            content_hash=digest,
            mime="image/jpeg",
            width=int(dims[0]),
            height=int(dims[1]),
            bytes=jpeg,
        )
        try:
            with session.begin_nested():
                session.add(row)
        except Exception:
            logger.debug("thumbnail store failed for %s", digest[:12], exc_info=True)
            return "failed"
        return "found"

    def extract_for_product_chunk(
        self,
        session: Session,
        product: Product,
        *,
        offset: int = 0,
        limit: int = _CHUNK,
    ) -> tuple[ThumbnailBackfillCounts, int, bool]:
        """Process a chunk of CAD tips. Returns (counts, next_offset, done)."""
        counts = ThumbnailBackfillCounts()
        rows = session.scalars(
            select(EngineeringObject)
            .where(EngineeringObject.product_id == product.id)
            .options(joinedload(EngineeringObject.current_version))
            .order_by(EngineeringObject.id)
        ).all()
        tips = [
            row
            for row in rows
            if is_thumbnail_candidate(row.filename or "")
            and row.current_version is not None
            and (row.current_version.content_hash or "").strip()
        ]
        total = len(tips)
        start = max(0, int(offset))
        take = max(1, min(int(limit), 80))
        chunk = tips[start : start + take]
        if not chunk:
            return counts, start, True

        for obj in chunk:
            counts.processed += 1
            version = obj.current_version
            assert version is not None
            logical = CreoFileManager.normalize_creo_filename(obj.filename or "")
            suffix = Path(logical).suffix.lower() or ".prt"
            if suffix not in {".prt", ".asm", ".drw"}:
                suffix = ".prt"
            try:
                path = self._workspaces.locate_content(product, obj)
            except Exception:
                counts.bump(counts.failed, suffix)
                continue
            result = self.ensure_from_path(
                session,
                content_hash=version.content_hash,
                path=path,
                filename=obj.filename or "",
            )
            if result == "found":
                counts.bump(counts.found, suffix)
            elif result == "missing":
                counts.bump(counts.missing, suffix)
            elif result == "skipped":
                counts.skipped_existing += 1
            else:
                counts.bump(counts.failed, suffix)

        next_offset = start + len(chunk)
        return counts, next_offset, next_offset >= total

    def backfill_all_products(
        self,
        session_factory,
        *,
        batch_size: int = _CHUNK,
    ) -> ThumbnailBackfillCounts:
        """Resumable vault-wide backfill; skips hashes that already have a row."""
        totals = ThumbnailBackfillCounts()
        session = session_factory()
        try:
            products = list(session.scalars(select(Product).order_by(Product.id)).all())
        finally:
            session.close()

        for product in products:
            offset = 0
            while True:
                session = session_factory()
                try:
                    # Re-load product in this session
                    prod = session.get(Product, product.id)
                    if prod is None:
                        break
                    chunk_counts, offset, done = self.extract_for_product_chunk(
                        session, prod, offset=offset, limit=batch_size
                    )
                    session.commit()
                except Exception:
                    session.rollback()
                    logger.exception("thumbnail backfill failed for product %s", product.uuid)
                    break
                finally:
                    session.close()

                for key in (".prt", ".asm", ".drw"):
                    totals.found[key] = totals.found.get(key, 0) + chunk_counts.found.get(key, 0)
                    totals.missing[key] = totals.missing.get(key, 0) + chunk_counts.missing.get(
                        key, 0
                    )
                    totals.failed[key] = totals.failed.get(key, 0) + chunk_counts.failed.get(key, 0)
                totals.skipped_existing += chunk_counts.skipped_existing
                totals.processed += chunk_counts.processed
                logger.info(
                    "Thumbnail backfill %s offset=%s found=%s missing=%s failed=%s skipped=%s",
                    product.uuid[:8],
                    offset,
                    chunk_counts.found,
                    chunk_counts.missing,
                    chunk_counts.failed,
                    chunk_counts.skipped_existing,
                )
                if done:
                    break
        return totals


def thumbnail_row_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(Thumbnail)) or 0)
