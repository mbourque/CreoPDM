"""Project watch / email subscribe for activity notifications."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from creopdm.exceptions import ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.models.project import Project
from creopdm.models.user import ProjectWatch, User
from creopdm.services.notification_service import NotificationEvent, NotificationService
from creopdm.services.user_service import validate_email

logger = get_logger("project_watch")

_MAX_FILES_IN_EMAIL = 40


class ProjectWatchService:
    def __init__(self, notifications: NotificationService) -> None:
        self._notifications = notifications

    def email_notifications_enabled(self, *, email_enabled: bool) -> bool:
        return bool(email_enabled)

    def watch_eligibility(
        self,
        user: User | None,
        *,
        email_enabled: bool,
    ) -> tuple[bool, str | None]:
        """Return (can_watch, reason). Notifications off is handled by hiding the UI."""
        if not email_enabled:
            return False, "Email notifications are disabled."
        if user is None:
            return False, "Sign in to watch a project."
        try:
            validate_email(user.email or "")
        except ValidationAppError:
            return (
                False,
                "Set a valid email address on your account before watching a project.",
            )
        return True, None

    def is_watching(self, db: Session, user_id: int, project_id: int) -> bool:
        row = db.scalar(
            select(ProjectWatch).where(
                ProjectWatch.user_id == user_id,
                ProjectWatch.project_id == project_id,
            )
        )
        return row is not None

    def subscribe(self, db: Session, user: User, project: Project, *, email_enabled: bool) -> None:
        can, reason = self.watch_eligibility(user, email_enabled=email_enabled)
        if not can:
            raise ValidationAppError(reason or "Cannot watch this project.")
        if self.is_watching(db, user.id, project.id):
            return
        db.add(ProjectWatch(user_id=user.id, project_id=project.id))
        db.flush()

    def unsubscribe(self, db: Session, user: User, project: Project) -> None:
        db.execute(
            delete(ProjectWatch).where(
                ProjectWatch.user_id == user.id,
                ProjectWatch.project_id == project.id,
            )
        )
        db.flush()

    def list_watcher_emails(
        self,
        db: Session,
        project_id: int,
        *,
        exclude_user_id: int | None = None,
    ) -> list[str]:
        stmt = (
            select(User.email, User.id)
            .join(ProjectWatch, ProjectWatch.user_id == User.id)
            .where(ProjectWatch.project_id == project_id)
        )
        if exclude_user_id is not None:
            stmt = stmt.where(User.id != exclude_user_id)
        out: list[str] = []
        for email, _uid in db.execute(stmt).all():
            try:
                out.append(validate_email(email or ""))
            except ValidationAppError:
                continue
        # Stable unique order
        seen: set[str] = set()
        unique: list[str] = []
        for addr in out:
            key = addr.casefold()
            if key in seen:
                continue
            seen.add(key)
            unique.append(addr)
        return unique

    def notify_project_activity(
        self,
        db: Session,
        *,
        project: Project,
        action: str,
        actor: User | None,
        actor_label: str,
        filenames: list[str],
        base_url: str,
        object_uuid: str | None = None,
        email_enabled: bool,
    ) -> None:
        if not email_enabled:
            return
        exclude_id = actor.id if actor is not None else None
        recipients = self.list_watcher_emails(db, project.id, exclude_user_id=exclude_id)
        if not recipients:
            return

        files = [f for f in filenames if (f or "").strip()]
        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        base = (base_url or "").rstrip("/")
        if object_uuid and len(files) == 1:
            link = f"{base}/projects/{project.uuid}/objects/{object_uuid}"
        else:
            link = f"{base}/?project={project.uuid}"

        if not files:
            files_block = "(project settings)"
        elif len(files) == 1:
            files_block = files[0]
        else:
            shown = files[:_MAX_FILES_IN_EMAIL]
            extra = len(files) - len(shown)
            lines = "\n".join(f"  - {name}" for name in shown)
            if extra > 0:
                lines += f"\n  … and {extra} more"
            files_block = f"{len(files)} files:\n{lines}"

        subject = f"CreoPDM: {action} in {project.name}"
        message = (
            f"Project: {project.name}\n"
            f"Action: {action}\n"
            f"By: {actor_label}\n"
            f"When: {when}\n"
            f"Files: {files_block}\n"
            f"\nOpen: {link}\n"
        )
        self._notifications.notify(
            NotificationEvent.PROJECT_ACTIVITY,
            subject=subject,
            message=message,
            to=recipients,
        )
