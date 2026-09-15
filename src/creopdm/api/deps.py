"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from creopdm.context import AppContext


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
