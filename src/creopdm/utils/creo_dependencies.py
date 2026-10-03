"""Resolve CAD files that must sit beside a model for Creo to open it.

Walks assembly trees automatically by scanning vault model bytes for referenced
names (no Rebuild Where Used required). Where Used edges are an optional extra
source when the product has already been indexed.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from creopdm.creo.file_manager import CreoFileManager
from creopdm.utils.cad_name_matcher import CadNameMatcher
from creopdm.utils.classify import is_creo_openable
from creopdm.utils.folders import folder_of, objects_in_folder_view

# Assemblies/drawings need neighbors; plain parts usually do not.
_NEEDS_DEPENDENCIES = frozenset({
    "CREO_ASSEMBLY",
    "CREO_DRAWING",
})
_NEEDS_DEPENDENCY_SUFFIXES = frozenset({".asm", ".drw"})
_SCAN_LIMIT = 8 * 1024 * 1024
# Below this, plain ``in`` checks are cheaper than building an automaton.
_MATCHER_THRESHOLD = 48
# Safety caps for deep assembly trees.
_MAX_OPEN_DEPENDENCY_DEPTH = 12
_MAX_OPEN_DEPENDENCIES_TOTAL = 2500


def needs_open_dependencies(object_type: str, filename: str) -> bool:
    if (object_type or "").upper() in _NEEDS_DEPENDENCIES:
        return True
    logical = CreoFileManager.normalize_creo_filename(filename)
    return Path(logical).suffix.lower() in _NEEDS_DEPENDENCY_SUFFIXES


def read_model_scan_blob(path: Path) -> bytes:
    """Read up to ``_SCAN_LIMIT`` bytes from a Creo file (lowercased)."""
    if not path.is_file():
        return b""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            blob = handle.read(min(size, _SCAN_LIMIT))
    except OSError:
        return b""
    return blob.lower()


def names_referenced_in_model(path: Path, candidates: list[str]) -> set[str]:
    """Return candidate logical names that appear as bytes in the Creo file."""
    if not candidates or not path.is_file():
        return set()
    lower = read_model_scan_blob(path)
    if not lower:
        return set()
    if len(candidates) >= _MATCHER_THRESHOLD:
        return CadNameMatcher(candidates).find(lower)
    found: set[str] = set()
    for name in candidates:
        logical = CreoFileManager.normalize_creo_filename(name).lower()
        if not logical:
            continue
        stem = Path(logical).stem.lower()
        tokens = {logical.encode("ascii", "ignore"), stem.encode("ascii", "ignore")}
        for token in tokens:
            if len(token) >= 2 and token in lower:
                found.add(CreoFileManager.normalize_creo_filename(name))
                break
    return found


def model_references_filename(path: Path, filename: str) -> bool:
    """True when the vault Creo file byte-content mentions this model name.

    Used for Where Used when Creo.JS BOM metadata was never captured. Matches the
    same way open-dependency narrowing matches same-folder siblings.
    """
    from creopdm.utils.bom_match import bom_where_used_keys

    if not path.is_file():
        return False
    tokens: list[bytes] = []
    seen: set[bytes] = set()
    for key in sorted(bom_where_used_keys(filename), key=len, reverse=True):
        raw = key.encode("ascii", "ignore")
        if len(raw) < 3:
            continue
        # Prefer names with an extension, or stems long enough to avoid noise.
        if b"." not in raw and len(raw) < 5:
            continue
        if raw in seen:
            continue
        seen.add(raw)
        tokens.append(raw)
    if not tokens:
        return False
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            blob = handle.read(min(size, _SCAN_LIMIT))
    except OSError:
        return False
    lower = blob.lower()
    return any(token in lower for token in tokens)


_MAX_OPEN_DEPENDENCY_POOL = 40


def select_dependency_objects(
    *,
    primary_relative: str,
    primary_filename: str,
    object_type: str,
    siblings: list,
    model_path: Path,
    model_extensions: list[str] | tuple[str, ...],
    all_cad_extensions: list[str] | tuple[str, ...],
    scope: str = "folder",
) -> list:
    """Pick CAD objects that should download with an assembly/drawing.

    ``scope="folder"``: same-folder siblings (legacy / huge flat folders).
    ``scope="product"``: whole product, but only names referenced in the model
    bytes (needed for parts living in other folders).
    """
    if not needs_open_dependencies(object_type, primary_filename):
        return []
    folder = folder_of(primary_relative)
    primary_rel = str(primary_relative or "").replace("\\", "/").lower()
    primary_logical = CreoFileManager.normalize_creo_filename(primary_filename).lower()
    pool = []
    candidate_names: list[str] = []
    source = siblings if scope == "product" else objects_in_folder_view(siblings, folder)
    for obj in source:
        rel = str(getattr(obj, "relative_path", "") or "").replace("\\", "/")
        if rel.lower() == primary_rel:
            continue
        name = str(getattr(obj, "filename", "") or Path(rel).name)
        if not is_creo_openable(name, model_extensions, all_cad_extensions):
            continue
        logical = CreoFileManager.normalize_creo_filename(name, (*model_extensions, *all_cad_extensions))
        if logical.lower() == primary_logical:
            continue
        pool.append(obj)
        candidate_names.append(logical)
    if not pool:
        return []
    referenced = names_referenced_in_model(model_path, candidate_names)
    if referenced:
        narrowed = []
        for obj in pool:
            name = str(getattr(obj, "filename", "") or "")
            logical = CreoFileManager.normalize_creo_filename(name, (*model_extensions, *all_cad_extensions))
            if logical in referenced or logical.lower() in {item.lower() for item in referenced}:
                narrowed.append(obj)
        if narrowed:
            return narrowed
    # Product-wide without byte hits would pull the whole vault — refuse.
    if scope == "product":
        return []
    # No byte matches (or empty scan): never drag an entire flat product folder
    # into Creo — that hangs Open on multi-thousand-file products.
    if len(pool) > _MAX_OPEN_DEPENDENCY_POOL:
        return []
    return pool


def collect_open_dependency_objects(
    *,
    primary_relative: str,
    primary_filename: str,
    object_type: str,
    siblings: list,
    model_path: Path,
    model_extensions: list[str] | tuple[str, ...],
    all_cad_extensions: list[str] | tuple[str, ...],
    resolve_path: Callable[[object], Path | None],
    skip_object_id: int | None = None,
) -> list:
    """Walk sub-assemblies and collect every part/asm Creo needs to open primary.

    Each assembly level uses product-wide name matching against vault file bytes,
    then recurses into any dependency that is itself an assembly/drawing.
    """
    if not needs_open_dependencies(object_type, primary_filename):
        return []
    queue: list[tuple[str, str, str, Path, int]] = [
        (
            str(primary_relative or "").replace("\\", "/"),
            str(primary_filename or ""),
            str(object_type or ""),
            model_path,
            0,
        )
    ]
    seen_keys: set[str] = set()
    primary_key = str(primary_relative or "").replace("\\", "/").lower()
    if primary_key:
        seen_keys.add(primary_key)
    if skip_object_id is not None:
        seen_keys.add(f"id:{skip_object_id}")
    out: list = []
    while queue and len(out) < _MAX_OPEN_DEPENDENCIES_TOTAL:
        rel, filename, otype, path, depth = queue.pop(0)
        if depth > _MAX_OPEN_DEPENDENCY_DEPTH:
            continue
        if not path.is_file():
            continue
        immediate = select_dependency_objects(
            primary_relative=rel,
            primary_filename=filename,
            object_type=otype,
            siblings=siblings,
            model_path=path,
            model_extensions=model_extensions,
            all_cad_extensions=all_cad_extensions,
            scope="product",
        )
        if not immediate and depth == 0:
            # First level: also try same-folder fallback (empty/unreadable scan).
            immediate = select_dependency_objects(
                primary_relative=rel,
                primary_filename=filename,
                object_type=otype,
                siblings=siblings,
                model_path=path,
                model_extensions=model_extensions,
                all_cad_extensions=all_cad_extensions,
                scope="folder",
            )
        for obj in immediate:
            obj_id = getattr(obj, "id", None)
            obj_rel = str(getattr(obj, "relative_path", "") or "").replace("\\", "/")
            key = f"id:{obj_id}" if obj_id is not None else obj_rel.lower()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append(obj)
            if len(out) >= _MAX_OPEN_DEPENDENCIES_TOTAL:
                break
            child_type = str(getattr(obj, "object_type", "") or "")
            child_name = str(getattr(obj, "filename", "") or Path(obj_rel).name)
            if not needs_open_dependencies(child_type, child_name):
                continue
            child_path = resolve_path(obj)
            if child_path is None or not child_path.is_file():
                continue
            queue.append((obj_rel, child_name, child_type, child_path, depth + 1))
    return out
