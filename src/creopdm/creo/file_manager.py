"""Creo filename and canonical-file policy. Isolated so the strategy can change."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path

from creopdm.constants import (
    CREO_FILE_EXTENSIONS,
    DEFAULT_CREO_MODEL_EXTENSIONS,
    DEFAULT_EXTRA_CAD_EXTENSIONS,
    DEFAULT_OPENABLE_CAD_EXTENSIONS,
)

_UUIDISH_STEM = re.compile(
    r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{6,12}$",
    re.IGNORECASE,
)
_SKIP_IMPORT_DIRS = {".git", ".creopdm", "__pycache__"}
_SKIP_IMPORT_SUFFIXES = {".bak", ".tmp"}


def common_import_root(paths: Iterable[Path]) -> Path | None:
    """Shared ancestor when files span sibling subfolders (preserves nest on import).

    Returns None for a single file or for siblings that already share one parent —
    those stay flat at the vault root unless the caller passes an explicit base folder.
    """
    resolved: list[Path] = []
    for raw in paths:
        try:
            path = Path(raw).resolve()
        except OSError:
            continue
        if path.is_file() or path.exists():
            resolved.append(path)
    if len(resolved) < 2:
        return None
    parents = {path.parent for path in resolved}
    if len(parents) <= 1:
        return None
    try:
        common = Path(os.path.commonpath([str(path) for path in resolved]))
    except ValueError:
        return None
    if common.is_file():
        return None
    return common


def _dot_ext(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return text if text.startswith(".") else f".{text}"


_EXTRA_CAD_ONLY = frozenset(
    _dot_ext(item) for item in (*DEFAULT_OPENABLE_CAD_EXTENSIONS, *DEFAULT_EXTRA_CAD_EXTENSIONS)
)


class CreoFileManager:
    """Handles Creo numbered filenames and canonical repository copies."""

    @staticmethod
    def versioned_extensions(extra_extensions: Iterable[str] | None = None) -> frozenset[str]:
        """Extensions that use Creo-style .ext.N save numbers.

        ``None`` → built-in CAD defaults (Creo models + openable + extra).
        An explicit list (e.g. Settings → Purgeable) is the sole authority used
        when omitting older numbered saves on import — do not also union the
        built-in Creo set, or removing ``.prt`` from Purgeable would be ignored.
        """
        if extra_extensions is None:
            extras: Iterable[str] = (
                *DEFAULT_CREO_MODEL_EXTENSIONS,
                *DEFAULT_OPENABLE_CAD_EXTENSIONS,
                *DEFAULT_EXTRA_CAD_EXTENSIONS,
            )
            known = set(CREO_FILE_EXTENSIONS)
        else:
            extras = extra_extensions
            known = set()
        for item in extras:
            ext = _dot_ext(item)
            if ext:
                known.add(ext)
        return frozenset(known)

    @classmethod
    def is_ignored(
        cls,
        filename: str,
        ignore_patterns: Iterable[str] | None = None,
    ) -> bool:
        """True for session junk that must never be stored or listed."""
        from creopdm.utils.ignore import is_ignored_name

        name = Path(str(filename).replace("\\", "/")).name
        if is_ignored_name(name, ignore_patterns):
            return True
        logical = cls.normalize_creo_filename(name)
        if Path(logical).suffix.lower() == ".idx" and _UUIDISH_STEM.match(Path(logical).stem):
            return True
        return False

    @classmethod
    def is_workspace_transient(
        cls,
        filename: str,
        ignore_patterns: Iterable[str] | None = None,
    ) -> bool:
        return cls.is_ignored(filename, ignore_patterns)

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
    def _numbered_save(
        cls,
        filename: str,
        extra_extensions: Iterable[str] | None = None,
    ) -> tuple[str, int]:
        """Return (logical_name, save_number). 0 means the file is unnumbered.

        Creo-openable models accept both name.ext.N and name.N.ext.
        Extra CAD only uses name.ext.N.
        """
        name = Path(str(filename).replace("\\", "/")).name
        if not name:
            return name, 0
        parts = name.split(".")
        if len(parts) < 3 or not parts[0]:
            return name, 0
        last = parts[-1]
        prev = parts[-2]
        if last.isdigit() and cls.is_versioned_extension(f".{prev}", extra_extensions):
            return ".".join(parts[:-1]), int(last)
        if (
            prev.isdigit()
            and cls.is_versioned_extension(f".{last}", extra_extensions)
            and _dot_ext(last) not in _EXTRA_CAD_ONLY
        ):
            return ".".join((*parts[:-2], last)), int(prev)
        return name, 0

    @classmethod
    def normalize_creo_filename(
        cls,
        filename: str,
        extra_extensions: Iterable[str] | None = None,
    ) -> str:
        """Strip save-version numbers from CAD files.

        Examples:
            shaft.prt.1   -> shaft.prt
            shaft.1.prt   -> shaft.prt
            preview.2.pvz -> preview.pvz
            setup.inf.1   -> setup.inf
            setup.1.inf   -> setup.1.inf   (extra CAD is .ext.N only)
            notes.txt.1   -> notes.txt.1
            report.2024   -> report.2024
        """
        logical, _number = cls._numbered_save(filename, extra_extensions)
        return logical

    @classmethod
    def save_number(
        cls,
        filename: str,
        extra_extensions: Iterable[str] | None = None,
    ) -> int:
        """Save number from name.ext.N or, for Creo-openable models, name.N.ext."""
        _logical, number = cls._numbered_save(filename, extra_extensions)
        return number

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
            version = cls.save_number(name, extra_extensions)
            if version == 0:
                if cls.is_versioned_extension(path.suffix, extra_extensions):
                    unnumbered = path
                continue
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
        scan_disk_siblings: bool = True,
    ) -> list[Path]:
        """Keep one file per CAD family: the highest .ext.N. Unnumbered is older."""
        grouped: dict[str, list[Path]] = {}
        order: list[str] = []
        seen: dict[str, set[str]] = {}

        def path_id(path: Path) -> str:
            return os.path.normcase(os.path.abspath(path))

        def group_key(path: Path) -> str:
            parent = os.path.normcase(os.path.abspath(path.parent))
            logical = cls.logical_filename(path.name, extra_extensions).lower()
            return f"{parent}/{logical}"

        def add(key: str, path: Path, check_exists: bool) -> None:
            if check_exists and not path.is_file():
                return
            ident = path_id(path)
            bucket = seen.setdefault(key, set())
            if ident in bucket:
                return
            bucket.add(ident)
            grouped.setdefault(key, []).append(path)

        for path in paths:
            key = group_key(path)
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            add(key, path, check_exists=scan_disk_siblings)
            if not scan_disk_siblings:
                continue
            parent = path.parent
            if parent.is_dir() and cls.is_cad_save_family(path.name, extra_extensions):
                logical = cls.logical_filename(path.name, extra_extensions).lower()
                for sibling in parent.iterdir():
                    if sibling.is_file() and cls.logical_filename(sibling.name, extra_extensions).lower() == logical:
                        add(key, sibling, check_exists=False)

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
        ignore_patterns: Iterable[str] | None = None,
        *,
        recursive: bool = True,
    ) -> Iterator[Path]:
        """Walk a folder for files that can be added to a project."""
        folder = Path(root)
        if not folder.is_dir():
            return
        if not recursive:
            try:
                names = list(folder.iterdir())
            except OSError:
                return
            for path in names:
                if not path.is_file():
                    continue
                name = path.name
                if name.startswith("."):
                    continue
                if cls.is_ignored(name, ignore_patterns):
                    continue
                suffix = path.suffix.lower()
                numbered = cls.normalize_creo_filename(name, extra_extensions)
                check = Path(numbered).suffix.lower() if numbered != name else suffix
                if check in _SKIP_IMPORT_SUFFIXES or suffix in _SKIP_IMPORT_SUFFIXES:
                    continue
                yield path
            return
        for dirpath, dirnames, filenames in os.walk(folder):
            dirnames[:] = [name for name in dirnames if name.lower() not in _SKIP_IMPORT_DIRS]
            current = Path(dirpath)
            for name in filenames:
                if name.startswith("."):
                    continue
                if cls.is_ignored(name, ignore_patterns):
                    continue
                path = current / name
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
        ignore_patterns: Iterable[str] | None = None,
        *,
        recursive: bool = True,
    ) -> list[Path]:
        return cls.filter_to_latest_saves(
            list(
                cls.iter_importable_files(
                    root,
                    extra_extensions,
                    ignore_patterns,
                    recursive=recursive,
                )
            ),
            extra_extensions,
            scan_disk_siblings=False,
        )

    @classmethod
    def filenames_older_than_floor(
        cls,
        names: Iterable[str],
        min_keep: int,
        model_extensions: Iterable[str] | None = None,
        logical_name: str | None = None,
    ) -> list[str]:
        """Return sibling basenames with save_number strictly below ``min_keep``.

        Vault floor semantics: keep ``== min_keep`` and ``> min_keep``. Unnumbered
        saves are 0, so they are deleted only when ``min_keep > 0``. When
        ``min_keep <= 0``, nothing is returned (vault unnumbered → purge nothing).
        """
        floor = int(min_keep or 0)
        if floor <= 0:
            return []
        wanted = (
            cls.logical_filename(logical_name, model_extensions).lower()
            if logical_name
            else ""
        )
        obsolete: list[str] = []
        for raw in names:
            name = Path(str(raw or "").replace("\\", "/")).name
            if not name:
                continue
            if wanted and cls.logical_filename(name, model_extensions).lower() != wanted:
                continue
            if cls.save_number(name, model_extensions) < floor:
                obsolete.append(name)
        obsolete.sort(
            key=lambda name: (
                cls.logical_filename(name, model_extensions).lower(),
                cls.save_number(name, model_extensions),
                name.lower(),
            )
        )
        return obsolete

    @classmethod
    def paths_older_than_vault_floors(
        cls,
        root: Path,
        floors: Iterable[tuple[str, int]],
        model_extensions: Iterable[str] | None = None,
    ) -> list[Path]:
        """Local-cache paths older than each vault floor (logical_path, min_keep).

        Only siblings of listed logical relative paths are considered. Floors with
        ``min_keep <= 0`` are skipped. Non-matching / untracked files are untouched.

        The agent cache is usually flat (basename only) while vault objects may be
        nested (``Documents/part.prt``). When a nested parent folder is missing —
        or when the logical basename is unique among floors — also scan the cache
        root so older ``part.prt.N`` saves are still purged.
        """
        folder = Path(root)
        if not folder.is_dir():
            return []
        parsed: list[tuple[str, int, Path]] = []
        basename_counts: dict[str, int] = {}
        for raw_logical, min_keep in floors:
            floor = int(min_keep or 0)
            if floor <= 0:
                continue
            logical_rel = str(raw_logical or "").replace("\\", "/").lstrip("/")
            if not logical_rel or ".." in logical_rel.split("/"):
                continue
            logical_path = Path(logical_rel)
            wanted = cls.logical_filename(logical_path.name, model_extensions).lower()
            if not wanted:
                continue
            parsed.append((logical_rel, floor, logical_path))
            basename_counts[wanted] = basename_counts.get(wanted, 0) + 1

        obsolete: list[Path] = []
        seen: set[str] = set()
        folder_resolved = folder.resolve()
        for _logical_rel, floor, logical_path in parsed:
            wanted = cls.logical_filename(logical_path.name, model_extensions).lower()
            parents: list[Path] = []
            nested_parent = folder / logical_path.parent
            if nested_parent.is_dir():
                parents.append(nested_parent)
            # Flat agent cache: Documents/shaft.prt → shaft.prt.1 at cache root.
            nested = logical_path.parent.as_posix() not in ("", ".")
            if nested and basename_counts.get(wanted, 0) == 1 and folder.is_dir():
                if not any(parent.resolve() == folder_resolved for parent in parents):
                    parents.append(folder)
            if not parents:
                continue
            for parent in parents:
                for child in parent.iterdir():
                    if not child.is_file():
                        continue
                    if not cls.is_cad_save_family(child.name, model_extensions):
                        continue
                    if cls.logical_filename(child.name, model_extensions).lower() != wanted:
                        continue
                    if cls.save_number(child.name, model_extensions) >= floor:
                        continue
                    ident = os.path.normcase(os.path.abspath(child))
                    if ident in seen:
                        continue
                    seen.add(ident)
                    obsolete.append(child)
        obsolete.sort(
            key=lambda path: (
                path.parent.as_posix().lower(),
                cls.logical_filename(path.name, model_extensions).lower(),
                cls.save_number(path.name, model_extensions),
                path.name.lower(),
            )
        )
        return obsolete
