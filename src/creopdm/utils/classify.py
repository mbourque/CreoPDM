"""File classification for imported engineering objects."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from pathlib import Path

from creopdm.constants import (
    CREO_FILE_EXTENSIONS,
    DEFAULT_CREO_MODEL_EXTENSIONS,
    DEFAULT_DOCUMENT_EXTENSIONS,
    DEFAULT_EXTRA_CAD_EXTENSIONS,
    DEFAULT_FOLDER_BY_TYPE,
    DEFAULT_OPENABLE_CAD_EXTENSIONS,
    DOCUMENT_OBJECT_TYPES,
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


def unique_extensions(values: Iterable[str] | None) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for raw in values or ():
        ext = normalize_extension(str(raw))
        if ext and ext not in seen:
            seen.add(ext)
            found.append(ext)
    return found


def extra_cad_set(values: Iterable[str] | None) -> frozenset[str]:
    return frozenset(unique_extensions(values))


def matches_cad_models(
    filename: str,
    extensions: Iterable[str] | None,
    stored_extension: str | None = None,
) -> bool:
    """True when the file's logical suffix is in the Creo Models chip list."""
    return matches_extension_list(filename, extensions, stored_extension)


def matches_document(
    filename: str,
    extensions: Iterable[str] | None,
    stored_extension: str | None = None,
) -> bool:
    """True when the file's logical suffix is in the Documents chip list."""
    return matches_extension_list(filename, extensions, stored_extension)


def matches_extension_list(
    filename: str,
    extensions: Iterable[str] | None,
    stored_extension: str | None = None,
) -> bool:
    wanted = extra_cad_set(extensions)
    if not wanted:
        return False
    stored = normalize_extension(stored_extension or "")
    if stored in wanted:
        return True
    canonical = CreoFileManager.normalize_creo_filename(filename, wanted)
    return Path(canonical).suffix.lower() in wanted


def default_data_cad_extensions() -> list[str]:
    return unique_extensions((*DEFAULT_OPENABLE_CAD_EXTENSIONS, *DEFAULT_EXTRA_CAD_EXTENSIONS))


def exclude_extensions(
    values: Iterable[str] | None,
    excluded: Iterable[str] | None,
) -> list[str]:
    skip = extra_cad_set(excluded)
    return [item for item in unique_extensions(values) if item not in skip]


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


def parse_type_label_tokens(value: str | None) -> list[str]:
    """Parse type-label keys: extensions (.inf) or file names (reviewref.inf)."""
    if not value:
        return []
    found: list[str] = []
    seen: set[str] = set()
    text = str(value).replace(";", ",")
    for line in text.replace(",", "\n").splitlines():
        for part in line.split():
            token = _normalize_type_label_token(part)
            if token and token not in seen:
                seen.add(token)
                found.append(token)
    return found


def _normalize_type_label_token(value: str) -> str:
    text = str(value or "").strip().lower().replace("\\", "/")
    if not text or text in {".", ".."}:
        return ""
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    if not text or any(ch in text for ch in '/:"<>|'):
        return ""
    if "*" in text or "?" in text:
        return text
    if "." in text and not text.startswith("."):
        return text
    return normalize_extension(text)


def classify_filename(
    filename: str,
    extra_cad_extensions: Iterable[str] | None = None,
    model_extensions: Iterable[str] | None = None,
    document_extensions: Iterable[str] | None = None,
) -> ObjectType:
    """Map a filename to an object type. Unknown extensions become OTHER.

    Creo models always stay Creo types. Files Creo can open, and extra CAD
    extensions from Settings, are classified as CAD. Document extensions from
    Settings stay documents unless listed as extra CAD extensions.
    """
    models = unique_extensions(
        DEFAULT_CREO_MODEL_EXTENSIONS if model_extensions is None else model_extensions
    )
    extras = unique_extensions(
        default_data_cad_extensions() if extra_cad_extensions is None else extra_cad_extensions
    )
    documents = unique_extensions(
        DEFAULT_DOCUMENT_EXTENSIONS if document_extensions is None else document_extensions
    )
    canonical = CreoFileManager.normalize_creo_filename(filename, (*models, *extras, *documents))
    suffix = Path(canonical).suffix.lower()
    mapped = OBJECT_TYPE_BY_EXTENSION.get(suffix)
    if mapped is not None and mapped.value.startswith("CREO_"):
        return mapped
    if suffix in CREO_FILE_EXTENSIONS or suffix in extra_cad_set(models) or suffix in extra_cad_set(extras):
        return ObjectType.CAD
    if _is_intermediate_cl(filename):
        return ObjectType.CAD
    if suffix in extra_cad_set(documents):
        if mapped in DOCUMENT_OBJECT_TYPES:
            return mapped
        return ObjectType.DOCUMENT
    return OBJECT_TYPE_BY_EXTENSION.get(suffix, ObjectType.OTHER)


def _is_intermediate_cl(filename: str) -> bool:
    """True for Creo intermediate CL files such as op10.ncl.tl1."""
    name = Path(str(filename).replace("\\", "/")).name.lower()
    return fnmatch.fnmatch(name, "*.ncl.tl*")


