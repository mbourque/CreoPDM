"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from creopdm.context import AppContext
from creopdm.exceptions import PermissionDeniedError


def get_context(request: Request) -> AppContext:
    return request.app.state.ctx


def get_db(request: Request) -> Generator[Session, None, None]:
    ctx: AppContext = request.app.state.ctx
    session = ctx.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def require_permission(request: Request, ctx: AppContext, key: str) -> None:
    """Enforce a permission when session auth is enabled."""
    if not ctx.auth_enabled:
        return
    perms = getattr(request.state, "permissions", None) or frozenset()
    if key in perms:
        return
    raise PermissionDeniedError("You do not have permission to perform this action.")
