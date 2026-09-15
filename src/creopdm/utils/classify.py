"""File classification for imported engineering objects."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from creopdm.constants import (
    CREO_FILE_EXTENSIONS,
    DEFAULT_EXTRA_CAD_EXTENSIONS,
    DEFAULT_FOLDER_BY_TYPE,
    OBJECT_TYPE_BY_EXTENSION,
    ObjectType,
)
from creopdm.creo.file_manager import CreoFileManager


def normalize_extension(value: str) -> str:
    """Return a lowercase extension with a leading dot, or '' if invalid."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if not text.startswith("."):
        text = f".{text}"
    if any(ch in text for ch in '/\\:*?"<>|') or text == ".":
        return ""
    return text


def extra_cad_set(values: Iterable[str] | None) -> frozenset[str]:
    found: list[str] = []
    seen: set[str] = set()
    for raw in values or ():
        ext = normalize_extension(str(raw))
        if ext and ext not in seen:
            seen.add(ext)
            found.append(ext)
    return frozenset(found)


def parse_extension_text(value: str | None) -> list[str]:
    """Parse a comma, newline, or space separated extension list."""
    if not value:
        return []
    chunks: list[str] = []
    for line in value.replace(",", "\n").splitlines():
        for part in line.split():
            ext = normalize_extension(part)
            if ext and ext not in chunks:
                chunks.append(ext)
    return chunks


def classify_filename(
    filename: str,
    extra_cad_extensions: Iterable[str] | None = None,
) -> ObjectType:
    """Map a filename to an object type. Unknown extensions become OTHER.

    Creo models always stay Creo types. Extra CAD extensions from Settings are
    classified as CAD. Built-in document types stay documents unless listed as
    extra CAD extensions. Workspace copies all go in one folder.
    """
    canonical = CreoFileManager.normalize_creo_filename(filename, extra_cad_extensions)
    suffix = Path(canonical).suffix.lower()
    extras = (
        extra_cad_set(DEFAULT_EXTRA_CAD_EXTENSIONS)
        if extra_cad_extensions is None
        else extra_cad_set(extra_cad_extensions)
    )
    if suffix in CREO_FILE_EXTENSIONS:
        return OBJECT_TYPE_BY_EXTENSION.get(suffix, ObjectType.CAD)
    if suffix in extras:
        return ObjectType.CAD
    return OBJECT_TYPE_BY_EXTENSION.get(suffix, ObjectType.OTHER)


def default_folder_for(object_type: ObjectType) -> str:
    return DEFAULT_FOLDER_BY_TYPE.get(object_type, "Documents")
