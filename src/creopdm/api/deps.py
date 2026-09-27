"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from creopdm.context import AppContext
from creopdm.exceptions import PermissionDeniedError
from creopdm.models.project import Project


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


def require_project_access(request: Request, ctx: AppContext, project: Project) -> None:
    """Deny when the signed-in user is restricted away from this project."""
    if not ctx.auth_enabled:
        return
    user = getattr(request.state, "auth_user", None)
    if user is None:
        return
    if ctx.user_accounts.user_can_access_project(user, project):
        return
    raise PermissionDeniedError("You do not have access to this project.")


def accessible_projects(request: Request, ctx: AppContext, db: Session) -> list[Project]:
    """Projects the current user may browse (all when auth off or All projects)."""
    projects = ctx.projects.list_projects(db)
    if not ctx.auth_enabled:
        return projects
    user = getattr(request.state, "auth_user", None)
    if user is None:
        return projects
    return ctx.user_accounts.filter_accessible_projects(user, projects)


def load_accessible_project(
    request: Request,
    ctx: AppContext,
    db: Session,
    project_id: str,
) -> Project:
    """Load a project and enforce membership when auth is on."""
    project = ctx.projects.get_project(db, project_id)
    require_project_access(request, ctx, project)
    return project
