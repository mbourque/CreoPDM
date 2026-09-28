"""Helpers to notify project watchers after mutating API actions."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from creopdm.context import AppContext
from creopdm.models.project import Project
from creopdm.models.user import User


def actor_label(user: User | None, fallback: str = "Someone") -> str:
    if user is None:
        return fallback
    name = (user.display_name or "").strip() or user.username
    return f"{name} ({user.username})"


def notify_project_watchers(
    request: Request,
    ctx: AppContext,
    db: Session,
    project: Project,
    *,
    action: str,
    filenames: list[str],
    object_uuid: str | None = None,
) -> None:
    """Fan out one summary email to watchers (excludes the actor). Failures stay logged."""
    auth_user = getattr(request.state, "auth_user", None)
    if not isinstance(auth_user, User):
        auth_user = None
    identity = ctx.users.get_current_user()
    label = actor_label(auth_user, fallback=identity.user_name or "Someone")
    ctx.project_watches.notify_project_activity(
        db,
        project=project,
        action=action,
        actor=auth_user,
        actor_label=label,
        filenames=filenames,
        base_url=str(request.base_url),
        object_uuid=object_uuid,
        email_enabled=bool(ctx.settings.email.enabled),
    )
