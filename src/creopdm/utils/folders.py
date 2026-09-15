"""Group project files by folder for the list UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from creopdm.constants import CAD_OBJECT_TYPES, DOCUMENT_OBJECT_TYPES
from creopdm.exceptions import PathValidationError
from creopdm.utils.paths import assert_safe_relative_path


def objects_in_folder_view(objects: list[Any], current: str = "") -> list[Any]:
    """Files listed in this folder: immediate children, not nested folders."""
    current = normalize_folder_query(current)
    found = []
    for obj in objects:
        relative = str(getattr(obj, "relative_path", "") or getattr(obj, "filename", "")).replace("\\", "/")
        if folder_of(relative) == current:
            found.append(obj)
    return found


def folder_view_counts(objects: list[Any], current: str = "") -> dict[str, int]:
    """Metric chip counts for the current folder view."""
    view = objects_in_folder_view(objects, current)
    cad = {item.value for item in CAD_OBJECT_TYPES}
    docs = {item.value for item in DOCUMENT_OBJECT_TYPES}
    return {
        "files": len(view),
        "creo_parts": sum(1 for obj in view if getattr(obj, "object_type", "") == "CREO_PART"),
        "assemblies": sum(1 for obj in view if getattr(obj, "object_type", "") == "CREO_ASSEMBLY"),
        "drawings": sum(1 for obj in view if getattr(obj, "object_type", "") == "CREO_DRAWING"),
        "documents": sum(1 for obj in view if getattr(obj, "object_type", "") in docs),
        "other": sum(1 for obj in view if getattr(obj, "object_type", "") not in cad),
        "checked_out": sum(
            1
            for obj in view
            if getattr(obj, "owned_by_me", False) or getattr(obj, "checkout_user", None)
        ),
    }


def folder_of(relative_path: str) -> str:
    path = Path(str(relative_path or "").replace("\\", "/"))
    parent = path.parent.as_posix()
    return "" if parent == "." else parent


def normalize_folder_query(value: str | None) -> str:
    raw = str(value or "").replace("\\", "/").strip().strip("/")
    if not raw:
        return ""
    try:
        path = assert_safe_relative_path(raw).as_posix()
    except PathValidationError:
        return ""
    return "" if path == "." else path


def folder_crumbs(current: str) -> list[dict[str, str]]:
    current = normalize_folder_query(current)
    if not current:
        return []
    crumbs: list[dict[str, str]] = []
    parts = Path(current).parts
    for index, name in enumerate(parts):
        crumbs.append({"name": name, "path": "/".join(parts[: index + 1])})
    return crumbs


@dataclass
class _Node:
    folders: dict[str, _Node] = field(default_factory=dict)
    files: list[Any] = field(default_factory=list)

    def count_files(self) -> int:
        total = len(self.files)
        for child in self.folders.values():
            total += child.count_files()
        return total

    def latest_modified(self):
        stamps = [getattr(item, "updated_at", None) for item in self.files]
        for child in self.folders.values():
            stamps.append(child.latest_modified())
        stamps = [item for item in stamps if item is not None]
        return max(stamps) if stamps else None


def folder_list_entries(objects: list[Any], current: str = "") -> list[dict[str, Any]]:
    """Immediate folders and files in the current folder view."""
    current = normalize_folder_query(current)
    root = _Node()
    for obj in objects:
        relative = str(getattr(obj, "relative_path", "") or getattr(obj, "filename", "")).replace("\\", "/")
        parts = Path(relative).parts
        node = root
        for part in parts[:-1]:
            node = node.folders.setdefault(part, _Node())
        node.files.append(obj)

    node = root
    if current:
        for part in Path(current).parts:
            node = node.folders.get(part)
            if node is None:
                return []
    entries: list[dict[str, Any]] = []
    for name in sorted(node.folders, key=str.lower):
        child = node.folders[name]
        path = f"{current}/{name}" if current else name
        entries.append(
            {
                "kind": "folder",
                "name": name,
                "path": path,
                "depth": 0,
                "count": child.count_files(),
                "modified": child.latest_modified(),
            }
        )
    files = sorted(
        node.files,
        key=lambda item: str(getattr(item, "filename", "")).lower(),
    )
    for obj in files:
        entries.append(
            {
                "kind": "file",
                "object": obj,
                "folder": current,
                "depth": 0,
            }
        )
    return entries
