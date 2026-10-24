"""Pick the right file when several files of a product share a name.

Creo reports the parts of an assembly (and the parents of a part) by NAME only: ``plate.prt``, with no
folder. A product can hold the same name in several folders (``Face_Lateral/face_mill.asm`` and
``Face_Entry-Exit/face_mill.asm``): each folder is its own set of models, independent of the others.

The rule: a name that exists once in the product is that file. A name that exists in several folders
means the file in the SAME folder as the file that refers to it, and nothing else. It is never
resolved to a same-named file in another folder, and never guessed: when the referring file's own
folder has no such file (or the referrer's folder is unknown) the reference is left unresolved.
Files are always identified by their UUID afterwards.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

T = TypeVar("T")


def folder_key(relative_path: str) -> str:
    text = str(relative_path or "").replace("\\", "/").strip("/")
    return text.rpartition("/")[0].lower()


def pick_in_folder(
    candidates: Sequence[T],
    referencing_path: str,
    rel_of: Callable[[T], str] = lambda item: getattr(item, "relative_path", "") or "",
) -> T | None:
    """The one candidate a reference from ``referencing_path`` means; None if it cannot be told.

    One candidate is that candidate. Several: the one in the referring file's own folder (exactly
    one), else None.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    home = folder_key(referencing_path)
    same = [item for item in candidates if folder_key(rel_of(item)) == home]
    return same[0] if len(same) == 1 else None


def add_candidate(index: dict[str, list[Any]], key: str, item: Any, same: Callable[[Any, Any], bool]) -> None:
    """Add ``item`` under ``key`` once (the same file can reach a key through several name forms)."""
    bucket = index.setdefault(key, [])
    if not any(same(existing, item) for existing in bucket):
        bucket.append(item)
