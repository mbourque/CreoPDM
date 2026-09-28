"""Central SMTP sender — the only place CreoPDM opens smtplib."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from email.message import EmailMessage
from email.utils import formataddr
import smtplib

from creopdm.config import EmailConfig
from creopdm.exceptions import ValidationAppError
from creopdm.logging_setup import get_logger

logger = get_logger("email")


class EmailService:
    """Send mail using AppSettings.email (local Postfix or authenticated SMTP)."""

    def __init__(self, get_config: Callable[[], EmailConfig] | None = None) -> None:
        self._get_config = get_config

    def configure(self, get_config: Callable[[], EmailConfig]) -> None:
        self._get_config = get_config

    def _config(self) -> EmailConfig:
        if self._get_config is None:
            raise ValidationAppError("Email service is not configured.")
        return self._get_config()

    def send(self, to: str | Sequence[str], subject: str, message: str) -> None:
        """Send a plain-text email. Raises ValidationAppError on misconfig or SMTP failure."""
        cfg = self._config()
        recipients = _normalize_recipients(to)
        if not recipients:
            raise ValidationAppError("At least one recipient email address is required.")
        from_addr = (cfg.from_address or "").strip()
        if not from_addr:
            raise ValidationAppError("From address is required before sending email.")
        host, port, use_tls, use_auth = cfg.connection()

        msg = EmailMessage()
        if (cfg.from_name or "").strip():
            msg["From"] = formataddr((cfg.from_name.strip(), from_addr))
        else:
            msg["From"] = from_addr
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = (subject or "").strip() or "(no subject)"
        msg.set_content(message or "")

        try:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                if use_tls:
                    smtp.starttls()
                if use_auth:
                    username = (cfg.smtp_username or "").strip()
                    if not username:
                        raise ValidationAppError(
                            "SMTP authentication is enabled but username is empty."
                        )
                    smtp.login(username, cfg.smtp_password or "")
                smtp.send_message(msg)
        except ValidationAppError:
            raise
        except OSError as exc:
            logger.warning("SMTP send failed to %s: %s", recipients, exc)
            raise ValidationAppError(f"Could not send email: {exc}") from exc
        except smtplib.SMTPException as exc:
            logger.warning("SMTP send failed to %s: %s", recipients, exc)
            raise ValidationAppError(f"Could not send email: {exc}") from exc
        logger.info("Sent email to %s subject=%r", recipients, subject)


def _normalize_recipients(to: str | Sequence[str]) -> list[str]:
    if isinstance(to, str):
        raw = [to]
    else:
        raw = list(to)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        addr = (item or "").strip()
        if not addr or addr.lower() in seen:
            continue
        seen.add(addr.lower())
        out.append(addr)
    return out
