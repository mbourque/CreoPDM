"""Server diagnostics and admin utilities for Administration → Utilities."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session, joinedload

from creopdm.auth_constants import UserStatus
from creopdm.config import (
    database_url_for_display,
    path_for_settings_display,
    sqlite_url_for_settings_display,
)
from creopdm.constants import APP_NAME, APP_VERSION, ActivityAction, CheckoutStatus, DEFAULT_BRANCH
from creopdm.context import AppContext
from creopdm.exceptions import ProductNotFoundError, RepositoryError, ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.models.checkout import Checkout
from creopdm.models.object import EngineeringObject
from creopdm.models.parameter import Parameter
from creopdm.models.product import Product
from creopdm.models.user import User
from creopdm.models.version import ObjectVersion
from creopdm.schemas.common import (
    UtilitiesCpuUsage,
    UtilitiesDiskUsage,
    UtilitiesProbe,
    UtilitiesStatusResponse,
)
from creopdm.site_availability import normalize_site_availability

logger = get_logger("utilities")

# Warn when free space on a volume drops below this (bytes).
_LOW_DISK_BYTES = 1_073_741_824  # 1 GiB
# CPU section badge only (does not change overall health status).
_CPU_BUSY_PERCENT = 70.0
_CPU_HOT_PERCENT = 90.0
_CPU_SAMPLE_SECONDS = 0.2


@dataclass(frozen=True, slots=True)
class BroadcastEmailResult:
    sent: int
    failed: int
    recipient_count: int
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CompactVaultResult:
    product_uuid: str
    product_name: str
    new_head: str
    versions_removed: int
    git_bytes_before: int
    git_bytes_after: int

    @property
    def size_summary(self) -> str:
        before = _format_storage_bytes(self.git_bytes_before)
        after = _format_storage_bytes(self.git_bytes_after)
        if self.git_bytes_after < self.git_bytes_before:
            saved = _format_storage_bytes(self.git_bytes_before - self.git_bytes_after)
            return f".git {before} → {after} (freed {saved})"
        return f".git {before} → {after}"


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


def _read_cpu_times() -> tuple[float, float] | None:
    """Return ``(idle, total)`` CPU time counters, or None if unavailable."""
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/stat", encoding="utf-8") as handle:
                line = handle.readline()
        except OSError:
            return None
        if not line.startswith("cpu "):
            return None
        parts = line.split()
        try:
            values = [float(part) for part in parts[1:8]]
        except (TypeError, ValueError):
            return None
        if len(values) < 4:
            return None
        idle = values[3] + (values[4] if len(values) > 4 else 0.0)  # idle + iowait
        total = sum(values)
        return idle, total
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class FileTime(ctypes.Structure):
                _fields_ = [
                    ("dwLowDateTime", wintypes.DWORD),
                    ("dwHighDateTime", wintypes.DWORD),
                ]

            idle = FileTime()
            kernel = FileTime()
            user = FileTime()
            if not ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None

            def _filetime_to_int(value: FileTime) -> int:
                return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)

            idle_i = _filetime_to_int(idle)
            # Kernel time includes idle on Windows.
            kernel_i = _filetime_to_int(kernel)
            user_i = _filetime_to_int(user)
            total = kernel_i + user_i
            return float(idle_i), float(total)
        except Exception:  # noqa: BLE001 — best-effort host probe
            return None
    return None


def _sample_cpu_percent(sample_seconds: float = _CPU_SAMPLE_SECONDS) -> float | None:
    """Instantaneous host CPU busy percent over a short sample window."""
    first = _read_cpu_times()
    if first is None:
        return None
    time.sleep(max(0.05, float(sample_seconds)))
    second = _read_cpu_times()
    if second is None:
        return None
    idle_delta = second[0] - first[0]
    total_delta = second[1] - first[1]
    if total_delta <= 0:
        return None
    busy = 100.0 * (1.0 - (idle_delta / total_delta))
    return max(0.0, min(100.0, busy))


def _cpu_status_for_percent(percent: float | None) -> str:
    if percent is None:
        return "ok"
    if percent >= _CPU_HOT_PERCENT:
        return "hot"
    if percent >= _CPU_BUSY_PERCENT:
        return "busy"
    return "ok"


def collect_cpu_usage() -> UtilitiesCpuUsage:
    """Read host CPU load for Utilities → Health (does not affect overall status)."""
    logical = os.cpu_count()
    percent: float | None = None
    error: str | None = None
    try:
        percent = _sample_cpu_percent()
    except Exception as exc:  # noqa: BLE001
        error = str(exc) or "CPU sample failed"
        percent = None

    load_1 = load_5 = load_15 = None
    load_label = "—"
    try:
        load_1, load_5, load_15 = os.getloadavg()
        load_label = f"{load_1:.2f} / {load_5:.2f} / {load_15:.2f} (1 / 5 / 15 min)"
    except (AttributeError, OSError):
        load_label = "—"

    if percent is None and error is None and load_1 is None:
        error = "CPU load is not available on this host."

    percent_label = "—" if percent is None else f"{percent:.0f}%"
    return UtilitiesCpuUsage(
        percent=None if percent is None else round(percent, 1),
        percent_label=percent_label,
        status=_cpu_status_for_percent(percent),
        logical_cpus=logical,
        load_1=None if load_1 is None else round(float(load_1), 2),
        load_5=None if load_5 is None else round(float(load_5), 2),
        load_15=None if load_15 is None else round(float(load_15), 2),
        load_label=load_label,
        error=error,
    )


def _directory_size_bytes(path: Path) -> int:
    """Best-effort recursive size of files under path (no symlink follow)."""
    try:
        if not path.exists():
            return 0
        if path.is_file():
            return int(path.stat().st_size)
    except OSError:
        return 0
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += int((Path(root) / name).stat().st_size)
            except OSError:
                continue
    return total


def _volume_usage(label: str, path: Path) -> UtilitiesDiskUsage:
    """Free / used for the volume that holds path (shown once as System)."""
    display = path_for_settings_display(path)
    try:
        resolved = path.expanduser().resolve()
    except OSError as exc:
        return UtilitiesDiskUsage(
            label=label, path=display, kind="volume", exists=False, error=str(exc)
        )
    exists = resolved.exists()
    try:
        probe = resolved if exists else (Path(resolved.anchor) if resolved.anchor else resolved.parent)
        usage = shutil.disk_usage(probe)
        free_pct = (100.0 * usage.free / usage.total) if usage.total else None
        return UtilitiesDiskUsage(
            label=label,
            path=display,
            kind="volume",
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
        return UtilitiesDiskUsage(
            label=label, path=display, kind="volume", exists=exists, error=str(exc)
        )


def _directory_usage(label: str, path: Path) -> UtilitiesDiskUsage:
    """Size of this folder tree only (not the whole volume)."""
    display = path_for_settings_display(path)
    try:
        resolved = path.expanduser().resolve()
    except OSError as exc:
        return UtilitiesDiskUsage(
            label=label, path=display, kind="directory", exists=False, error=str(exc)
        )
    exists = resolved.exists()
    if not exists:
        return UtilitiesDiskUsage(
            label=label,
            path=display,
            kind="directory",
            exists=False,
            used_bytes=0,
            used_label=_format_storage_bytes(0),
        )
    try:
        size = _directory_size_bytes(resolved)
        return UtilitiesDiskUsage(
            label=label,
            path=display,
            kind="directory",
            exists=True,
            used_bytes=size,
            used_label=_format_storage_bytes(size),
        )
    except OSError as exc:
        return UtilitiesDiskUsage(
            label=label, path=display, kind="directory", exists=exists, error=str(exc)
        )


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


def list_products_for_compact(db: Session) -> list[Product]:
    """All products (including archived) for the compact-vault dropdown."""
    return list(db.scalars(select(Product).order_by(Product.name.asc())).all())


def compact_product_vault_history(
    ctx: AppContext,
    db: Session,
    *,
    product_uuid: str,
    confirm_name: str,
) -> CompactVaultResult:
    """Squash one product vault to a single tip commit and prune old ObjectVersions.

    Requires the typed product name to match exactly. Rejects dirty vaults and
    products with active checkouts.
    """
    uuid = (product_uuid or "").strip()
    typed = (confirm_name or "").strip()
    if not uuid:
        raise ValidationAppError("Choose a product.")
    if not typed:
        raise ValidationAppError("Type the product name exactly to confirm.")

    product = db.scalar(select(Product).where(Product.uuid == uuid))
    if product is None:
        raise ProductNotFoundError("Product not found.", details={"uuid": uuid})
    if typed != product.name:
        raise ValidationAppError(
            "Type the product name exactly to confirm.",
            details={"product": product.name},
        )

    active_checkouts = int(
        db.scalar(
            select(func.count())
            .select_from(Checkout)
            .join(EngineeringObject, EngineeringObject.id == Checkout.object_id)
            .where(
                EngineeringObject.product_id == product.id,
                Checkout.status == CheckoutStatus.ACTIVE.value,
            )
        )
        or 0
    )
    if active_checkouts:
        raise ValidationAppError(
            f"Release all checkouts first ({active_checkouts} active).",
            details={"active_checkouts": active_checkouts},
        )

    vault = ctx.workspaces.vault_for(product)
    git_dir = vault / ".git"
    if not git_dir.is_dir():
        raise ValidationAppError(
            "This product has no Git vault to compact.",
            details={"vault": str(vault)},
        )

    user = ctx.users.get_current_user()
    branch = (product.default_branch or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH
    before = _directory_size_bytes(git_dir)

    with ctx.locks.acquire(product.uuid):
        # Re-check checkouts inside the lock.
        active_checkouts = int(
            db.scalar(
                select(func.count())
                .select_from(Checkout)
                .join(EngineeringObject, EngineeringObject.id == Checkout.object_id)
                .where(
                    EngineeringObject.product_id == product.id,
                    Checkout.status == CheckoutStatus.ACTIVE.value,
                )
            )
            or 0
        )
        if active_checkouts:
            raise ValidationAppError(
                f"Release all checkouts first ({active_checkouts} active).",
                details={"active_checkouts": active_checkouts},
            )
        try:
            new_head = ctx.git.compact_to_tip(
                vault,
                author=user,
                message=f"Compact vault history ({product.name})",
                branch=branch,
            )
        except RepositoryError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Vault compact failed for %s", product.uuid)
            raise RepositoryError(
                f"Could not compact vault history: {exc}",
                details={"product": product.name},
            ) from exc

        objects = list(
            db.scalars(
                select(EngineeringObject)
                .options(joinedload(EngineeringObject.current_version))
                .where(EngineeringObject.product_id == product.id)
            ).unique()
        )
        object_ids = [obj.id for obj in objects]
        keep_version_ids = {
            int(obj.current_version_id)
            for obj in objects
            if obj.current_version_id is not None
        }
        versions_removed = 0
        if object_ids:
            stale_stmt = select(ObjectVersion.id).where(ObjectVersion.object_id.in_(object_ids))
            if keep_version_ids:
                stale_stmt = stale_stmt.where(ObjectVersion.id.notin_(keep_version_ids))
            stale_ids = list(db.scalars(stale_stmt).all())
            versions_removed = len(stale_ids)
            for start in range(0, len(stale_ids), 400):
                chunk = stale_ids[start : start + 400]
                if not chunk:
                    continue
                db.execute(delete(Parameter).where(Parameter.version_id.in_(chunk)))
                db.execute(delete(ObjectVersion).where(ObjectVersion.id.in_(chunk)))
            if keep_version_ids:
                db.execute(
                    update(ObjectVersion)
                    .where(ObjectVersion.id.in_(list(keep_version_ids)))
                    .values(git_commit_hash=new_head)
                )
            db.flush()

        after = _directory_size_bytes(git_dir)
        ctx.activities.record(
            db,
            ActivityAction.VAULT_HISTORY_COMPACTED,
            user,
            product_id=product.id,
            object_id=None,
            details={
                "product": product.name,
                "new_head": new_head,
                "versions_removed": versions_removed,
                "git_bytes_before": before,
                "git_bytes_after": after,
            },
        )
        db.flush()

    logger.info(
        "Compacted vault history for %s (%s); removed %s old versions; .git %s → %s",
        product.name,
        product.uuid,
        versions_removed,
        before,
        after,
    )
    return CompactVaultResult(
        product_uuid=product.uuid,
        product_name=product.name,
        new_head=new_head,
        versions_removed=versions_removed,
        git_bytes_before=before,
        git_bytes_after=after,
    )


_LOG_TAIL_MAX_BYTES = 256_000
_LOG_TAIL_MAX_LINES = 400


@dataclass(frozen=True, slots=True)
class ServerLogFileInfo:
    name: str
    size_label: str
    mtime_label: str


@dataclass(frozen=True, slots=True)
class ServerLogView:
    logs_dir_display: str
    files: tuple[ServerLogFileInfo, ...]
    selected_name: str | None
    content: str
    truncated: bool
    error: str | None = None


def _safe_log_path(logs_dir: Path, name: str) -> Path:
    """Resolve a log filename under logs_dir; reject path traversal."""
    raw = (name or "").strip()
    if not raw or raw in {".", ".."} or "/" in raw or "\\" in raw or Path(raw).name != raw:
        raise ValidationAppError("Invalid log file name.")
    root = logs_dir.resolve()
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValidationAppError("Invalid log file name.") from exc
    if not candidate.is_file():
        raise ValidationAppError("Log file not found.", details={"name": raw})
    return candidate


def list_server_log_files(logs_dir: Path) -> list[ServerLogFileInfo]:
    """Flat list of regular files in the server logs directory (newest first)."""
    root = Path(logs_dir)
    if not root.is_dir():
        return []
    rows: list[tuple[float, ServerLogFileInfo]] = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    for path in entries:
        try:
            if not path.is_file():
                continue
            st = path.stat()
        except OSError:
            continue
        mtime = datetime.fromtimestamp(st.st_mtime).astimezone()
        rows.append(
            (
                st.st_mtime,
                ServerLogFileInfo(
                    name=path.name,
                    size_label=_format_storage_bytes(int(st.st_size)),
                    mtime_label=mtime.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
        )
    rows.sort(key=lambda item: item[0], reverse=True)
    return [info for _mtime, info in rows]


def read_server_log_tail(
    path: Path,
    *,
    max_bytes: int = _LOG_TAIL_MAX_BYTES,
    max_lines: int = _LOG_TAIL_MAX_LINES,
) -> tuple[str, bool]:
    """Return (text, truncated) for the end of a log file."""
    try:
        size = int(path.stat().st_size)
    except OSError as exc:
        raise ValidationAppError(f"Could not read log: {exc}") from exc
    truncated = False
    try:
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(-max_bytes, os.SEEK_END)
                truncated = True
            data = handle.read()
    except OSError as exc:
        raise ValidationAppError(f"Could not read log: {exc}") from exc
    text = data.decode("utf-8", errors="replace")
    if truncated and text:
        # Drop a partial first line after a mid-file seek.
        nl = text.find("\n")
        if nl >= 0:
            text = text[nl + 1 :]
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        truncated = True
    return "\n".join(lines), truncated


def load_server_log_view(ctx: AppContext, *, name: str | None = None) -> ServerLogView:
    """Pick a log under the configured logs dir and return a safe tail view."""
    logs_dir = ctx.config.logs_dir
    display = path_for_settings_display(logs_dir)
    files = list_server_log_files(logs_dir)
    file_tuple = tuple(files)
    if not files:
        return ServerLogView(
            logs_dir_display=display,
            files=(),
            selected_name=None,
            content="",
            truncated=False,
            error="No log files found in the logs directory.",
        )
    requested = (name or "").strip()
    if requested:
        try:
            path = _safe_log_path(logs_dir, requested)
        except ValidationAppError as exc:
            return ServerLogView(
                logs_dir_display=display,
                files=file_tuple,
                selected_name=None,
                content="",
                truncated=False,
                error=exc.message,
            )
        selected = path.name
    else:
        names = {row.name for row in files}
        selected = "creopdm.log" if "creopdm.log" in names else files[0].name
        path = _safe_log_path(logs_dir, selected)
    try:
        content, truncated = read_server_log_tail(path)
    except ValidationAppError as exc:
        return ServerLogView(
            logs_dir_display=display,
            files=file_tuple,
            selected_name=selected,
            content="",
            truncated=False,
            error=exc.message,
        )
    return ServerLogView(
        logs_dir_display=display,
        files=file_tuple,
        selected_name=selected,
        content=content,
        truncated=truncated,
        error=None,
    )


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
        _volume_usage("System", data_dir),
        _directory_usage("Data directory", data_dir),
        _directory_usage("Vaults", vaults_dir),
        _directory_usage("Logs", logs_dir),
    ]

    for row in disks:
        if row.error:
            if overall == "ok":
                overall = "degraded"
            continue
        if (
            row.kind == "volume"
            and row.free_bytes is not None
            and row.free_bytes < _LOW_DISK_BYTES
        ):
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
    cpu = collect_cpu_usage()

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
        cpu=cpu,
        disk=disks,
        product_count=product_count,
        user_count=user_count,
        active_checkout_count=active_checkout_count,
        data_dir=path_for_settings_display(data_dir),
        vaults_dir=path_for_settings_display(vaults_dir),
        logs_dir=path_for_settings_display(logs_dir),
        agent_base_url=(ctx.settings.ui.agent_base_url or "http://127.0.0.1:8766").rstrip("/"),
    )
