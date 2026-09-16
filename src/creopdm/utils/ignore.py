"""Gitignore-style patterns for files CreoPDM never stores."""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from pathlib import Path

from creopdm.constants import DEFAULT_IGNORE_PATTERNS

GITIGNORE_BEGIN = "# BEGIN CREOPDM IGNORE"
GITIGNORE_END = "# END CREOPDM IGNORE"
_OLD_IGNORE_MARKERS = ("# Creo transients",)


def unique_ignore_patterns(values: Iterable[str] | None) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for raw in values or ():
        text = str(raw).strip()
        if not text or text.startswith("#"):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(text)
    return found


def parse_ignore_text(value: str | None) -> list[str]:
    if not value:
        return []
    chunks: list[str] = []
    for line in value.replace(",", "\n").replace(";", "\n").splitlines():
        chunks.extend(unique_ignore_patterns([line]))
    return unique_ignore_patterns(chunks)


def _candidates(filename: str) -> list[str]:
    name = Path(str(filename).replace("\\", "/")).name
    if not name:
        return []
    found = [name.lower()]
    stem, dot, suffix = name.rpartition(".")
    if dot and suffix.isdigit() and stem:
        found.append(stem.lower())
    return found


def is_ignored_name(
    filename: str,
    patterns: Iterable[str] | None = None,
) -> bool:
    """True when the basename matches a gitignore-style ignore pattern."""
    rules = unique_ignore_patterns(
        DEFAULT_IGNORE_PATTERNS if patterns is None else patterns
    )
    names = _candidates(filename)
    for pattern in rules:
        pat = pattern.lower()
        for name in names:
            if fnmatch.fnmatch(name, pat):
                return True
    return False


def gitignore_section(patterns: Iterable[str] | None = None) -> str:
    rules = unique_ignore_patterns(
        DEFAULT_IGNORE_PATTERNS if patterns is None else patterns
    )
    lines = [
        GITIGNORE_BEGIN,
        "# Session files CreoPDM never stores",
        *rules,
        GITIGNORE_END,
        "",
    ]
    return "\n".join(lines)


def sync_gitignore(path: Path, patterns: Iterable[str] | None = None) -> None:
    """Write or refresh the CreoPDM-managed ignore block."""
    section = gitignore_section(patterns)
    if not path.is_file():
        path.write_text(section, encoding="utf-8")
        return
    text = path.read_text(encoding="utf-8")
    if GITIGNORE_BEGIN in text and GITIGNORE_END in text:
        start = text.index(GITIGNORE_BEGIN)
        end = text.index(GITIGNORE_END) + len(GITIGNORE_END)
        rest = text[end:].lstrip("\n")
        prefix = text[:start]
        new_text = prefix + section + rest
        if text == new_text:
            return
        path.write_text(new_text, encoding="utf-8")
        return
    if any(marker in text for marker in _OLD_IGNORE_MARKERS):
        path.write_text(section, encoding="utf-8")
        return
    remainder = text.lstrip("\n")
    path.write_text(section + remainder, encoding="utf-8")
