"""Match Creo BOM / dependency filenames to project objects."""

from __future__ import annotations

import re

from creopdm.creo.file_manager import CreoFileManager

_INSTANCE_GENERIC_RE = re.compile(r"<([^>]+)>")
# Creo Mirror Part defaults: NAME_MIR or NAME-NAME_MIR (custom prefix rules).
_MIRROR_SUFFIX_RE = re.compile(r"^(.+)_mir$", re.IGNORECASE)
_MIRROR_DUP_RE = re.compile(r"^(.+)-\1_mir$", re.IGNORECASE)
_CAD_SUFFIXES = (".prt", ".asm", ".drw", ".frm", ".mfg")


def extension_of(filename: str) -> str:
    lower = str(filename or "").lower()
    for candidate in _CAD_SUFFIXES:
        if lower.endswith(candidate) or f"{candidate}." in lower:
            return candidate
    name = CreoFileManager.logical_filename(filename)
    if "." in name:
        return "." + name.rsplit(".", 1)[-1].lower()
    return ""


def bom_lookup_keys(filename: str, *, include_mirror_aliases: bool = False) -> list[str]:
    """Keys used to match BOM/dependency names to project objects.

    Family-table display names like ``INSTALLED<SPLIT-RIVET>.prt`` resolve to the
    generic ``SPLIT-RIVET.prt`` (name inside ``<>``), which is what Creo opens.
    Extensionless Creo descriptors (``SHAFT``) also match ``shaft.prt``.
    """
    name = str(filename or "").strip()
    if not name:
        return []
    keys: list[str] = []

    def add(key: str) -> None:
        text = CreoFileManager.logical_filename(key or "").strip().lower()
        if text and text not in keys:
            keys.append(text)

    def add_stem_variants(stem: str) -> None:
        stem = (stem or "").strip().lower()
        if not stem:
            return
        add(stem)
        for suffix in _CAD_SUFFIXES:
            add(f"{stem}{suffix}")

    ext = extension_of(name)
    for match in _INSTANCE_GENERIC_RE.finditer(name):
        generic = match.group(1).strip()
        if not generic:
            continue
        add(f"{generic}{ext}" if ext and not generic.lower().endswith(ext) else generic)
        add(generic)
        add_stem_variants(generic.rsplit(".", 1)[0] if "." in generic else generic)
    plain = _INSTANCE_GENERIC_RE.sub("", name)
    if plain and plain != name:
        add(plain)
    add(name)

    logical = CreoFileManager.logical_filename(name).strip().lower()
    if logical:
        if "." in logical:
            stem = logical.rsplit(".", 1)[0]
            add(stem)  # Creo ModelDescr often omits .prt/.asm
            if include_mirror_aliases:
                # Mirror copies: clasp-clasp_mir.prt / clasp_mir.prt → also clasp.prt
                dup = _MIRROR_DUP_RE.match(stem)
                if dup:
                    add_stem_variants(dup.group(1))
                else:
                    mirrored = _MIRROR_SUFFIX_RE.match(stem)
                    if mirrored:
                        add_stem_variants(mirrored.group(1))
        else:
            add_stem_variants(logical)

    return keys


def bom_where_used_keys(filename: str) -> list[str]:
    """Lookup keys for Where Used, including Creo mirror-part aliases."""
    return bom_lookup_keys(filename, include_mirror_aliases=True)


def bom_generic_label(filename: str) -> str | None:
    """Human label for the generic that an instance name opens, if any."""
    name = str(filename or "").strip()
    match = _INSTANCE_GENERIC_RE.search(name)
    if not match:
        return None
    generic = match.group(1).strip()
    if not generic:
        return None
    ext = extension_of(name)
    if ext and not generic.lower().endswith(ext):
        return f"{generic}{ext}"
    return generic


def filenames_refer_to_same_model(left: str, right: str) -> bool:
    """True when two Creo filenames likely refer to the same project object."""
    left_keys = set(bom_where_used_keys(left))
    right_keys = set(bom_where_used_keys(right))
    return bool(left_keys and right_keys and (left_keys & right_keys))
