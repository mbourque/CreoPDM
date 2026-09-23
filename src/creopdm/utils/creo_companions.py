"""Resolve CAD files that must sit beside a model for Creo to open it.

Creo.JS cannot list assembly members before Retrieve. The dependency table is
not populated yet, so we use same-folder CAD siblings and optionally narrow
by names referenced inside the parent file.
"""

from __future__ import annotations

from pathlib import Path

from creopdm.creo.file_manager import CreoFileManager
from creopdm.utils.classify import is_creo_openable
from creopdm.utils.folders import folder_of, objects_in_folder_view

# Assemblies/drawings need neighbors; plain parts usually do not.
_NEEDS_COMPANIONS = frozenset({
    "CREO_ASSEMBLY",
    "CREO_DRAWING",
})
_NEEDS_COMPANION_SUFFIXES = frozenset({".asm", ".drw"})
_SCAN_LIMIT = 8 * 1024 * 1024


def needs_open_companions(object_type: str, filename: str) -> bool:
    if (object_type or "").upper() in _NEEDS_COMPANIONS:
        return True
    logical = CreoFileManager.normalize_creo_filename(filename)
    return Path(logical).suffix.lower() in _NEEDS_COMPANION_SUFFIXES


def names_referenced_in_model(path: Path, candidates: list[str]) -> set[str]:
    """Return candidate logical names that appear as bytes in the Creo file."""
    if not candidates or not path.is_file():
        return set()
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            blob = handle.read(min(size, _SCAN_LIMIT))
    except OSError:
        return set()
    lower = blob.lower()
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
    same way companion open narrows same-folder siblings.
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


def select_companion_objects(
    *,
    primary_relative: str,
    primary_filename: str,
    object_type: str,
    siblings: list,
    model_path: Path,
    model_extensions: list[str] | tuple[str, ...],
    all_cad_extensions: list[str] | tuple[str, ...],
) -> list:
    """Pick same-folder CAD objects that should download with an assembly/drawing."""
    if not needs_open_companions(object_type, primary_filename):
        return []
    folder = folder_of(primary_relative)
    primary_rel = str(primary_relative or "").replace("\\", "/").lower()
    primary_logical = CreoFileManager.normalize_creo_filename(primary_filename).lower()
    pool = []
    candidate_names: list[str] = []
    for obj in objects_in_folder_view(siblings, folder):
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
    if not referenced:
        return pool
    narrowed = []
    for obj in pool:
        name = str(getattr(obj, "filename", "") or "")
        logical = CreoFileManager.normalize_creo_filename(name, (*model_extensions, *all_cad_extensions))
        if logical in referenced or logical.lower() in {item.lower() for item in referenced}:
            narrowed.append(obj)
    return narrowed or pool
