"""Creo filename and canonical-file policy. Isolated so the strategy can change."""

from __future__ import annotations

from pathlib import Path

from creopdm.constants import CREO_FILE_EXTENSIONS


class CreoFileManager:
    """Handles Creo numbered filenames and canonical repository copies."""

    @staticmethod
    def is_creo_extension(extension: str) -> bool:
        return extension.lower() in CREO_FILE_EXTENSIONS

    @staticmethod
    def normalize_creo_filename(filename: str) -> str:
        """Strip Creo save-version suffixes from known Creo files only.

        Examples:
            shaft.prt.1   -> shaft.prt
            shaft.prt.25  -> shaft.prt
            motor.asm.7   -> motor.asm
            layout.drw.3  -> layout.drw
            notes.txt.1   -> notes.txt.1   (not a Creo extension)
            report.2024   -> report.2024   (numeric suffix is not after a Creo ext)
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
        if f".{extension.lower()}" not in CREO_FILE_EXTENSIONS:
            return name
        return f"{stem}.{extension}"

    @classmethod
    def canonical_repository_name(cls, filename: str) -> str:
        """Filename stored in the repository. Creo save numbers such as .prt.3 are kept."""
        return Path(str(filename).replace("\\", "/")).name

    @classmethod
    def logical_filename(cls, filename: str) -> str:
        """Logical Creo model name used to match numbered siblings."""
        return cls.normalize_creo_filename(filename)

    @classmethod
    def logical_repo_path(cls, relative_path: str) -> str:
        path = Path(str(relative_path).replace("\\", "/"))
        name = cls.logical_filename(path.name)
        parent = path.parent
        if parent.as_posix() == ".":
            return name.lower()
        return (parent / name).as_posix().lower()

    @classmethod
    def select_latest_creo_version(cls, paths: list[Path]) -> Path | None:
        """Choose the highest numbered Creo save among sibling files."""
        best: tuple[int, Path] | None = None
        unnumbered: Path | None = None
        for path in paths:
            name = path.name
            normalized = cls.normalize_creo_filename(name)
            if normalized == name:
                if cls.is_creo_extension(path.suffix):
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
    def latest_in_directory(cls, directory: Path, canonical_name: str) -> Path | None:
        """Return the newest Creo save (or the canonical file) for a logical object."""
        if not directory.is_dir():
            return None
        wanted = cls.logical_filename(canonical_name).lower()
        matches: list[Path] = []
        for path in directory.iterdir():
            if not path.is_file():
                continue
            if cls.logical_filename(path.name).lower() == wanted:
                matches.append(path)
        if not matches:
            fallback = directory / canonical_name
            return fallback if fallback.is_file() else None
        return cls.select_latest_creo_version(matches) or matches[0]
