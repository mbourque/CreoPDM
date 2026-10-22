"""Compress text responses (pages, JSON, scripts) — never files the vault sends back."""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.middleware.gzip import GZipMiddleware, GZipResponder
from starlette.types import Message, Receive, Scope, Send

# A big product's page is ~7 MB of row markup and its file list ~5 MB of JSON: both shrink about
# tenfold. CAD files, zips and images are already compact (or are streamed): sent as they are.
COMPRESSIBLE_TYPES = frozenset(
    {
        "application/json",
        "application/javascript",
        "application/xml",
        "image/svg+xml",
    }
)


def is_compressible(content_type: str) -> bool:
    media = (content_type or "").partition(";")[0].strip().lower()
    return media.startswith("text/") or media in COMPRESSIBLE_TYPES


class _TextOnlyResponder(GZipResponder):
    async def send_with_compression(self, message: Message) -> None:
        await super().send_with_compression(message)
        if message["type"] == "http.response.start":
            media = Headers(raw=message["headers"]).get("content-type", "")
            if not is_compressible(media):
                self.content_type_is_excluded = True


class TextGZipMiddleware(GZipMiddleware):
    """GZip for clients that accept it, limited to text-like content types."""

    def __init__(self, app, minimum_size: int = 1024, compresslevel: int = 3) -> None:
        # Level 3: nearly the size of level 9 for markup, several times faster on a 7 MB page.
        super().__init__(app, minimum_size=minimum_size, compresslevel=compresslevel)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and "gzip" in Headers(scope=scope).get("Accept-Encoding", ""):
            responder = _TextOnlyResponder(
                self.app,
                self.minimum_size,
                compresslevel=self.compresslevel,
                thread_minimum_size=self.thread_minimum_size,
                exclude_content_types=self.exclude_content_types,
            )
            await responder(scope, receive, send)
            return
        await self.app(scope, receive, send)
