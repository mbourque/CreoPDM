"""Bounded Creo UGC header parse for .prt / .asm / .drw files.

The Files list never opens CAD files. Call this only when a version is stored
(add / later save / check-in). The text prefix ends at the #UGC_TOC hash run.
"""

from __future__ import annotations

import re
from pathlib import Path

from creopdm.creo.file_manager import CreoFileManager

CREO_HEADER_EXTENSIONS = frozenset({".prt", ".asm", ".drw"})
HEADER_LIMIT = 16 * 1024
READ_CHUNK = 1024
_TOC = b"#UGC_TOC"
_PRODUCT_LINE = re.compile(
    r"^#(?P<product>Creo(?:\s+Elements(?:/Pro)?)?|Pro/ENGINEER)\s+TM\s+(?P<rest>.+)$",
    re.IGNORECASE | re.MULTILINE,
)
_COPYRIGHT = re.compile(r"\(\s*c\s*\)", re.IGNORECASE)
_RESERVED_TAIL = re.compile(r"Reserved\.?\s*(.*)$", re.IGNORECASE)
_DOTTED_BUILD = re.compile(r"(\d+(?:\.\d+)+)\s*$")


def is_creo_native_model(filename: str) -> bool:
    """True for Creo parts, assemblies, and drawings, including numbered saves."""
    logical = CreoFileManager.normalize_creo_filename(filename)
    return Path(logical).suffix.lower() in CREO_HEADER_EXTENSIONS


def creo_release_for(path: Path, filename: str | None = None) -> str | None:
    """Return the Creo/Pro-E release from a native model, or None if absent/unreadable."""
    if not is_creo_native_model(filename or path.name):
        return None
    header = read_ugc_header(path)
    if not header:
        return None
    return parse_creo_release(header)


def read_ugc_header(path: Path, limit: int = HEADER_LIMIT) -> str:
    """Read ASCII until the UGC_TOC hash padding, or `limit` bytes, whichever first."""
    collected = bytearray()
    try:
        with path.open("rb") as handle:
            while len(collected) < limit:
                chunk = handle.read(min(READ_CHUNK, limit - len(collected)))
                if not chunk:
                    break
                collected.extend(chunk)
                cut = _header_cut(collected)
                if cut is not None:
                    return _decode(cut)
    except OSError:
        return ""
    return _decode(bytes(collected))


def parse_creo_release(header: str) -> str | None:
    """Read the TM product line. Prefer a trailing dotted build (13.4.1.0).

    Older Pro/ENGINEER files use names such as Wildfire 5.0 and a date code
    (M040) after Reserved; the date code is not the product version.
    """
    match = _PRODUCT_LINE.search(header.replace("\r\n", "\n"))
    if match is None:
        return None
    rest = " ".join((match.group("rest") or "").split())
    if not rest:
        return None
    parts = _COPYRIGHT.split(rest, maxsplit=1)
    marketing = parts[0].strip(" -")
    trailing = _dotted_build_after_copyright(parts[1] if len(parts) > 1 else "")
    if trailing:
        return trailing
    return marketing or None


def _dotted_build_after_copyright(text: str) -> str | None:
    blob = text.strip()
    reserved = _RESERVED_TAIL.search(blob)
    if reserved is not None:
        blob = reserved.group(1).strip()
    match = _DOTTED_BUILD.search(blob)
    if match is None:
        return None
    return match.group(1)


def _header_cut(data: bytes | bytearray) -> bytes | None:
    idx = data.find(_TOC)
    if idx < 0:
        return None
    i = idx + len(_TOC)
    n = len(data)
    while i < n and data[i] in b" \t0123456789":
        i += 1
    if i >= n:
        return None
    if data[i] != ord("#"):
        newline = data.find(b"\n", idx)
        if newline >= 0:
            return bytes(data[: newline + 1])
        return None
    start = i
    while i < n and data[i] == ord("#"):
        i += 1
    if i == n and (i - start) < 8:
        return None
    return bytes(data[:i])


def _decode(data: bytes) -> str:
    return data.decode("ascii", errors="ignore")
