"""Multi-pattern byte matcher for Creo filenames embedded in vault files.

Used by Where Used vault indexing and companion open narrowing. Aho-Corasick
keeps large-project scans roughly O(file_bytes + pattern_bytes) instead of
O(file_bytes × candidate_count).
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from creopdm.creo.file_manager import CreoFileManager


class CadNameMatcher:
    """Match logical Creo filenames (and stems) inside a lowercased byte blob."""

    __slots__ = ("_goto", "_fail", "_out", "_logicals")

    def __init__(self, filenames: list[str] | tuple[str, ...]) -> None:
        token_to_logicals: dict[bytes, list[str]] = {}
        for name in filenames:
            logical = CreoFileManager.normalize_creo_filename(name).lower()
            if not logical:
                continue
            stem = Path(logical).stem.lower()
            for token in {logical.encode("ascii", "ignore"), stem.encode("ascii", "ignore")}:
                if len(token) < 2:
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
