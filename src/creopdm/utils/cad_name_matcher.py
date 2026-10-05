"""Multi-pattern byte matcher for Creo filenames embedded in vault files.

Used by Where Used vault indexing and open-dependency narrowing. Aho-Corasick
keeps large-product scans roughly O(file_bytes + pattern_bytes) instead of
O(file_bytes × candidate_count).
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from creopdm.creo.file_manager import CreoFileManager


class CadNameMatcher:
    """Match logical Creo filenames inside a lowercased byte blob.

    ``include_stems`` also matches the bare stem (``shaft`` for ``shaft.prt``).
    That helps Open find neighbors when Creo omits the extension, but it causes
    false Where Used parents (part numbers / short names appearing anywhere in
    unrelated assemblies). Where Used indexing should pass ``include_stems=False``.
    """

    __slots__ = ("_goto", "_fail", "_out", "_logicals")

    def __init__(
        self,
        filenames: list[str] | tuple[str, ...],
        *,
        include_stems: bool = True,
    ) -> None:
        token_to_logicals: dict[bytes, list[str]] = {}
        for name in filenames:
            logical = CreoFileManager.normalize_creo_filename(name).lower()
            if not logical:
                continue
            tokens = {logical.encode("ascii", "ignore")}
            if include_stems:
                stem = Path(logical).stem.lower()
                tokens.add(stem.encode("ascii", "ignore"))
            for token in tokens:
                if len(token) < 2:
                    continue
                # Extension-only mode: skip tokens with no '.' (bare stems).
                if not include_stems and b"." not in token:
                    continue
                bucket = token_to_logicals.setdefault(token, [])
                if logical not in bucket:
                    bucket.append(logical)

        patterns = list(token_to_logicals.keys())
        self._logicals = [token_to_logicals[pat] for pat in patterns]
        self._goto, self._fail, self._out = _build_aho(patterns)

    def find(self, lower_blob: bytes) -> set[str]:
        """Return logical filenames whose token appears in ``lower_blob``."""
        if not self._logicals or not lower_blob:
            return set()
        state = 0
        found: set[str] = set()
        goto = self._goto
        fail = self._fail
        out = self._out
        logicals = self._logicals
        for byte in lower_blob:
            while state and byte not in goto[state]:
                state = fail[state]
            state = goto[state].get(byte, 0)
            for pattern_index in out[state]:
                found.update(logicals[pattern_index])
        return found


def _build_aho(
    patterns: list[bytes],
) -> tuple[list[dict[int, int]], list[int], list[list[int]]]:
    goto: list[dict[int, int]] = [{}]
    out: list[list[int]] = [[]]
    for index, pattern in enumerate(patterns):
        state = 0
        for byte in pattern:
            nxt = goto[state].get(byte)
            if nxt is None:
                nxt = len(goto)
                goto[state][byte] = nxt
                goto.append({})
                out.append([])
            state = nxt
        out[state].append(index)

    fail = [0] * len(goto)
    queue: deque[int] = deque()
    for state in goto[0].values():
        queue.append(state)
        fail[state] = 0
    while queue:
        r = queue.popleft()
        for byte, s in goto[r].items():
            queue.append(s)
            f = fail[r]
            while f and byte not in goto[f]:
                f = fail[f]
            fail[s] = goto[f].get(byte, 0)
            if fail[s]:
                out[s].extend(out[fail[s]])
    return goto, fail, out


__all__ = ["CadNameMatcher"]
