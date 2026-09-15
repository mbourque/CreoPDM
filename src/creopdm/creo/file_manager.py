"""Creo filename and canonical-file policy. Isolated so the strategy can change."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path

from creopdm.constants import CREO_FILE_EXTENSIONS, DEFAULT_EXTRA_CAD_EXTENSIONS

_TRAIL_FILE = re.compile(r"^trail\.txt(?:\.\d+)?$", re.IGNORECASE)
_UUIDISH_STEM = re.compile(
    r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{6,12}$",
    re.IGNORECASE,
)
_SKIP_IMPORT_DIRS = {".git", ".creopdm", "__pycache__"}
_SKIP_IMPORT_SUFFIXES = {".tst", ".err", ".lst", ".bak", ".tmp", ".acl"}


def _dot_ext(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return text if text.startswith(".") else f".{text}"


class CreoFileManager:
    """Handles Creo numbered filenames and canonical repository copies."""

    @staticmethod
    def versioned_extensions(extra_extensions: Iterable[str] | None = None) -> frozenset[str]:
        """Extensions that use Creo-style .ext.N save numbers."""
        extras = DEFAULT_EXTRA_CAD_EXTENSIONS if extra_extensions is None else extra_extensions
        known = set(CREO_FILE_EXTENSIONS)
        for item in extras:
            ext = _dot_ext(item)
            if ext:
                known.add(ext)
        return frozenset(known)

    @classmethod
    def is_workspace_transient(cls, filename: str) -> bool:
        """Creo session junk that should never be added as a PDM object."""
        name = Path(str(filename).replace("\\", "/")).name
        lower = name.lower()
        if lower in {"std.out", "std.err"}:
            return True
        if _TRAIL_FILE.match(lower):
            return True
        logical = cls.normalize_creo_filename(name)
        if Path(logical).suffix.lower() == ".idx" and _UUIDISH_STEM.match(Path(logical).stem):
            return True
        return False

    @classmethod
    def is_creo_extension(cls, extension: str) -> bool:
        return _dot_ext(extension) in CREO_FILE_EXTENSIONS

    @classmethod
    def is_versioned_extension(
        cls,
        extension: str,
        extra_extensions: Iterable[str] | None = None,
    ) -> bool:
        return _dot_ext(extension) in cls.versioned_extensions(extra_extensions)

    @classmethod
    def normalize_creo_filename(
        cls,
        filename: str,
        extra_extensions: Iterable[str] | None = None,
    ) -> str:
        """Strip save-version suffixes from CAD files that use .ext.N numbering.

        Examples:
            shaft.prt.1   -> shaft.prt
            setup.inf.1   -> setup.inf
            outline.dxf.4 -> outline.dxf
            notes.txt.1   -> notes.txt.1   (not a versioned CAD extension)
            report.2024   -> report.2024
        """
        name = Path(str(filename).replace("\\", "/")).name
        if not name:
            return name
        parts = name.rsplit(".", 2)
        if len(parts) != 3:
            return name
        stem, extension, suffix = parts
        if not stem or not suffix.isdigit():
            return name
        if f".{extension.lower()}" not in cls.versioned_extensions(extra_extensions):
            return name
        return f"{stem}.{extension}"

    @classmethod
    def canonical_repository_name(cls, filename: str) -> str:
        """Filename stored in the repository. Creo save numbers such as .prt.3 are kept."""
        return Path(str(filename).replace("\\", "/")).name

    @classmethod
    def logical_filename(
        cls,
        filename: str,
        extra_extensions: Iterable[str] | None = None,
    ) -> str:
        """Logical CAD name used to match numbered siblings."""
        return cls.normalize_creo_filename(filename, extra_extensions)

    @classmethod
    def logical_repo_path(
        cls,
        relative_path: str,
        extra_extensions: Iterable[str] | None = None,
    ) -> str:
        path = Path(str(relative_path).replace("\\", "/"))
        name = cls.logical_filename(path.name, extra_extensions)
        parent = path.parent
        if parent.as_posix() == ".":
            return name.lower()
        return (parent / name).as_posix().lower()

    @classmethod
    def select_latest_creo_version(
        cls,
        paths: list[Path],
        extra_extensions: Iterable[str] | None = None,
    ) -> Path | None:
        """Choose the highest numbered save among sibling files."""
        best: tuple[int, Path] | None = None
        unnumbered: Path | None = None
        for path in paths:
            name = path.name
            normalized = cls.normalize_creo_filename(name, extra_extensions)
            if normalized == name:
                if cls.is_versioned_extension(path.suffix, extra_extensions):
                    unnumbered = path
                continue
            suffix = name.rsplit(".", 1)[-1]
            if suffix.isdigit():
                version = int(suffix)
                if best is None or version > best[0]:
                    best = (version, path)
        if best is not None:
            return best[1]
        return unnumbered

    @classmethod
    def latest_in_directory(
        cls,
        directory: Path,
        canonical_name: str,
        extra_extensions: Iterable[str] | None = None,
    ) -> Path | None:
        """Return the newest numbered save (or the canonical file) for a logical object."""
        if not directory.is_dir():
            return None
        wanted = cls.logical_filename(canonical_name, extra_extensions).lower()
        matches: list[Path] = []
        for path in directory.iterdir():
            if not path.is_file():
                continue
            if cls.logical_filename(path.name, extra_extensions).lower() == wanted:
                matches.append(path)
        if not matches:
            fallback = directory / canonical_name
            return fallback if fallback.is_file() else None
        return cls.select_latest_creo_version(matches, extra_extensions) or matches[0]

    @classmethod
    def is_cad_save_family(cls, filename: str, extra_extensions: Iterable[str] | None = None) -> bool:
        name = Path(filename).name
        if cls.normalize_creo_filename(name, extra_extensions) != name:
            return True
        return cls.is_versioned_extension(Path(name).suffix, extra_extensions)

    @classmethod
    def filter_to_latest_saves(
        cls,
        paths: list[Path],
        extra_extensions: Iterable[str] | None = None,
    ) -> list[Path]:
        """Keep one file per CAD family: the highest .ext.N. Unnumbered is older."""
        grouped: dict[str, list[Path]] = {}
        order: list[str] = []
        seen: dict[str, set[str]] = {}

        def group_key(path: Path) -> str:
            parent = path.resolve().parent.as_posix().lower()
            logical = cls.logical_filename(path.name, extra_extensions).lower()
            return f"{parent}/{logical}"

        def add(key: str, path: Path) -> None:
            if not path.is_file():
                return
            ident = str(path.resolve()).lower()
            bucket = seen.setdefault(key, set())
            if ident in bucket:
                return
            bucket.add(ident)
            grouped.setdefault(key, []).append(path.resolve())

        for path in paths:
            key = group_key(path)
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            add(key, path)
            parent = path.parent
            if parent.is_dir() and cls.is_cad_save_family(path.name, extra_extensions):
                logical = cls.logical_filename(path.name, extra_extensions).lower()
                for sibling in parent.iterdir():
                    if sibling.is_file() and cls.logical_filename(sibling.name, extra_extensions).lower() == logical:
                        add(key, sibling)

        chosen: list[Path] = []
        for key in order:
            family = grouped.get(key) or []
            if not family:
                continue
            latest = cls.select_latest_creo_version(family, extra_extensions)
            chosen.append(latest if latest is not None else family[0])
        return chosen

    @classmethod
    def iter_importable_files(
        cls,
        root: Path,
        extra_extensions: Iterable[str] | None = None,
    ) -> Iterator[Path]:
        """Walk a folder for files that can be added to a project."""
        folder = Path(root)
        if not folder.is_dir():
            return
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [name for name in dirnames if name.lower() not in _SKIP_IMPORT_DIRS]
            current = Path(dirpath)
            for name in filenames:
                if name.startswith("."):
                    continue
                if cls.is_workspace_transient(name):
                    continue
                path = current / name
                if not path.is_file():
                    continue
                suffix = path.suffix.lower()
                numbered = cls.normalize_creo_filename(name, extra_extensions)
                check = Path(numbered).suffix.lower() if numbered != name else suffix
                if check in _SKIP_IMPORT_SUFFIXES or suffix in _SKIP_IMPORT_SUFFIXES:
                    continue
                yield path

    @classmethod
    def list_latest_in_folder(
        cls,
        root: Path,
        extra_extensions: Iterable[str] | None = None,
    ) -> list[Path]:
        return cls.filter_to_latest_saves(
            list(cls.iter_importable_files(root, extra_extensions)),
            extra_extensions,
        )
