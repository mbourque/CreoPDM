"""Creo filename and canonical-file policy. Isolated so the strategy can change."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from creopdm.constants import CREO_FILE_EXTENSIONS, DEFAULT_EXTRA_CAD_EXTENSIONS


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
