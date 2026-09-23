"""Match Creo BOM / dependency filenames to project objects."""

from __future__ import annotations

import re

from creopdm.creo.file_manager import CreoFileManager

_INSTANCE_GENERIC_RE = re.compile(r"<([^>]+)>")


def extension_of(filename: str) -> str:
    lower = str(filename or "").lower()
    for candidate in (".prt", ".asm", ".drw", ".frm", ".mfg"):
        if lower.endswith(candidate) or f"{candidate}." in lower:
            return candidate
    name = CreoFileManager.logical_filename(filename)
    if "." in name:
        return "." + name.rsplit(".", 1)[-1].lower()
    return ""


def bom_lookup_keys(filename: str) -> list[str]:
    """Keys used to match BOM/dependency names to project objects.

    Family-table display names like ``INSTALLED<SPLIT-RIVET>.prt`` resolve to the
    generic ``SPLIT-RIVET.prt`` (name inside ``<>``), which is what Creo opens.
    """
    name = str(filename or "").strip()
    if not name:
        return []
    keys: list[str] = []

    def add(key: str) -> None:
        text = CreoFileManager.logical_filename(key or "").strip().lower()
        if text and text not in keys:
            keys.append(text)

    ext = extension_of(name)
    for match in _INSTANCE_GENERIC_RE.finditer(name):
        generic = match.group(1).strip()
        if not generic:
            continue
        add(f"{generic}{ext}" if ext and not generic.lower().endswith(ext) else generic)
        add(generic)
    plain = _INSTANCE_GENERIC_RE.sub("", name)
    if plain and plain != name:
        add(plain)
    add(name)
    return keys


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
    left_keys = set(bom_lookup_keys(left))
    right_keys = set(bom_lookup_keys(right))
    return bool(left_keys and right_keys and (left_keys & right_keys))
