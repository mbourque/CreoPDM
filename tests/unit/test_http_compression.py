"""Text responses are compressed for clients that accept it; files the vault sends are not."""

from __future__ import annotations

import gzip

from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from creopdm.http_compression import TextGZipMiddleware, is_compressible

BIG = ("row " * 2000).encode()


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/page")
    def page():
        return Response(BIG, media_type="text/html; charset=utf-8")

    @app.get("/list")
    def listing():
        return Response(b'["' + BIG + b'"]', media_type="application/json")

    @app.get("/script.js")
    def script():
        return Response(BIG, media_type="application/javascript")

    @app.get("/file")
    def file():
        return Response(BIG, media_type="application/octet-stream")

    @app.get("/zip")
    def zipped():
        return Response(BIG, media_type="application/zip")

    @app.get("/uploaded-pdf")
    def pdf():
        return Response(BIG, media_type="application/pdf")

    @app.get("/small")
    def small():
        return Response(b"tiny", media_type="text/html")

    @app.get("/events")
    def events():
        return StreamingResponse(iter([b"data: x\n\n" * 400]), media_type="text/event-stream")

    app.add_middleware(TextGZipMiddleware)
    return TestClient(app)


def _raw(client: TestClient, path: str, accept: str = "gzip"):
    with client.stream("GET", path, headers={"Accept-Encoding": accept}) as response:
        body = b"".join(response.iter_raw())
        return response.headers, body


def test_pages_json_and_scripts_are_compressed():
    client = _client()
    for path in ("/page", "/list", "/script.js"):
        headers, body = _raw(client, path)
        assert headers["content-encoding"] == "gzip", path
        assert len(body) < len(BIG) // 5
        assert gzip.decompress(body).startswith((b"row ", b'["row '))
        assert headers["content-length"] == str(len(body))
        assert "accept-encoding" in headers["vary"].lower()


def test_files_zips_and_other_binary_types_are_sent_as_they_are():
    client = _client()
    for path in ("/file", "/zip", "/uploaded-pdf"):
        headers, body = _raw(client, path)
        assert "content-encoding" not in headers, path
        assert body == BIG


def test_event_streams_small_replies_and_clients_without_gzip_are_untouched():
    client = _client()
    headers, body = _raw(client, "/events")
    assert "content-encoding" not in headers
    headers, body = _raw(client, "/small")
    assert "content-encoding" not in headers and body == b"tiny"
    headers, body = _raw(client, "/page", accept="identity")
    assert "content-encoding" not in headers and body == BIG


def test_which_types_count_as_text():
    assert is_compressible("text/html; charset=utf-8") and is_compressible("application/json")
    assert is_compressible("image/svg+xml") and is_compressible("text/csv")
    assert not is_compressible("application/octet-stream") and not is_compressible("image/png")
    assert not is_compressible("") and not is_compressible("application/zip")


def test_the_app_registers_the_middleware_outermost():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "src" / "creopdm" / "app.py").read_text(encoding="utf-8")
    assert source.index("SessionMiddleware,") < source.index("app.add_middleware(TextGZipMiddleware)")
