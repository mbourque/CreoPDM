"""File classification for imported engineering objects."""

from __future__ import annotations

from pathlib import Path

from creopdm.constants import DEFAULT_FOLDER_BY_TYPE, OBJECT_TYPE_BY_EXTENSION, ObjectType
from creopdm.creo.file_manager import CreoFileManager


def classify_filename(filename: str) -> ObjectType:
    """Map a filename to an object type. Unknown extensions become OTHER."""
    canonical = CreoFileManager.normalize_creo_filename(filename)
    suffix = Path(canonical).suffix.lower()
    return OBJECT_TYPE_BY_EXTENSION.get(suffix, ObjectType.OTHER)


def default_folder_for(object_type: ObjectType) -> str:
    return DEFAULT_FOLDER_BY_TYPE.get(object_type, "Documents")
