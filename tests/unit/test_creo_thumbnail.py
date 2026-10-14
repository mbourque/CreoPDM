"""Unit tests for Creo embedded JPEG thumbnail extraction (vault bytes only)."""

from __future__ import annotations

from pathlib import Path

import pytest

from creopdm.utils.creo_thumbnail import (
    MARKER,
    diagnose_thumbnail,
    extract_thumbnail,
    is_thumbnail_candidate,
    jpeg_dimensions,
)


def _minimal_jpeg(width: int = 16, height: int = 16, min_size: int = 1024) -> bytes:
    """Valid JFIF with SOF0, padded with a COM segment to meet min_size."""
    app0 = b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = bytes(
        [
            0xFF,
            0xC0,
            0x00,
            0x0B,
            0x08,
            (height >> 8) & 0xFF,
            height & 0xFF,
            (width >> 8) & 0xFF,
            width & 0xFF,
            0x03,
            0x01,
            0x11,
            0x00,
        ]
    )
    eoi = b"\xff\xd9"
    core = b"\xff\xd8" + app0 + sof + eoi
    if len(core) >= min_size:
        return core
    # Insert COM between APP0 and SOF so dimensions still parse.
    need = min_size - (len(b"\xff\xd8") + len(app0) + len(sof) + len(eoi))
    # COM: FF FE + 2-byte length (includes length bytes) + payload
    payload = max(need - 4, 0)
    seg_len = payload + 2
    com = bytes([0xFF, 0xFE, (seg_len >> 8) & 0xFF, seg_len & 0xFF]) + (b"X" * payload)
    return b"\xff\xd8" + app0 + com + sof + eoi


def test_jpeg_dimensions_reads_sof():
    data = _minimal_jpeg(256, 128, min_size=1024)
    assert jpeg_dimensions(data) == (256, 128)


def test_extract_thumbnail_marker_plus_jpeg(tmp_path: Path):
    jpeg = _minimal_jpeg()
    blob = b"HEADER" + MARKER + b"\x00\x01\x02" + jpeg + b"TRAILER"
    path = tmp_path / "wedge.prt"
    path.write_bytes(blob)
    out = extract_thumbnail(path)
    assert out == jpeg
    assert out.startswith(b"\xff\xd8\xff\xe0")
    assert out.endswith(b"\xff\xd9")


def test_extract_thumbnail_jpeg_far_after_marker(tmp_path: Path):
    """Regression: 600630031046.prt had SOI ~2933 bytes after THMB_IMG_MAIN."""
    jpeg = _minimal_jpeg()
    pad = b"\x00" * 2933
    path = tmp_path / "far.prt"
    path.write_bytes(b"H" + MARKER + pad + jpeg + b"T")
    out = extract_thumbnail(path)
    assert out == jpeg
    report = diagnose_thumbnail(path)
    assert report["reason"] == "ok"
    assert report["nearest_jpeg_gap"] == 2933


def test_extract_thumbnail_marker_but_no_jpeg(tmp_path: Path):
    path = tmp_path / "empty.prt"
    path.write_bytes(b"xx" + MARKER + b"not a jpeg here" + b"yy" * 600)
    assert extract_thumbnail(path) is None


def test_extract_thumbnail_no_marker(tmp_path: Path):
    path = tmp_path / "plain.prt"
    path.write_bytes(b"no thumbnail marker " + _minimal_jpeg())
    assert extract_thumbnail(path) is None


def test_extract_thumbnail_truncated_jpeg_no_eoi(tmp_path: Path):
    jpeg = _minimal_jpeg()
    truncated = jpeg[:-2]  # drop FF D9
    path = tmp_path / "trunc.prt"
    path.write_bytes(MARKER + b"\x00" + truncated)
    assert extract_thumbnail(path) is None


def test_extract_thumbnail_marker_twice_jpeg_after_first(tmp_path: Path):
    """Directory near EOF may repeat the marker; first marker+JPEG wins."""
    jpeg = _minimal_jpeg()
    # First marker has the real JPEG; second marker (directory) has no JPEG.
    blob = (
        b"A" * 100
        + MARKER
        + b"\x00\x00"
        + jpeg
        + b"B" * 50
        + MARKER
        + b"dir-entry-only"
        + b"C" * 50
    )
    path = tmp_path / "dup.prt"
    path.write_bytes(blob)
    assert extract_thumbnail(path) == jpeg


def test_is_thumbnail_candidate_creo_tips_only():
    assert is_thumbnail_candidate("wedge.prt")
    assert is_thumbnail_candidate("wedge.prt.16")
    assert is_thumbnail_candidate("top.asm")
    assert is_thumbnail_candidate("plate.drw.1")
    assert not is_thumbnail_candidate("notes.txt")
    assert not is_thumbnail_candidate("read.me")


def test_extract_thumbnail_missing_file_returns_none(tmp_path: Path):
    assert extract_thumbnail(tmp_path / "missing.prt") is None


def test_diagnose_thumbnail_not_in_model_vs_ok(tmp_path: Path):
    bare = tmp_path / "bare.prt"
    bare.write_bytes(b"no marker " * 200)
    assert diagnose_thumbnail(bare)["reason"] == "not_in_model"

    jpeg = _minimal_jpeg()
    good = tmp_path / "good.prt"
    good.write_bytes(b"H" + MARKER + b"\x00\x00" + jpeg)
    report = diagnose_thumbnail(good)
    assert report["reason"] == "ok"
    assert report["extract_bytes"] == len(jpeg)
    assert report["marker_count"] == 1


@pytest.mark.skipif(
    not Path(r"C:\Users\micha\AppData\Local\Temp").exists(),
    reason="optional sample path probe",
)
def test_extract_thumbnail_wedge_sample_if_present():
    """Optional: wedge.prt.16 yields ~13906-byte JPEG when available on disk."""
    candidates = [
        Path(__file__).resolve().parents[1] / "fixtures" / "wedge.prt.16",
        Path.home() / "AppData" / "Local" / "Temp" / "wedge.prt.16",
    ]
    sample = next((p for p in candidates if p.is_file()), None)
    if sample is None:
        pytest.skip("wedge.prt.16 sample not available")
    out = extract_thumbnail(sample)
    assert out is not None
    assert len(out) == 13906
    assert out.startswith(b"\xff\xd8")
    assert out.endswith(b"\xff\xd9")
