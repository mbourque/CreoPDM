"""Unit tests for EmailService and NotificationService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from creopdm.config import EmailConfig
from creopdm.exceptions import ValidationAppError
from creopdm.services.email_service import EmailService
from creopdm.services.notification_service import (
    NotificationEvent,
    NotificationService,
)


def _cfg(**kwargs) -> EmailConfig:
    base = dict(
        enabled=True,
        smtp_host="localhost",
        smtp_port=25,
        from_address="creopdm@example.com",
        from_name="CreoPDM",
        administrator_email="admin@example.com",
        smtp_username="",
        smtp_password="",
        smtp_use_tls=False,
        smtp_use_auth=False,
    )
    base.update(kwargs)
    return EmailConfig.model_validate(base)


def test_email_service_local_send_uses_localhost_25():
    cfg = _cfg()
    service = EmailService(lambda: cfg)
    smtp = MagicMock()
    smtp.__enter__ = MagicMock(return_value=smtp)
    smtp.__exit__ = MagicMock(return_value=False)
    with patch("creopdm.services.email_service.smtplib.SMTP", return_value=smtp) as ctor:
        service.send("user@example.com", "Subject", "Body text")
    ctor.assert_called_once_with("localhost", 25, timeout=30)
    smtp.starttls.assert_not_called()
    smtp.login.assert_not_called()
    smtp.send_message.assert_called_once()
    msg = smtp.send_message.call_args.args[0]
    assert msg["To"] == "user@example.com"
    assert msg["Subject"] == "Subject"
    assert "CreoPDM" in msg["From"]


def test_email_service_auth_tls_path():
    cfg = _cfg(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_use_tls=True,
        smtp_use_auth=True,
        smtp_username="creopdm@example.com",
        smtp_password="secret",
    )
    service = EmailService(lambda: cfg)
    smtp = MagicMock()
    smtp.__enter__ = MagicMock(return_value=smtp)
    smtp.__exit__ = MagicMock(return_value=False)
    with patch("creopdm.services.email_service.smtplib.SMTP", return_value=smtp) as ctor:
        service.send(["a@example.com", "b@example.com"], "Hi", "Hello")
    ctor.assert_called_once_with("smtp.example.com", 587, timeout=30)
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("creopdm@example.com", "secret")
    smtp.send_message.assert_called_once()


def test_email_service_requires_from_and_recipient():
    service = EmailService(lambda: _cfg(from_address=""))
    with pytest.raises(ValidationAppError, match="From address"):
        service.send("user@example.com", "S", "B")
    service = EmailService(lambda: _cfg())
    with pytest.raises(ValidationAppError, match="recipient"):
        service.send("  ", "S", "B")


def test_notification_disabled_skips_send():
    email = MagicMock(spec=EmailService)
    cfg = _cfg(enabled=False)
    notify = NotificationService(get_config=lambda: cfg, email=email)
    notify.notify(NotificationEvent.SERVER_ERROR, subject="x", message="y")
    email.send.assert_not_called()


def test_notification_routes_to_admin_email():
    email = MagicMock(spec=EmailService)
    cfg = _cfg(enabled=True)
    notify = NotificationService(get_config=lambda: cfg, email=email)
    notify.notify(NotificationEvent.LOW_DISK_SPACE, subject="Disk", message="Low")
    email.send.assert_called_once_with(["admin@example.com"], "Disk", "Low")


def test_notification_send_failure_is_logged_not_raised(caplog):
    email = MagicMock(spec=EmailService)
    email.send.side_effect = ValidationAppError("SMTP down")
    cfg = _cfg(enabled=True)
    notify = NotificationService(get_config=lambda: cfg, email=email)
    with caplog.at_level("ERROR", logger="creopdm.notifications"):
        notify.notify(NotificationEvent.SERVER_ERROR, subject="Err", message="Boom")
    assert any("failed" in r.message.lower() for r in caplog.records)
