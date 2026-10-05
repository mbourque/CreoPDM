"""Multi-pattern byte matcher for Creo filenames embedded in vault files.

Used by Where Used vault indexing and open-dependency narrowing. Aho-Corasick
keeps large-product scans roughly O(file_bytes + pattern_bytes) instead of
O(file_bytes × candidate_count).
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from creopdm.creo.file_manager import CreoFileManager


def is_creo_name_char(byte: int) -> bool:
    """Alphanumeric or underscore — characters that glue Creo names together."""
    return (
        48 <= byte <= 57  # 0-9
        or 97 <= byte <= 122  # a-z (blob is lowercased)
        or byte == 95  # _
    )


def token_has_name_boundaries(blob: bytes, start: int, end: int) -> bool:
    """True when ``blob[start:end]`` is not glued to a longer Creo name token."""
    if start < 0 or end > len(blob) or start >= end:
        return False
    if start > 0 and is_creo_name_char(blob[start - 1]):
        return False
    if end < len(blob) and is_creo_name_char(blob[end]):
        return False
    return True


def find_bounded_token(blob: bytes, token: bytes) -> bool:
    """True when ``token`` appears in ``blob`` with Creo name boundaries."""
    if not token or not blob:
        return False
    start = 0
    while True:
        index = blob.find(token, start)
        if index < 0:
            return False
        end = index + len(token)
        if token_has_name_boundaries(blob, index, end):
            return True
        start = index + 1


class CadNameMatcher:
    """Match logical Creo filenames inside a lowercased byte blob.

    ``include_stems`` also matches the bare stem (``shaft`` for ``shaft.prt``).
    Creo often stores component names without the extension. Where Used should
    use stems **with** ``require_boundaries=True`` so ``1003573`` glued inside
    another token is ignored, but a real ``\\0shaft\\0`` component still matches.
    """

    __slots__ = ("_goto", "_fail", "_out", "_logicals", "_lengths", "_require_boundaries")

    def __init__(
        self,
        filenames: list[str] | tuple[str, ...],
        *,
        include_stems: bool = True,
        require_boundaries: bool | None = None,
        min_stem_len: int = 2,
        unique_stems_only: bool = False,
    ) -> None:
        # Prefer explicit require_boundaries; else stems-only Open stays loose,
        # extension-only mode stays strict.
        self._require_boundaries = (
            (not include_stems) if require_boundaries is None else bool(require_boundaries)
        )
        logicals: list[str] = []
        stem_counts: dict[str, int] = {}
        for name in filenames:
            logical = CreoFileManager.normalize_creo_filename(name).lower()
            if not logical:
                continue
            logicals.append(logical)
            if include_stems:
                stem = Path(logical).stem.lower()
                if stem:
                    stem_counts[stem] = stem_counts.get(stem, 0) + 1

        token_to_logicals: dict[bytes, list[str]] = {}
        for logical in logicals:
            tokens = {logical.encode("ascii", "ignore")}
            if include_stems:
                stem = Path(logical).stem.lower()
                if len(stem) >= max(2, int(min_stem_len)) and (
                    not unique_stems_only or stem_counts.get(stem, 0) == 1
                ):
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
        self._lengths = [len(pat) for pat in patterns]
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
        lengths = self._lengths
        require_boundaries = self._require_boundaries
        for index, byte in enumerate(lower_blob):
            while state and byte not in goto[state]:
                state = fail[state]
            state = goto[state].get(byte, 0)
            for pattern_index in out[state]:
                if require_boundaries:
                    end = index + 1
                    start = end - lengths[pattern_index]
                    if not token_has_name_boundaries(lower_blob, start, end):
                        continue
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


__all__ = [
    "CadNameMatcher",
    "find_bounded_token",
    "is_creo_name_char",
    "token_has_name_boundaries",
]
