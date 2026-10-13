"""Thumbnail store + where-used isolation / idempotency."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from creopdm.models.thumbnail import Thumbnail
from creopdm.utils.creo_thumbnail import MARKER
from tests.unit.test_creo_thumbnail import _minimal_jpeg


def _write_model_with_thumb(path: Path) -> bytes:
    jpeg = _minimal_jpeg()
    path.write_bytes(b"UGC" + MARKER + b"\x00" + jpeg)
    return jpeg


def test_ensure_from_path_idempotent(tmp_path, data_dir):
    from creopdm.app import build_context
    from creopdm.config import ConfigManager
    from creopdm.utils.identity import StaticUserProvider

    ctx = build_context(ConfigManager(), users=StaticUserProvider("Alice", "PC"))
    assert ctx.thumbnails is not None
    session = ctx.session_factory()
    try:
        model = tmp_path / "wedge.prt"
        jpeg = _write_model_with_thumb(model)
        digest = "a" * 64
        svc = ctx.thumbnails
        assert svc.ensure_from_path(session, content_hash=digest, path=model) == "found"
        session.commit()
        assert svc.ensure_from_path(session, content_hash=digest, path=model) == "skipped"
        session.commit()
        rows = session.scalars(select(Thumbnail)).all()
        assert len(rows) == 1
        assert rows[0].content_hash == digest
        assert bytes(rows[0].bytes) == jpeg
        assert rows[0].width == 16
        assert rows[0].height == 16
    finally:
        session.close()
        ctx.engine.dispose()


def test_ensure_from_path_missing_returns_missing_not_error(tmp_path, data_dir):
    from creopdm.app import build_context
    from creopdm.config import ConfigManager
    from creopdm.utils.identity import StaticUserProvider

    ctx = build_context(ConfigManager(), users=StaticUserProvider("Alice", "PC"))
    session = ctx.session_factory()
    try:
        path = tmp_path / "bare.prt"
        path.write_bytes(b"no marker " * 200)
        assert (
            ctx.thumbnails.ensure_from_path(session, content_hash="b" * 64, path=path)
            == "missing"
        )
        assert session.scalars(select(Thumbnail)).all() == []
    finally:
        session.close()
        ctx.engine.dispose()


def test_where_used_job_survives_thumbnail_extract_failure(data_dir, monkeypatch):
    """Thumbnail exceptions must not flip Where Used job to error."""
    from creopdm.app import build_context
    from creopdm.config import ConfigManager
    from creopdm.utils.identity import StaticUserProvider

    ctx = build_context(ConfigManager(), users=StaticUserProvider("Alice", "PC"))

    def boom(*_a, **_k):
        raise RuntimeError("thumbnail boom")

    monkeypatch.setattr(ctx.thumbnails, "extract_for_product_chunk", boom)
    ctx.where_used_index._extract_thumbnails_quiet("no-such-product", None)
    status = ctx.where_used_index.get("no-such-product")
    assert status.state == "idle"
    ctx.engine.dispose()
