"""Diagnose missing Creo thumbnails: not embedded vs extractor miss.

Examples (venv active on CreoPDM host):

  # One vault tip:
  python scripts/diagnose_thumbnails.py /path/to/vaults/<uuid>/parts/shaft.prt

  # Several paths:
  python scripts/diagnose_thumbnails.py tip1.prt tip2.asm

  # Sample tips in a product that have no thumbnails row yet:
  python scripts/diagnose_thumbnails.py --product-uuid <uuid> --limit 20

Reasons:
  ok                 — extract works
  not_in_model       — no THMB_IMG_MAIN + nearby JPEG (Creo never stored one)
  jpeg_outside_window — marker exists, JPEG farther than extractor window (bug?)
  parse_rejected     — JPEG signature in window but size/SOF checks failed (bug?)
  file_too_small / missing_file / io_error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = ROOT / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

from creopdm.app import build_context  # noqa: E402
from creopdm.config import ConfigManager  # noqa: E402
from creopdm.logging_setup import setup_logging  # noqa: E402
from creopdm.models.thumbnail import Thumbnail  # noqa: E402
from creopdm.utils.creo_thumbnail import (  # noqa: E402
    diagnose_thumbnail,
    is_thumbnail_candidate,
)
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import joinedload  # noqa: E402
from creopdm.models.object import EngineeringObject  # noqa: E402
from creopdm.models.product import Product  # noqa: E402


def _paths_from_product(ctx, product_uuid: str, limit: int) -> list[Path]:
    session = ctx.session_factory()
    paths: list[Path] = []
    try:
        product = session.scalar(select(Product).where(Product.uuid == product_uuid))
        if product is None:
            print(f"product not found: {product_uuid}", file=sys.stderr)
            return []
        rows = session.scalars(
            select(EngineeringObject)
            .where(EngineeringObject.product_id == product.id)
            .options(joinedload(EngineeringObject.current_version))
            .order_by(EngineeringObject.id)
        ).all()
        for obj in rows:
            if not is_thumbnail_candidate(obj.filename or ""):
                continue
            version = obj.current_version
            if version is None or not (version.content_hash or "").strip():
                continue
            digest = version.content_hash.strip().lower()
            if session.get(Thumbnail, digest) is not None:
                continue  # already has a thumb — skip
            try:
                path = ctx.workspaces.locate_content(product, obj)
            except Exception:
                continue
            paths.append(path)
            if len(paths) >= limit:
                break
    finally:
        session.close()
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="Vault tip file(s)")
    parser.add_argument("--product-uuid", default="", help="Sample tips missing a DB thumbnail")
    parser.add_argument("--limit", type=int, default=20, help="Max tips when using --product-uuid")
    parser.add_argument("--json", action="store_true", help="JSON lines output")
    args = parser.parse_args()

    paths: list[Path] = list(args.paths)
    if args.product_uuid:
        manager = ConfigManager()
        setup_logging(manager.log_path)
        ctx = build_context(manager)
        paths.extend(_paths_from_product(ctx, args.product_uuid.strip(), args.limit))
        ctx.engine.dispose()

    if not paths:
        parser.error("pass tip paths and/or --product-uuid")

    tallies: dict[str, int] = {}
    for path in paths:
        report = diagnose_thumbnail(path)
        reason = str(report.get("reason") or "?")
        tallies[reason] = tallies.get(reason, 0) + 1
        if args.json:
            print(json.dumps(report, sort_keys=True))
        else:
            print(
                f"{reason:22} markers={report.get('marker_count')} "
                f"jpeg_sig={report.get('markers_with_jpeg_sig')} "
                f"gap={report.get('nearest_jpeg_gap')} "
                f"bytes={report.get('extract_bytes')}  {path}"
            )

    if not args.json:
        print("---")
        print("totals:", tallies)
        print(
            "not_in_model = Creo did not embed a usable thumbnail. "
            "jpeg_outside_window / parse_rejected = look like extractor bugs."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
