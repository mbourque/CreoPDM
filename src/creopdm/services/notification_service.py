"""Notification facade — email first; other channels can plug in later."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

from creopdm.config import EmailConfig
from creopdm.logging_setup import get_logger
from creopdm.services.email_service import EmailService

logger = get_logger("notifications")


class NotificationEvent(StrEnum):
    """Catalog of notification kinds (producers wire these later)."""

    CHECKIN_FAILURE = "checkin_failure"
    CHECKOUT_FAILURE = "checkout_failure"
    BACKGROUND_FAILURE = "background_failure"
    METADATA_FAILURE = "metadata_failure"
    SERVER_ERROR = "server_error"
    LOW_DISK_SPACE = "low_disk_space"
    LONG_JOB_COMPLETED = "long_job_completed"
    BACKUP_MAINTENANCE = "backup_maintenance"
    USER_WORKFLOW = "user_workflow"
    PRODUCT_ACTIVITY = "product_activity"
    SYSTEM_EVENT = "system_event"


# Events that default to the administrator email when `to` is omitted.
_ADMIN_ATTENTION_EVENTS: frozenset[NotificationEvent] = frozenset(
    {
        NotificationEvent.CHECKIN_FAILURE,
        NotificationEvent.CHECKOUT_FAILURE,
        NotificationEvent.BACKGROUND_FAILURE,
        NotificationEvent.METADATA_FAILURE,
        NotificationEvent.SERVER_ERROR,
        NotificationEvent.LOW_DISK_SPACE,
        NotificationEvent.BACKUP_MAINTENANCE,
        NotificationEvent.SYSTEM_EVENT,
    }
)


class NotificationProvider(Protocol):
    def send(
        self,
        *,
        event: NotificationEvent,
        subject: str,
        message: str,
        to: list[str],
    ) -> None: ...


class EmailNotificationProvider:
    """First notification channel — delegates to EmailService."""

    def __init__(self, email: EmailService) -> None:
        self._email = email

    def send(
        self,
        *,
        event: NotificationEvent,
        subject: str,
        message: str,
        to: list[str],
    ) -> None:
        self._email.send(to, subject, message)


class NotificationService:
    """Route notify() to registered providers. Failures are logged, never raised."""

    def __init__(
        self,
        *,
        get_config: Callable[[], EmailConfig],
        email: EmailService,
        providers: list[NotificationProvider] | None = None,
    ) -> None:
        self._get_config = get_config
        self._email = email
        self._providers: list[NotificationProvider] = list(
            providers if providers is not None else [EmailNotificationProvider(email)]
        )

    def configure(self, get_config: Callable[[], EmailConfig]) -> None:
        self._get_config = get_config

    def _config(self) -> EmailConfig:
        return self._get_config()

    def notify(
        self,
        event: NotificationEvent | str,
        *,
        subject: str,
        message: str,
        to: str | list[str] | None = None,
    ) -> None:
        try:
            kind = event if isinstance(event, NotificationEvent) else NotificationEvent(str(event))
        except ValueError:
            logger.warning("Unknown notification event %r; treating as system_event", event)
            kind = NotificationEvent.SYSTEM_EVENT

        cfg = self._config()
        if not cfg.enabled:
            logger.debug("Notifications disabled; skip %s", kind.value)
            return

        recipients = _resolve_recipients(kind, to=to, administrator_email=cfg.administrator_email)
        if not recipients:
            logger.warning(
                "No recipients for notification %s; set administrator email or pass to=",
                kind.value,
            )
            return

        for provider in self._providers:
            try:
                provider.send(
                    event=kind,
                    subject=subject,
                    message=message,
                    to=recipients,
                )
            except Exception as exc:  # noqa: BLE001 — never fail originating operation
                logger.error(
                    "Notification provider %s failed for %s: %s",
                    type(provider).__name__,
                    kind.value,
                    exc,
                )


def _resolve_recipients(
    event: NotificationEvent,
    *,
    to: str | list[str] | None,
    administrator_email: str,
) -> list[str]:
    if to is not None:
        if isinstance(to, str):
            raw = [to]
        else:
            raw = list(to)
        out = [a.strip() for a in raw if (a or "").strip()]
        if out:
            return out
    if event in _ADMIN_ATTENTION_EVENTS or event in (
        NotificationEvent.LONG_JOB_COMPLETED,
        NotificationEvent.USER_WORKFLOW,
    ):
        admin = (administrator_email or "").strip()
        return [admin] if admin else []
    return []
