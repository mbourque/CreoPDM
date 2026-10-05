"""Resolve CAD files that must sit beside a model for Creo to open it.

Walks assembly trees automatically by scanning vault model bytes for referenced
names (no Rebuild Where Used required). Where Used edges are an optional extra
source when the product has already been indexed.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from creopdm.creo.file_manager import CreoFileManager
from creopdm.utils.cad_name_matcher import CadNameMatcher, find_bounded_token
from creopdm.utils.classify import is_creo_openable
from creopdm.utils.folders import folder_of, objects_in_folder_view

# Assemblies/drawings need neighbors; plain parts usually do not.
_NEEDS_DEPENDENCIES = frozenset({
    "CREO_ASSEMBLY",
    "CREO_DRAWING",
})
_NEEDS_DEPENDENCY_SUFFIXES = frozenset({".asm", ".drw"})
# Open / Finding dependencies — keep small so one request cannot wedge the worker.
_SCAN_LIMIT = 8 * 1024 * 1024
# Rebuild Where Used is background; read the whole tip (component tables can sit late).
_WHERE_USED_SCAN_LIMIT: int | None = None
# Creo tips often embed a product-wide name table. Stem matching then links almost
# every assembly as a "child" (Top Level → 0) and falsely parents the true root.
# After indexing, drop ASSEMBLY_MEMBER edges into assemblies claimed by more than
# this many parents (e.g. project root name appearing in ~every tip).
_MAX_WHERE_USED_ASM_PARENTS = 40
# Bare stems that are Creo datum/view words — never treat as component names.
# ``front.asm`` otherwise becomes a name-table magnet / false Top Level.
_WHERE_USED_STEM_BLOCKLIST = frozenset(
    {
        "front",
        "back",
        "left",
        "right",
        "top",
        "bottom",
        "side",
        "center",
        "middle",
        "inner",
        "outer",
        "upper",
        "lower",
        "main",
        "base",
        "core",
        "default",
        "solid",
        "quilt",
    }
)
# Omit from the Top Level pill only (stem blocklist stays broader for matching).
# Do not include common real roots like ``top.asm`` / ``main.asm``.
_TOP_LEVEL_STEM_OMIT = frozenset({"front", "back", "left", "right"})
# Below this, plain ``in`` checks are cheaper than building an automaton.
_MATCHER_THRESHOLD = 48
# Safety caps for deep assembly trees.
# Keep the Open/vault-scan walk small — a single worker + QueuePool (5+10) wedges
# the whole site when Open prepares thousands of dependencies.
_MAX_OPEN_DEPENDENCY_DEPTH = 8
_MAX_OPEN_DEPENDENCIES_TOTAL = 150


def needs_open_dependencies(object_type: str, filename: str) -> bool:
    if (object_type or "").upper() in _NEEDS_DEPENDENCIES:
        return True
    logical = CreoFileManager.normalize_creo_filename(filename)
    return Path(logical).suffix.lower() in _NEEDS_DEPENDENCY_SUFFIXES


def _is_ascii_name_byte(byte: int) -> bool:
    """ASCII Creo name character (either case) — used before the blob is lowercased."""
    return (
        48 <= byte <= 57  # 0-9
        or 65 <= byte <= 90  # A-Z
        or 97 <= byte <= 122  # a-z
        or byte == 95  # _
        or byte == 45  # -
    )


def _utf16le_ascii_runs(raw: bytes) -> bytes:
    """Collapse UTF-16LE ASCII runs to contiguous bytes (Creo wide component names)."""
    out = bytearray()
    index = 0
    length = len(raw)
    while index + 1 < length:
        if raw[index + 1] == 0 and 32 <= raw[index] < 127:
            # Do not start a wide run glued to a preceding ASCII letter
            # (``header\\x00`` + ``a\\x00t\\x00…`` must not become ``rat…``).
            if index > 0 and _is_ascii_name_byte(raw[index - 1]):
                index += 1
                continue
            start = index
            while index + 1 < length and raw[index + 1] == 0 and 32 <= raw[index] < 127:
                index += 2
            # At least 2 characters (4 bytes) — skip noise.
            if index - start >= 4:
                out.extend(raw[pos] for pos in range(start, index, 2))
                out.append(0)
            continue
        index += 1
    return bytes(out)


def read_model_scan_blob(path: Path, *, max_bytes: int | None = _SCAN_LIMIT) -> bytes:
    """Read Creo tip bytes (lowercased) for name matching.

    Default ``max_bytes`` is the Open scan window. Pass ``None`` (or
    ``_WHERE_USED_SCAN_LIMIT``) from Rebuild so late component tables are not missed.

    Appends collapsed UTF-16LE ASCII runs so bare component names stored as
    wide strings still match the same CadNameMatcher tokens.
    """
    if not path.is_file():
        return b""
    try:
        size = path.stat().st_size
        take = size if max_bytes is None else min(size, int(max_bytes))
        with path.open("rb") as handle:
            blob = handle.read(take)
    except OSError:
        return b""
    lower = blob.lower()
    wide = _utf16le_ascii_runs(blob)
    if not wide:
        return lower
    return lower + b"\x00" + wide.lower()


def names_referenced_in_model(
    path: Path,
    candidates: list[str],
    *,
    include_stems: bool = True,
) -> set[str]:
    """Return candidate logical names that appear as bytes in the Creo file."""
    if not candidates or not path.is_file():
        return set()
    lower = read_model_scan_blob(path)
    if not lower:
        return set()
    if len(candidates) >= _MATCHER_THRESHOLD or not include_stems:
        return CadNameMatcher(candidates, include_stems=include_stems).find(lower)
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


def logical_name_in_model(path: Path, filename: str) -> bool:
    """True when the vault file contains bounded logical ``name.ext`` (not bare stem).

    Bare stems and names glued inside longer tokens create false Where Used /
    Top Level parents (e.g. ``844j.asm`` claimed by an assembly that only has parts).
    """
    logical = CreoFileManager.normalize_creo_filename(filename).lower()
    if not logical or "." not in logical:
        return False
    token = logical.encode("ascii", "ignore")
    if len(token) < 5:
        return False
    lower = read_model_scan_blob(path)
    return bool(lower) and find_bounded_token(lower, token)


def model_references_filename(path: Path, filename: str) -> bool:
    """True when the vault Creo file mentions this model as ``name.ext``.

    Used for Where Used when Creo.JS BOM metadata was never captured. Stem-only
    hits are ignored — they false-positive Top Level / Where Used.
    """
    return logical_name_in_model(path, filename)


_MAX_OPEN_DEPENDENCY_POOL = 40
# Flat multi-thousand vaults put the whole product in "folder" scope — stem
# matching then hangs Finding dependencies. Cap and prefer name.ext only.
_MAX_OPEN_DEPENDENCY_MATCHES = 200


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
    # Large/flat pools: bounded name.ext only (stem matching times out Open).
    strict = len(pool) > _MAX_OPEN_DEPENDENCY_POOL
    referenced = names_referenced_in_model(
        model_path, candidate_names, include_stems=not strict
    )
    if referenced:
        referenced_lower = {item.lower() for item in referenced}
        narrowed = []
        for obj in pool:
            name = str(getattr(obj, "filename", "") or "")
            logical = CreoFileManager.normalize_creo_filename(
                name, (*model_extensions, *all_cad_extensions)
            )
            if logical in referenced or logical.lower() in referenced_lower:
                narrowed.append(obj)
            if len(narrowed) >= _MAX_OPEN_DEPENDENCY_MATCHES:
                break
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


def _open_dependency_type(parent_filename: str) -> str:
    """ASSEMBLY_MEMBER for asms; DRAWING_MODEL for drawings (matches vault rebuild)."""
    from creopdm.constants import DependencyType

    logical = CreoFileManager.normalize_creo_filename(parent_filename)
    if Path(logical).suffix.lower() == ".drw":
        return DependencyType.DRAWING_MODEL.value
    return DependencyType.ASSEMBLY_MEMBER.value


def collect_open_dependency_walk(
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
) -> tuple[list, list[tuple[int, int, str]]]:
    """Walk open deps and return (objects, edges).

    Each edge is ``(parent_object_id, child_object_id, dependency_type)`` for
    parents/children that have DB ids — same links Rebuild Where Used would store.
    """
    if not needs_open_dependencies(object_type, primary_filename):
        return [], []
    root_id = skip_object_id
    queue: list[tuple[str, str, str, Path, int, int | None]] = [
        (
            str(primary_relative or "").replace("\\", "/"),
            str(primary_filename or ""),
            str(object_type or ""),
            model_path,
            0,
            root_id,
        )
    ]
    seen_keys: set[str] = set()
    primary_key = str(primary_relative or "").replace("\\", "/").lower()
    if primary_key:
        seen_keys.add(primary_key)
    if root_id is not None:
        seen_keys.add(f"id:{root_id}")
    out: list = []
    edges: list[tuple[int, int, str]] = []
    edge_seen: set[tuple[int, int, str]] = set()
    while queue and len(out) < _MAX_OPEN_DEPENDENCIES_TOTAL:
        rel, filename, otype, path, depth, parent_id = queue.pop(0)
        if depth > _MAX_OPEN_DEPENDENCY_DEPTH:
            continue
        if not path.is_file():
            continue
        # Folder first, then product — merge so cross-folder parts are not skipped
        # when a small folder falls back to "all siblings" without byte hits.
        folder_hits = select_dependency_objects(
            primary_relative=rel,
            primary_filename=filename,
            object_type=otype,
            siblings=siblings,
            model_path=path,
            model_extensions=model_extensions,
            all_cad_extensions=all_cad_extensions,
            scope="folder",
        )
        product_hits = select_dependency_objects(
            primary_relative=rel,
            primary_filename=filename,
            object_type=otype,
            siblings=siblings,
            model_path=path,
            model_extensions=model_extensions,
            all_cad_extensions=all_cad_extensions,
            scope="product",
        )
        merged: dict[str, object] = {}
        for obj in (*product_hits, *folder_hits):
            obj_id = getattr(obj, "id", None)
            obj_rel = str(getattr(obj, "relative_path", "") or "").replace("\\", "/")
            key = f"id:{obj_id}" if obj_id is not None else obj_rel.lower()
            merged.setdefault(key, obj)
        immediate = list(merged.values())
        dep_type = _open_dependency_type(filename)
        for obj in immediate:
            obj_id = getattr(obj, "id", None)
            obj_rel = str(getattr(obj, "relative_path", "") or "").replace("\\", "/")
            key = f"id:{obj_id}" if obj_id is not None else obj_rel.lower()
            if (
                parent_id is not None
                and obj_id is not None
                and int(obj_id) != int(parent_id)
            ):
                child_name = str(getattr(obj, "filename", "") or Path(obj_rel).name)
                # Stem hits may still download with Open; only persist Where Used
                # edges when the parent bytes contain the full logical name.ext.
                if logical_name_in_model(path, child_name):
                    edge = (int(parent_id), int(obj_id), dep_type)
                    if edge not in edge_seen:
                        edge_seen.add(edge)
                        edges.append(edge)
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
            child_parent_id = int(obj_id) if obj_id is not None else None
            queue.append(
                (obj_rel, child_name, child_type, child_path, depth + 1, child_parent_id)
            )
    return out, edges


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
    """Walk sub-assemblies and collect every part/asm Creo needs to open primary."""
    objects, _edges = collect_open_dependency_walk(
        primary_relative=primary_relative,
        primary_filename=primary_filename,
        object_type=object_type,
        siblings=siblings,
        model_path=model_path,
        model_extensions=model_extensions,
        all_cad_extensions=all_cad_extensions,
        resolve_path=resolve_path,
        skip_object_id=skip_object_id,
    )
    return objects
