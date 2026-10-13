"""One-off / resumable vault thumbnail backfill (server-side, no Creo).

Usage (from repo root, with CREOPDM_DATA_DIR set like the service):

  python scripts/backfill_thumbnails.py

Logs found / missing / failed counts per .prt / .asm / .drw.
Skips content_hash rows that already exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = ROOT / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from creopdm.app import build_context  # noqa: E402
from creopdm.config import ConfigManager  # noqa: E402
from creopdm.logging_setup import get_logger, setup_logging  # noqa: E402

logger = get_logger("backfill_thumbnails")


def main() -> int:
    setup_logging()
    ctx = build_context(ConfigManager())
    if ctx.thumbnails is None:
        logger.error("Thumbnail service not configured")
        return 1
    totals = ctx.thumbnails.backfill_all_products(ctx.session_factory)
    logger.info(
        "Thumbnail backfill complete: processed=%s skipped_existing=%s "
        "found=%s missing=%s failed=%s",
        totals.processed,
        totals.skipped_existing,
        totals.found,
        totals.missing,
        totals.failed,
    )
    print(
        "found",
        totals.found,
        "missing",
        totals.missing,
        "failed",
        totals.failed,
        "skipped",
        totals.skipped_existing,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
