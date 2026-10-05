#!/usr/bin/env python3
"""Diagnose why Top Level assemblies is not 1 for a product.

Run on the CreoPDM host (or any machine with that product's config/DB/vault):

  cd ~/CreoPDM
  .venv/bin/python scripts/diagnose_top_level.py 6f344032-97a4-4de1-a015-70254eb0ce0b
  .venv/bin/python scripts/diagnose_top_level.py 9c637a65-229a-4a51-a24d-266f0b39e50f

Prints DB top-level assemblies, a fresh in-memory rebuild graph, and for each
orphan assembly whether its name appears in any parent vault file (bounded /
loose / beyond the 8 MiB open-scan window).
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

# Allow `python scripts/diagnose_top_level.py` from repo root without install.
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sqlalchemy import select

from creopdm.app import build_context
from creopdm.config import ConfigManager
from creopdm.constants import DependencyType
from creopdm.creo.file_manager import CreoFileManager
from creopdm.models.dependency import Dependency
from creopdm.models.object import EngineeringObject
from creopdm.models.product import Product
from creopdm.utils.cad_name_matcher import CadNameMatcher, find_bounded_token
from creopdm.utils.creo_dependencies import (
    _SCAN_LIMIT,
    _WHERE_USED_SCAN_LIMIT,
    _utf16le_ascii_runs,
    needs_open_dependencies,
    read_model_scan_blob,
)
from creopdm.utils.paths import PathValidationError


def _read_full_scan_blob(path: Path, *, limit: int | None) -> bytes:
    if not path.is_file():
        return b""
    try:
        size = path.stat().st_size
        take = size if limit is None else min(size, limit)
        with path.open("rb") as handle:
            blob = handle.read(take)
    except OSError:
        return b""
    lower = blob.lower()
    wide = _utf16le_ascii_runs(blob)
    if not wide:
        return lower
    return lower + b"\x00" + wide.lower()


def _classify_hit(blob: bytes, logical: str, stem: str) -> str:
    """How the name appears in an already-built scan blob."""
    if not blob:
        return "absent"
    ext_tok = logical.encode("ascii", "ignore")
    stem_tok = stem.encode("ascii", "ignore")
    if ext_tok and find_bounded_token(blob, ext_tok):
        return "bounded_name_ext"
    if stem_tok and len(stem_tok) >= 4 and find_bounded_token(blob, stem_tok):
        return "bounded_stem"
    if ext_tok and ext_tok in blob:
        return "loose_name_ext"
    if stem_tok and len(stem_tok) >= 2 and stem_tok in blob:
        return "loose_stem"
    return "absent"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("product_uuid", help="Product UUID from the URL or Admin list")
    parser.add_argument(
        "--expected-root",
        default="844j.asm",
        help="Assembly that should be the only top-level (default: 844j.asm)",
    )
    parser.add_argument(
        "--max-orphans",
        type=int,
        default=40,
        help="How many orphan assemblies to explain in detail",
    )
    args = parser.parse_args()
    product_uuid = args.product_uuid.strip()
    expected_root = CreoFileManager.normalize_creo_filename(args.expected_root).lower()

    ctx = build_context(ConfigManager())
    with ctx.session_factory() as db:
        product = db.scalar(select(Product).where(Product.uuid == product_uuid))
        if product is None:
            print(f"ERROR: product not found: {product_uuid}")
            return 1

        objects = list(ctx.objects.list_objects(db, product.id))
        asms = [
            row
            for row in objects
            if (row.object_type or "").upper() == "CREO_ASSEMBLY"
            or Path(CreoFileManager.normalize_creo_filename(row.filename)).suffix.lower()
            == ".asm"
        ]
        parents = [
            row
            for row in objects
            if needs_open_dependencies(row.object_type, row.filename)
        ]
        db_tops = ctx.metadata.top_level_assembly_uuids(db, product.id)
        top_by_uuid = {str(row.uuid): row for row in asms}
        db_top_names = sorted(
            CreoFileManager.normalize_creo_filename(top_by_uuid[u].filename).lower()
            for u in db_tops
            if u in top_by_uuid
        )

        edge_count = db.scalar(
            select(Dependency.id)
            .where(
                Dependency.product_id == product.id,
                Dependency.dependency_type == DependencyType.ASSEMBLY_MEMBER.value,
            )
            .limit(1)
        )
        member_edges = list(
            db.scalars(
                select(Dependency).where(
                    Dependency.product_id == product.id,
                    Dependency.dependency_type == DependencyType.ASSEMBLY_MEMBER.value,
                )
            )
        )

        print(f"product: {product.name} ({product.uuid})")
        print(f"vault_folder: {product.vault_folder}")
        print(f"objects: {len(objects)}  assemblies: {len(asms)}  scan parents: {len(parents)}")
        print(f"ASSEMBLY_MEMBER edges: {len(member_edges)}")
        print(f"DB top-level assemblies: {len(db_tops)}")
        print(f"expected sole root: {expected_root}")
        print()
        if expected_root in db_top_names:
            print(f"OK: {expected_root} is in DB top-level set")
        else:
            print(f"WARN: {expected_root} is NOT in DB top-level set")
        print("DB top-level names (first 60):")
        for name in db_top_names[:60]:
            mark = " <-- expected" if name == expected_root else ""
            print(f"  {name}{mark}")
        if len(db_top_names) > 60:
            print(f"  ... +{len(db_top_names) - 60} more")
        print()

        # Fresh in-memory rebuild (same matcher as production).
        by_key: dict[str, EngineeringObject] = {}
        candidate_names: list[str] = []
        for row in objects:
            candidate_names.append(row.filename)
            logical = CreoFileManager.normalize_creo_filename(row.filename).lower()
            if logical and "." in logical:
                by_key.setdefault(logical, row)

        matcher = CadNameMatcher(
            candidate_names,
            include_stems=True,
            require_boundaries=True,
            min_stem_len=4,
            unique_stems_only=True,
        )

        children_of: dict[int, set[int]] = defaultdict(set)
        missing_vault = 0
        oversized = 0
        for parent in parents:
            try:
                path = ctx.workspaces.locate_content(product, parent)
            except PathValidationError:
                missing_vault += 1
                continue
            except Exception as exc:  # noqa: BLE001
                print(f"locate failed {parent.filename}: {exc}")
                missing_vault += 1
                continue
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            if size > _SCAN_LIMIT:
                oversized += 1
            blob = read_model_scan_blob(path, max_bytes=_WHERE_USED_SCAN_LIMIT)
            found = matcher.find(blob) if blob else set()
            for name in found:
                logical = CreoFileManager.normalize_creo_filename(name).lower()
                child = by_key.get(logical)
                if child is None or child.id == parent.id:
                    continue
                children_of[parent.id].add(child.id)

        referenced: set[int] = set()
        for kids in children_of.values():
            referenced.update(kids)
        mem_tops = sorted(
            CreoFileManager.normalize_creo_filename(row.filename).lower()
            for row in asms
            if row.id not in referenced
        )
        print(
            f"In-memory rebuild top-level: {len(mem_tops)} "
            f"(missing_vault={missing_vault}, parents_over_8MiB={oversized})"
        )
        print("In-memory top-level names (first 60):")
        for name in mem_tops[:60]:
            mark = " <-- expected" if name == expected_root else ""
            print(f"  {name}{mark}")
        if len(mem_tops) > 60:
            print(f"  ... +{len(mem_tops) - 60} more")
        print()

        orphans = [row for row in asms if row.id not in referenced]
        orphans.sort(key=lambda row: (row.filename or "").lower())
        # Prefer explaining non-root orphans first.
        orphans_focus = [
            row
            for row in orphans
            if CreoFileManager.normalize_creo_filename(row.filename).lower() != expected_root
        ][: max(0, args.max_orphans)]

        print(f"Explaining up to {len(orphans_focus)} non-root orphan assemblies:")
        print("(hit = how the orphan's name appears inside some other asm/drw vault file)")
        print()

        # Preload parent paths once.
        parent_paths: list[tuple[EngineeringObject, Path, int]] = []
        for parent in parents:
            try:
                path = ctx.workspaces.locate_content(product, parent)
            except Exception:  # noqa: BLE001
                continue
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            parent_paths.append((parent, path, size))

        reasons: dict[str, int] = defaultdict(int)
        for orphan in orphans_focus:
            logical = CreoFileManager.normalize_creo_filename(orphan.filename).lower()
            stem = Path(logical).stem.lower()
            best = "absent_everywhere"
            best_parent = ""
            beyond_8mib = False
            for parent, path, size in parent_paths:
                if parent.id == orphan.id:
                    continue
                blob8 = read_model_scan_blob(path)
                hit = _classify_hit(blob8, logical, stem)
                if hit != "absent":
                    best = hit
                    best_parent = parent.filename
                    break
                if size > _SCAN_LIMIT:
                    # Name might live past the Open/rebuild 8 MiB window.
                    full = _read_full_scan_blob(path, limit=None)
                    hit_full = _classify_hit(full, logical, stem)
                    if hit_full != "absent":
                        best = f"beyond_8MiB_{hit_full}"
                        best_parent = parent.filename
                        beyond_8mib = True
                        break
            reasons[best] += 1
            extra = f" in {best_parent}" if best_parent else ""
            flag = " [PAST 8MiB SCAN]" if beyond_8mib else ""
            print(f"  {logical}: {best}{extra}{flag}")

        print()
        print("Orphan reason totals:")
        for key, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0])):
            print(f"  {count:4d}  {key}")

        if edge_count is None and not member_edges:
            print()
            print("NOTE: no ASSEMBLY_MEMBER edges in DB — Rebuild may not have finished.")

        print()
        print("Done.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