def default_folder_for(object_type: ObjectType | str) -> str:
    if isinstance(object_type, str):
        try:
            object_type = ObjectType(object_type)
        except ValueError:
            return DEFAULT_FOLDER_BY_TYPE[ObjectType.OTHER]
    return DEFAULT_FOLDER_BY_TYPE.get(object_type, DEFAULT_FOLDER_BY_TYPE[ObjectType.OTHER])


def is_creo_openable(
    filename: str,
    model_extensions: Iterable[str] | None = None,
    extra_cad_extensions: Iterable[str] | None = None,
) -> bool:
    models = unique_extensions(
        DEFAULT_CREO_MODEL_EXTENSIONS if model_extensions is None else model_extensions
    )
    extras = unique_extensions(
        default_data_cad_extensions() if extra_cad_extensions is None else extra_cad_extensions
    )
    canonical = CreoFileManager.normalize_creo_filename(filename, (*models, *extras))
    return Path(canonical).suffix.lower() in extra_cad_set(models)


def is_extra_cad(
    filename: str,
    extra_cad_extensions: Iterable[str] | None = None,
    model_extensions: Iterable[str] | None = None,
) -> bool:
    """True for non-openable CAD data Creo does not open."""
    models = unique_extensions(
        DEFAULT_CREO_MODEL_EXTENSIONS if model_extensions is None else model_extensions
    )
    extras = unique_extensions(
        DEFAULT_EXTRA_CAD_EXTENSIONS if extra_cad_extensions is None else extra_cad_extensions
    )
    canonical = CreoFileManager.normalize_creo_filename(
        filename,
        (*models, *default_data_cad_extensions()),
    )
    suffix = Path(canonical).suffix.lower()
    return suffix in extra_cad_set(extras) and suffix not in extra_cad_set(models)


def default_type_label(object_type: str) -> str:
    return str(object_type or "").replace("_", " ").title() or "Other"


def unique_type_labels(values: object) -> list[dict[str, str]]:
    items: list[object]
    if values is None or isinstance(values, (str, bytes)):
        items = []
    elif isinstance(values, dict):
        items = [{"extension": key, "label": value} for key, value in values.items()]
    else:
        try:
            items = list(values)
        except TypeError:
            items = []
    found: list[dict[str, str]] = []
    index_by_key: dict[tuple[str, ...], int] = {}
    for raw in items:
        if isinstance(raw, dict):
            raw_ext = str(raw.get("extension") or raw.get("ext") or "")
            label = str(raw.get("label") or raw.get("name") or "").strip()
        else:
            raw_ext = str(getattr(raw, "extension", "") or "")
            label = str(getattr(raw, "label", "") or "").strip()
        tokens = parse_type_label_tokens(raw_ext)
        if not tokens or not label:
            continue
        entry = {"extension": ", ".join(tokens), "label": label}
        key = tuple(sorted(tokens))
        existing = index_by_key.get(key)
        if existing is None:
            index_by_key[key] = len(found)
            found.append(entry)
        else:
            found[existing] = entry
    return found


def type_label_maps(values: object) -> tuple[dict[str, str], dict[str, str]]:
    """Return (file-name map, extension map). File names win over extensions."""
    names: dict[str, str] = {}
    extensions: dict[str, str] = {}
    for item in unique_type_labels(values):
        for token in parse_type_label_tokens(item["extension"]):
            if token.startswith("."):
                extensions[token] = item["label"]
            else:
                names[token] = item["label"]
    return names, extensions


def display_type_label(
    filename: str,
    object_type: str,
    labels: object = None,
    names: dict[str, str] | None = None,
    extensions: dict[str, str] | None = None,
) -> str:
    """Custom Type-column name for a file name or extension, or the usual label."""
    if names is None or extensions is None:
        mapped_names, mapped_exts = type_label_maps(labels)
        names = mapped_names if names is None else names
        extensions = mapped_exts if extensions is None else extensions
    if names or extensions:
        canonical = CreoFileManager.normalize_creo_filename(filename)
        basename = Path(canonical).name.lower()
        original = Path(str(filename).replace("\\", "/")).name.lower()
        custom = names.get(basename) or names.get(original)
        if custom:
            return custom
        suffix = Path(canonical).suffix.lower()
        custom = extensions.get(suffix)
        if custom:
            return custom
        for token, label in names.items():
            if _matches_type_label_pattern(basename, original, token):
                return label
        for token, label in extensions.items():
            if _matches_type_label_pattern(basename, original, token):
                return label
    return default_type_label(object_type)


def _matches_type_label_pattern(basename: str, original: str, token: str) -> bool:
    if "*" not in token and "?" not in token:
        return False
    patterns = [token]
    if token.startswith(".") and not token.startswith("*"):
        patterns.append(f"*{token}")
    names = (basename, original)
    return any(fnmatch.fnmatch(name, pattern) for name in names for pattern in patterns)
