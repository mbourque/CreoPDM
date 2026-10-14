"""Extract Creo's embedded JPEG thumbnail from a vault model file (no Creo).

Searches for ``THMB_IMG_MAIN`` then a JFIF JPEG within a short window. Section
directory offsets are not trusted — only marker + JPEG signatures.
"""

from __future__ import annotations

import mmap
import struct
from pathlib import Path

from creopdm.creo.file_manager import CreoFileManager
from creopdm.logging_setup import get_logger

logger = get_logger("creo_thumbnail")

MARKER = b"THMB_IMG_MAIN"
# JFIF APP0 after SOI: FF D8 FF E0 — also accept FF D8 FF within the window.
JPEG_SOI = b"\xff\xd8\xff"
JPEG_JFIF = b"\xff\xd8\xff\xe0"
JPEG_EOI = b"\xff\xd9"
# Gap marker→SOI is often tiny (~0–64); AI Testing tip 600630031046.prt was 2933.
MARKER_WINDOW = 8192
MIN_JPEG_BYTES = 1024
MAX_JPEG_BYTES = 2 * 1024 * 1024
THUMBNAIL_EXTENSIONS = frozenset({".prt", ".asm", ".drw"})


def is_thumbnail_candidate(filename: str) -> bool:
    """True for Creo tips that may embed THMB_IMG_MAIN."""
    logical = CreoFileManager.normalize_creo_filename(filename or "")
    return Path(logical).suffix.lower() in THUMBNAIL_EXTENSIONS


def jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Read width/height from the first SOF marker; None if unreadable."""
    if not data or len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        i += 2
        if marker in (0xD8, 0xD9):  # SOI / EOI
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # TEM / RSTn
            continue
        if i + 2 > n:
            return None
        seg_len = struct.unpack(">H", data[i : i + 2])[0]
        if seg_len < 2 or i + seg_len > n:
            return None
        if marker in (
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        ):
            if seg_len < 7:
                return None
            height, width = struct.unpack(">HH", data[i + 3 : i + 7])
            if width > 0 and height > 0:
                return int(width), int(height)
            return None
        i += seg_len
    return None


def _slice(buf: bytes | mmap.mmap, start: int, end: int) -> bytes:
    return bytes(buf[start:end])


def _jpeg_at(buf: bytes | mmap.mmap, jpeg_start: int) -> bytes | None:
    """Validate JPEG starting at jpeg_start; only reads up to MAX_JPEG_BYTES."""
    end = min(len(buf), jpeg_start + MAX_JPEG_BYTES + 2)
    if end - jpeg_start < 4:
        return None
    head = _slice(buf, jpeg_start, min(jpeg_start + 4, end))
    if not head.startswith(JPEG_SOI):
        return None
    chunk = _slice(buf, jpeg_start, end)
    eoi = chunk.find(JPEG_EOI)
    if eoi < 0:
        return None
    jpeg = chunk[: eoi + len(JPEG_EOI)]
    if len(jpeg) < MIN_JPEG_BYTES or len(jpeg) > MAX_JPEG_BYTES:
        return None
    if jpeg[:2] != b"\xff\xd8" or jpeg[-2:] != JPEG_EOI:
        return None
    if jpeg_dimensions(jpeg) is None:
        return None
    return jpeg


def _extract_from_buffer(buf: bytes | mmap.mmap) -> bytes | None:
    """Scan for THMB_IMG_MAIN + nearby JPEG without copying the whole file."""
    try:
        offset = 0
        n = len(buf)
        while offset < n:
            at = buf.find(MARKER, offset)
            if at < 0:
                return None
            start_search = at + len(MARKER)
            window = _slice(buf, start_search, min(n, start_search + MARKER_WINDOW))
            rel = window.find(JPEG_JFIF)
            if rel < 0:
                rel = window.find(JPEG_SOI)
            if rel >= 0:
                jpeg = _jpeg_at(buf, start_search + rel)
                if jpeg is not None:
                    return jpeg
            offset = at + len(MARKER)
    except Exception:
        logger.debug("extract_thumbnail buffer scan failed", exc_info=True)
        return None
    return None


def extract_thumbnail(path: Path | str) -> bytes | None:
    """Return embedded JPEG bytes from a Creo model file, or None.

    Never raises to the caller — any I/O or parse doubt yields None.
    Uses mmap so multi‑MB tips are not fully loaded into Python memory.
    """
    try:
        file_path = Path(path)
        if not file_path.is_file():
            return None
        size = file_path.stat().st_size
        if size < MIN_JPEG_BYTES + len(MARKER):
            return None
        with file_path.open("rb") as handle:
            try:
                with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    return _extract_from_buffer(mm)
            except (ValueError, OSError):
                if size > MAX_JPEG_BYTES * 4:
                    return None
                handle.seek(0)
                return _extract_from_buffer(handle.read())
    except Exception:
        logger.debug("extract_thumbnail failed for %s", path, exc_info=True)
        return None


def diagnose_thumbnail(path: Path | str) -> dict[str, object]:
    """Explain why extract_thumbnail succeeded or returned None (for support).

    Distinguishes ``not_in_model`` (no THMB_IMG_MAIN / no nearby JPEG) from
    ``parse_rejected`` (marker+JPEG seen but size/SOF checks failed).
    """
    file_path = Path(path)
    out: dict[str, object] = {
        "path": str(file_path),
        "exists": file_path.is_file(),
        "size": 0,
        "marker_count": 0,
        "markers_with_jpeg_sig": 0,
        "nearest_jpeg_gap": None,
        "extract_bytes": None,
        "reason": "missing_file",
    }
    if not file_path.is_file():
        return out
    try:
        size = file_path.stat().st_size
        out["size"] = size
        if size < MIN_JPEG_BYTES + len(MARKER):
            out["reason"] = "file_too_small"
            return out
        with file_path.open("rb") as handle:
            with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                n = len(mm)
                offset = 0
                marker_count = 0
                with_sig = 0
                nearest_gap: int | None = None
                while offset < n:
                    at = mm.find(MARKER, offset)
                    if at < 0:
                        break
                    marker_count += 1
                    start_search = at + len(MARKER)
                    # Probe a bit past MARKER_WINDOW so jpeg_outside_window is visible.
                    probe = _slice(
                        mm, start_search, min(n, start_search + MARKER_WINDOW + 8192)
                    )
                    jfif = probe.find(JPEG_JFIF)
                    soi = probe.find(JPEG_SOI) if jfif < 0 else jfif
                    if soi >= 0:
                        with_sig += 1
                        if nearest_gap is None or soi < nearest_gap:
                            nearest_gap = soi
                    offset = at + len(MARKER)
                out["marker_count"] = marker_count
                out["markers_with_jpeg_sig"] = with_sig
                out["nearest_jpeg_gap"] = nearest_gap
                jpeg = _extract_from_buffer(mm)
                if jpeg is not None:
                    out["extract_bytes"] = len(jpeg)
                    out["reason"] = "ok"
                    dims = jpeg_dimensions(jpeg)
                    out["width"] = dims[0] if dims else None
                    out["height"] = dims[1] if dims else None
                    return out
                if marker_count == 0:
                    out["reason"] = "not_in_model"  # no THMB_IMG_MAIN
                elif with_sig == 0:
                    out["reason"] = "not_in_model"  # marker only (directory), no JPEG
                elif nearest_gap is not None and nearest_gap >= MARKER_WINDOW:
                    out["reason"] = "jpeg_outside_window"  # possible extractor bug
                else:
                    out["reason"] = "parse_rejected"  # SOI in window but checks failed
                return out
    except Exception as exc:
        out["reason"] = "io_error"
        out["error"] = str(exc)
        return out


__all__ = [
    "MARKER",
    "MARKER_WINDOW",
    "THUMBNAIL_EXTENSIONS",
    "diagnose_thumbnail",
    "extract_thumbnail",
    "is_thumbnail_candidate",
    "jpeg_dimensions",
]
