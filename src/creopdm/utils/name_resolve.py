"""Pick the right file when several files of a product share a name.

Creo reports the parts of an assembly (and the parents of a part) by NAME only: ``plate.prt``, with no
folder. When ``folderA/plate.prt`` and ``folderB/plate.prt`` both exist, a name alone cannot say which
one is meant, and taking the first match links the wrong file (wrong BOM / Structure link, wrong Where
Used parent). Creo itself finds a component next to the assembly first, so the file nearest the
referencing file's folder wins; when two are equally near the reference is left unresolved rather
than guessed. Files are always identified by their UUID afterwards.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

T = TypeVar("T")


def _folder_parts(relative_path: str) -> list[str]:
    text = str(relative_path or "").replace("\\", "/").strip("/")
    parts = [part for part in text.split("/") if part]
    return [part.lower() for part in parts[:-1]]


def pick_nearest(
    candidates: Sequence[T],
    referencing_path: str,
    rel_of: Callable[[T], str] = lambda item: getattr(item, "relative_path", "") or "",
) -> T | None:
    """The candidate in (or nearest to) the folder of ``referencing_path``; None if unclear.

    One candidate is that candidate. Several: the one in the same folder, else the one sharing the
    longest folder prefix with the referencing file, else the shallowest difference in depth. Two
    candidates that are equally near give None.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    home = _folder_parts(referencing_path)

    def score(item: T) -> tuple[int, int, int]:
        folder = _folder_parts(rel_of(item))
        common = 0
        for mine, theirs in zip(home, folder):
            if mine != theirs:
                break
            common += 1
        return (1 if folder == home else 0, common, -abs(len(folder) - len(home)))

    ranked = sorted(candidates, key=score, reverse=True)
    if score(ranked[0]) == score(ranked[1]):
        return None
    return ranked[0]


def add_candidate(index: dict[str, list[Any]], key: str, item: Any, same: Callable[[Any, Any], bool]) -> None:
    """Add ``item`` under ``key`` once (the same file can reach a key through several name forms)."""
    bucket = index.setdefault(key, [])
    if not any(same(existing, item) for existing in bucket):
        bucket.append(item)
