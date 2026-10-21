"""Map domain exceptions to the standard API error envelope."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from creopdm.exceptions import CreoPDMError
from creopdm.logging_setup import get_logger

logger = get_logger("api")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


_PAGE_TEXT = {
    401: ("Sign in required", "You need to sign in to see this page.", ""),
    403: (
        "You don't have access to this",
        "Your account is not allowed to open this page.",
        "If you followed a link, you may be signed in as a different person than the one it was meant for. "
        "Sign in as the right person, or ask an administrator for access.",
    ),
    404: (
        "Not found",
        "This page, file or product does not exist, or it has been removed.",
        "If you followed a link, it may be out of date.",
    ),
}


def _wants_page(request: Request, status: int) -> bool:
    """A person opening a link in the browser gets a readable page; scripts and fetches keep the JSON."""
    if request.method not in ("GET", "HEAD") or status not in _PAGE_TEXT:
        return False
    if request.url.path.startswith(("/api/", "/embed/", "/client/", "/static/")):
        return False
    return "text/html" in request.headers.get("accept", "") and request.headers.get("sec-fetch-dest", "document") in (
        "document",
        "iframe",
    )


def _error_page(request: Request, status: int) -> HTMLResponse | None:
    try:
        from creopdm.api.pages import render

        title, lead, hint = _PAGE_TEXT[status]
        response = render(
            request,
            "error_page.html",
            {"error_title": title, "error_lead": lead, "error_hint": hint, "error_status": status},
        )
        response.status_code = status
        return response
    except Exception:  # never let the friendly page hide the real status
        logger.exception("Could not render the error page")
        return None


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(CreoPDMError)
    async def domain_error(request: Request, exc: CreoPDMError) -> JSONResponse:
        if exc.http_status >= 500:
            logger.exception("Application error %s: %s", exc.code, exc.message)
        else:
            # Which request and which account: without them a burst of refusals (a page polling
            # without permission) cannot be traced. The path only, never the query string.
            user = getattr(getattr(request.state, "auth_user", None), "username", None)
            logger.info(
                "Client error %s: %s [%s %s%s]",
                exc.code,
                exc.message,
                request.method,
                request.url.path,
                f" user={user}" if user else "",
            )
        if _wants_page(request, exc.http_status):
            page = _error_page(request, exc.http_status)
            if page is not None:
                return page
        return JSONResponse(status_code=exc.http_status, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "The request was invalid.",
                    "details": {"errors": _json_safe(exc.errors())},
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if _wants_page(request, exc.status_code):
            page = _error_page(request, exc.status_code)
            if page is not None:
                return page
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "HTTP_ERROR",
                    "message": str(exc.detail),
                    "details": {},
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred.",
                    "details": {},
                }
            },
        )
