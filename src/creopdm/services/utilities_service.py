"""Server diagnostics and admin utilities for Administration → Utilities."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from creopdm.auth_constants import UserStatus
from creopdm.config import (
    database_url_for_display,
    path_for_settings_display,
    sqlite_url_for_settings_display,
)
from creopdm.constants import APP_NAME, APP_VERSION, CheckoutStatus
from creopdm.context import AppContext
from creopdm.exceptions import ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.models.checkout import Checkout
from creopdm.models.product import Product
from creopdm.models.user import User
from creopdm.schemas.common import UtilitiesDiskUsage, UtilitiesProbe, UtilitiesStatusResponse
from creopdm.site_availability import normalize_site_availability

logger = get_logger("utilities")

# Warn when free space on a volume drops below this (bytes).
_LOW_DISK_BYTES = 1_073_741_824  # 1 GiB


@dataclass(frozen=True, slots=True)
class BroadcastEmailResult:
    sent: int
    failed: int
    recipient_count: int
    errors: tuple[str, ...] = ()


def active_user_emails(db: Session) -> list[str]:
    """Unique email addresses for ACTIVE users (order preserved)."""
    rows = db.scalars(
        select(User.email)
        .where(User.status == UserStatus.ACTIVE.value)
        .order_by(User.username)
    ).all()
    out: list[str] = []
    seen: set[str] = set()
    for raw in rows:
        addr = (raw or "").strip()
        if not addr:
            continue
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(addr)
    return out


def send_email_to_all_users(
    ctx: AppContext,
    db: Session,
    *,
    subject: str,
    message: str,
) -> BroadcastEmailResult:
    """Email each active user individually (addresses stay private)."""
    subj = (subject or "").strip()
    body = (message or "").strip()
    if not subj:
        raise ValidationAppError("Subject is required.")
    if not body:
        raise ValidationAppError("Message is required.")
    recipients = active_user_emails(db)
    if not recipients:
        raise ValidationAppError("No active users with an email address.")

    sent = 0
    errors: list[str] = []
    for addr in recipients:
        try:
            ctx.email.send(addr, subj, body)
            sent += 1
        except Exception as exc:  # noqa: BLE001 — continue other recipients
            logger.warning("Broadcast email failed for %s: %s", addr, exc)
            msg = getattr(exc, "message", None) or str(exc) or "send failed"
            errors.append(f"{addr}: {msg}")

    failed = len(recipients) - sent
    if sent == 0:
        raise ValidationAppError(
            "Could not send email to any user. "
            + (errors[0] if errors else "Check Administration → Email delivery settings.")
        )
    return BroadcastEmailResult(
        sent=sent,
        failed=failed,
        recipient_count=len(recipients),
        errors=tuple(errors[:5]),
    )


def _format_storage_bytes(value: int) -> str:
    """Human size for disk totals (B / KB / MB / GB / TB)."""
    size = int(value)
    if size < 0:
        return "—"
    if size < 1024:
        return f"{size} B"
    units = ("KB", "MB", "GB", "TB")
    amount = float(size)
    for unit in units:
        amount /= 1024.0
        if amount < 1024.0 or unit == units[-1]:
            text = f"{amount:.0f}" if amount >= 10 else f"{amount:.1f}".rstrip("0").rstrip(".")
            return f"{text} {unit}"
    return f"{size} B"


def _disk_usage(label: str, path: Path) -> UtilitiesDiskUsage:
    display = path_for_settings_display(path)
    try:
        resolved = path.expanduser().resolve()
    except OSError as exc:
        return UtilitiesDiskUsage(label=label, path=display, exists=False, error=str(exc))
    exists = resolved.exists()
    try:
        probe = resolved if exists else (Path(resolved.anchor) if resolved.anchor else resolved.parent)
        usage = shutil.disk_usage(probe)
        free_pct = (100.0 * usage.free / usage.total) if usage.total else None
        return UtilitiesDiskUsage(
            label=label,
            path=display,
            exists=exists,
            total_bytes=int(usage.total),
            used_bytes=int(usage.used),
            free_bytes=int(usage.free),
            total_label=_format_storage_bytes(int(usage.total)),
            used_label=_format_storage_bytes(int(usage.used)),
            free_label=_format_storage_bytes(int(usage.free)),
            free_percent=round(free_pct, 1) if free_pct is not None else None,
        )
    except OSError as exc:
        return UtilitiesDiskUsage(label=label, path=display, exists=exists, error=str(exc))


def _git_probe(ctx: AppContext) -> tuple[UtilitiesProbe, str, str]:
    executable = (ctx.git.executable or "git").strip() or "git"
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        return UtilitiesProbe(status="error", detail="Git executable not found"), executable, ""
    except OSError as exc:
        return UtilitiesProbe(status="error", detail=str(exc)), executable, ""
    version = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        return (
            UtilitiesProbe(status="error", detail=version or f"exit {result.returncode}"),
            executable,
            version,
        )
    return UtilitiesProbe(status="ok", detail=version or "available"), executable, version


def _database_display(ctx: AppContext) -> str:
    configured = (ctx.settings.database.url or "").strip()
    if configured:
        return sqlite_url_for_settings_display(database_url_for_display(configured))
    return sqlite_url_for_settings_display(ctx.config.default_sqlite_url())


def collect_utilities_status(ctx: AppContext, db: Session) -> UtilitiesStatusResponse:
    """Gather a read-only snapshot of server health for admins."""
    overall = "ok"
    db_probe = UtilitiesProbe(status="ok", detail="Connected")
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — surface any DB failure to admins
        db_probe = UtilitiesProbe(status="error", detail=str(exc) or "Database probe failed")
        overall = "error"

    dialect = ""
    try:
        bind = db.get_bind()
        dialect = str(getattr(getattr(bind, "dialect", None), "name", "") or "")
    except Exception:  # noqa: BLE001
        dialect = ""
    if not dialect:
        try:
            dialect = str(ctx.engine.dialect.name)
        except Exception:  # noqa: BLE001
            dialect = "unknown"

    git_probe, git_exe, git_version = _git_probe(ctx)
    if git_probe.status != "ok" and overall == "ok":
        overall = "degraded"

    data_dir = ctx.config.data_dir
    vaults_dir = ctx.config.vaults_dir
    logs_dir = ctx.config.logs_dir
    disks = [
        _disk_usage("Data directory", data_dir),
        _disk_usage("Vaults", vaults_dir),
        _disk_usage("Logs", logs_dir),
    ]

    for row in disks:
        if row.error:
            if overall == "ok":
                overall = "degraded"
            continue
        if row.free_bytes is not None and row.free_bytes < _LOW_DISK_BYTES:
            if overall == "ok":
                overall = "degraded"

    product_count = int(db.scalar(select(func.count()).select_from(Product)) or 0)
    user_count = int(db.scalar(select(func.count()).select_from(User)) or 0)
    active_checkout_count = int(
        db.scalar(
            select(func.count())
            .select_from(Checkout)
            .where(Checkout.status == CheckoutStatus.ACTIVE.value)
        )
        or 0
    )

    site = normalize_site_availability(ctx.settings.ui.site_availability)
    now = datetime.now(timezone.utc).astimezone()

    return UtilitiesStatusResponse(
        status=overall,
        app_name=APP_NAME,
        app_version=APP_VERSION,
        server_time=now.strftime("%Y-%m-%d %H:%M:%S %Z").strip(),
        hostname=platform.node() or "—",
        platform=platform.platform(),
        python_version=sys.version.split()[0],
        auth_enabled=bool(ctx.auth_enabled),
        site_availability=site,
        database=db_probe,
        database_dialect=dialect or "unknown",
        database_url=_database_display(ctx),
        git=git_probe,
        git_executable=git_exe,
        git_version=git_version,
        disk=disks,
        product_count=product_count,
        user_count=user_count,
        active_checkout_count=active_checkout_count,
        data_dir=path_for_settings_display(data_dir),
        vaults_dir=path_for_settings_display(vaults_dir),
        logs_dir=path_for_settings_display(logs_dir),
        agent_base_url=(ctx.settings.ui.agent_base_url or "http://127.0.0.1:8766").rstrip("/"),
    )
