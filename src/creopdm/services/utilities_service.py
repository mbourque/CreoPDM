"""Server diagnostics and admin utilities for Administration → Utilities."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, exists, func, or_, select, text, update
from sqlalchemy.orm import Session, joinedload

from creopdm.auth_constants import UserStatus
from creopdm.config import (
    database_url_for_display,
    path_for_settings_display,
    sqlite_url_for_settings_display,
)
from creopdm.constants import (
    APP_NAME,
    APP_VERSION,
    ActivityAction,
    CheckoutStatus,
    DEFAULT_BRANCH,
    DEFAULT_REVISION,
    INITIAL_ITERATION,
    LifecycleState,
)
from creopdm.context import AppContext
from creopdm.creo.file_manager import CreoFileManager
from creopdm.exceptions import (
    PathValidationError,
    ProductNotFoundError,
    RepositoryError,
    ValidationAppError,
)
from creopdm.logging_setup import get_logger
from creopdm.models.activity import Activity
from creopdm.models.checkout import Checkout
from creopdm.models.dependency import Dependency
from creopdm.models.object import EngineeringObject
from creopdm.models.parameter import Parameter
from creopdm.models.product import Product
from creopdm.models.user import User
from creopdm.models.version import ObjectVersion
from creopdm.schemas.common import (
    UtilitiesCpuUsage,
    UtilitiesDiskUsage,
    UtilitiesIoUsage,
    UtilitiesProbe,
    UtilitiesProductHealth,
    UtilitiesProductIssue,
    UtilitiesStatusResponse,
)
from creopdm.site_availability import normalize_site_availability
from creopdm.utils.classify import classify_filename
from creopdm.utils.creo_header import creo_release_for
from creopdm.utils.hashing import calculate_sha256
from creopdm.utils.paths import assert_safe_relative_path
from creopdm.utils.vault_folder import validate_vault_folder

logger = get_logger("utilities")

# Warn when free space on a volume drops below this (bytes).
_LOW_DISK_BYTES = 1_073_741_824  # 1 GiB
# CPU section badge only (does not change overall health status).
_CPU_BUSY_PERCENT = 70.0
_CPU_HOT_PERCENT = 90.0
_CPU_SAMPLE_SECONDS = 0.2
# I/O wait badge only (does not change overall health status).
_IOWAIT_BUSY_PERCENT = 20.0
_IOWAIT_HOT_PERCENT = 40.0
_IO_SAMPLE_SECONDS = 0.2
# /proc/diskstats reports sectors; Linux keeps the historical 512-byte unit.
_DISKSTATS_SECTOR_BYTES = 512
_WHOLE_DISK_NAME = re.compile(
    r"^(?:sd[a-z]+|hd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme\d+n\d+|mmcblk\d+)$"
)
# Lightweight product vault probes (Utilities → Health → Products).
_PRODUCT_GIT_TIMEOUT_SEC = 5.0
_MAX_TIP_HASHES_PER_PRODUCT = 5
_MAX_PRODUCT_ISSUES_SHOWN = 30


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


@dataclass(frozen=True, slots=True)
class RebuildProductDbResult:
    product_uuid: str
    product_name: str
    head: str
    objects_removed: int
    files_registered: int


@dataclass(frozen=True, slots=True)
class ProductDbRepairResult:
    """Outcome of Utilities → Rebuild / clear metadata / rebuild Where Used."""

    product_uuid: str
    product_name: str
    rebuilt: bool = False
    head: str = ""
    objects_removed: int = 0
    files_registered: int = 0
    metadata_cleared: bool = False
    metadata_versions: int = 0
    where_used_rebuilt: bool = False
    where_used_edges_added: int = 0
    where_used_edges_existing: int = 0


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


def _io_status_for_iowait(percent: float | None) -> str:
    if percent is None:
        return "ok"
    if percent >= _IOWAIT_HOT_PERCENT:
        return "hot"
    if percent >= _IOWAIT_BUSY_PERCENT:
        return "busy"
    return "ok"


def _format_bytes_per_sec(value: int | None) -> str:
    if value is None:
        return "—"
    if value < 0:
        return "—"
    return f"{_format_storage_bytes(int(value))}/s"


def _read_iowait_times() -> tuple[float, float] | None:
    """Return ``(iowait, total)`` from Linux ``/proc/stat``, or None."""
    if not sys.platform.startswith("linux"):
        return None
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
    if len(values) < 5:
        return None
    iowait = values[4]
    total = sum(values)
    return iowait, total


def _read_disk_sector_totals() -> tuple[int, int] | None:
    """Sum read/write sectors for whole disks from Linux ``/proc/diskstats``."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open("/proc/diskstats", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return None
    read_sectors = 0
    write_sectors = 0
    matched = 0
    for line in lines:
        parts = line.split()
        if len(parts) < 10:
            continue
        name = parts[2]
        if not _WHOLE_DISK_NAME.match(name):
            continue
        try:
            read_sectors += int(parts[5])
            write_sectors += int(parts[9])
        except (TypeError, ValueError):
            continue
        matched += 1
    if matched == 0:
        return None
    return read_sectors, write_sectors


def _read_net_byte_totals() -> tuple[int, int] | None:
    """Sum RX/TX bytes across non-loopback interfaces from Linux ``/proc/net/dev``."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        with open("/proc/net/dev", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return None
    rx_total = 0
    tx_total = 0
    matched = 0
    for line in lines:
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        iface = name.strip()
        if not iface or iface == "lo":
            continue
        parts = rest.split()
        if len(parts) < 9:
            continue
        try:
            rx_total += int(parts[0])
            tx_total += int(parts[8])
        except (TypeError, ValueError):
            continue
        matched += 1
    if matched == 0:
        return None
    return rx_total, tx_total


def _rate_from_counters(
    first: tuple[int, int] | None,
    second: tuple[int, int] | None,
    *,
    elapsed: float,
    scale: int = 1,
) -> tuple[int | None, int | None]:
    if first is None or second is None:
        return None, None
    elapsed = max(0.05, float(elapsed))
    a = max(0, second[0] - first[0])
    b = max(0, second[1] - first[1])
    return (
        int(round(a * scale / elapsed)),
        int(round(b * scale / elapsed)),
    )


def _sample_linux_io(
    sample_seconds: float = _IO_SAMPLE_SECONDS,
) -> tuple[float | None, int | None, int | None, int | None, int | None]:
    """Return ``(iowait%, disk_read, disk_write, net_rx, net_tx)`` over one sample."""
    first_io = _read_iowait_times()
    first_disk = _read_disk_sector_totals()
    first_net = _read_net_byte_totals()
    if first_io is None and first_disk is None and first_net is None:
        return None, None, None, None, None
    elapsed = max(0.05, float(sample_seconds))
    time.sleep(elapsed)
    second_io = _read_iowait_times()
    second_disk = _read_disk_sector_totals()
    second_net = _read_net_byte_totals()

    iowait_percent: float | None = None
    if first_io is not None and second_io is not None:
        iowait_delta = second_io[0] - first_io[0]
        total_delta = second_io[1] - first_io[1]
        if total_delta > 0:
            iowait_percent = max(0.0, min(100.0, 100.0 * (iowait_delta / total_delta)))

    read_bps, write_bps = _rate_from_counters(
        first_disk, second_disk, elapsed=elapsed, scale=_DISKSTATS_SECTOR_BYTES
    )
    net_rx, net_tx = _rate_from_counters(first_net, second_net, elapsed=elapsed, scale=1)
    return iowait_percent, read_bps, write_bps, net_rx, net_tx


def _sample_windows_io_bps(
    sample_seconds: float = _IO_SAMPLE_SECONDS,
) -> tuple[int | None, int | None, int | None, int | None]:
    """Best-effort disk + network bytes/sec via PDH (Windows)."""
    if sys.platform != "win32":
        return None, None, None, None
    try:
        import ctypes
        from ctypes import wintypes

        pdh = ctypes.windll.pdh
        query = wintypes.HANDLE()
        if pdh.PdhOpenQueryW(None, 0, ctypes.byref(query)) != 0:
            return None, None, None, None

        class PdhFmtCounterValue(ctypes.Structure):
            class _Value(ctypes.Union):
                _fields_ = [
                    ("longValue", ctypes.c_long),
                    ("doubleValue", ctypes.c_double),
                    ("largeValue", ctypes.c_longlong),
                    ("AnsiStringValue", ctypes.c_char_p),
                    ("WideStringValue", ctypes.c_wchar_p),
                ]

            _fields_ = [("CStatus", wintypes.DWORD), ("value", _Value)]

        PDH_FMT_DOUBLE = 0x00000200
        disk_paths = (
            r"\PhysicalDisk(_Total)\Disk Read Bytes/sec",
            r"\PhysicalDisk(_Total)\Disk Write Bytes/sec",
        )
        net_paths = (
            r"\Network Interface(_Total)\Bytes Received/sec",
            r"\Network Interface(_Total)\Bytes Sent/sec",
        )
        counters: list[wintypes.HANDLE] = []
        try:
            for path in disk_paths:
                counter = wintypes.HANDLE()
                if pdh.PdhAddEnglishCounterW(query, path, 0, ctypes.byref(counter)) != 0:
                    return None, None, None, None
                counters.append(counter)
            # Network is optional — only include when both counters add cleanly.
            net_handles: list[wintypes.HANDLE] = []
            for path in net_paths:
                counter = wintypes.HANDLE()
                if pdh.PdhAddEnglishCounterW(query, path, 0, ctypes.byref(counter)) != 0:
                    net_handles = []
                    break
                net_handles.append(counter)
            counters.extend(net_handles)
            if pdh.PdhCollectQueryData(query) != 0:
                return None, None, None, None
            time.sleep(max(0.05, float(sample_seconds)))
            if pdh.PdhCollectQueryData(query) != 0:
                return None, None, None, None
            values: list[int] = []
            for counter in counters:
                fmt = PdhFmtCounterValue()
                if (
                    pdh.PdhGetFormattedCounterValue(
                        counter, PDH_FMT_DOUBLE, None, ctypes.byref(fmt)
                    )
                    != 0
                ):
                    return None, None, None, None
                values.append(max(0, int(round(float(fmt.value.doubleValue)))))
            if len(values) < 2:
                return None, None, None, None
            disk_read, disk_write = values[0], values[1]
            if len(values) >= 4:
                return disk_read, disk_write, values[2], values[3]
            return disk_read, disk_write, None, None
        finally:
            pdh.PdhCloseQuery(query)
    except Exception:  # noqa: BLE001 — best-effort host probe
        return None, None, None, None


def collect_io_usage() -> UtilitiesIoUsage:
    """Read host I/O wait, disk, and network rates for Utilities → Health (display only)."""
    iowait: float | None = None
    read_bps: int | None = None
    write_bps: int | None = None
    net_rx: int | None = None
    net_tx: int | None = None
    error: str | None = None
    try:
        if sys.platform.startswith("linux"):
            iowait, read_bps, write_bps, net_rx, net_tx = _sample_linux_io()
        elif sys.platform == "win32":
            read_bps, write_bps, net_rx, net_tx = _sample_windows_io_bps()
            if read_bps is None and write_bps is None and net_rx is None and net_tx is None:
                error = "Disk/network throughput is not available on this host."
            else:
                error = "I/O wait is a Linux kernel metric (not available on Windows)."
        else:
            error = "I/O metrics are not available on this platform."
    except Exception as exc:  # noqa: BLE001
        error = str(exc) or "I/O sample failed"
        iowait = None
        read_bps = None
        write_bps = None
        net_rx = None
        net_tx = None

    if (
        iowait is None
        and read_bps is None
        and write_bps is None
        and net_rx is None
        and net_tx is None
        and error is None
    ):
        error = "I/O metrics are not available on this host."

    return UtilitiesIoUsage(
        iowait_percent=None if iowait is None else round(iowait, 1),
        iowait_label="—" if iowait is None else f"{iowait:.0f}%",
        status=_io_status_for_iowait(iowait),
        read_bytes_per_sec=read_bps,
        write_bytes_per_sec=write_bps,
        read_label=_format_bytes_per_sec(read_bps),
        write_label=_format_bytes_per_sec(write_bps),
        net_rx_bytes_per_sec=net_rx,
        net_tx_bytes_per_sec=net_tx,
        net_rx_label=_format_bytes_per_sec(net_rx),
        net_tx_label=_format_bytes_per_sec(net_tx),
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
    confirm_password: str,
) -> CompactVaultResult:
    """Squash one product vault to a single tip commit and prune old ObjectVersions.

    Requires the signed-in user's password. Rejects dirty vaults and
    products with active checkouts.
    """
    from creopdm.utils.danger_confirm import require_danger_password

    uuid = (product_uuid or "").strip()
    if not uuid:
        raise ValidationAppError("Choose a product.")
    require_danger_password(ctx, db, confirm_password)

    product = db.scalar(select(Product).where(Product.uuid == uuid))
    if product is None:
        raise ProductNotFoundError("Product not found.", details={"uuid": uuid})

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


def _list_tracked_vault_relpaths(git_exe: str, vault: Path) -> list[str]:
    """Tracked paths at HEAD (``git ls-files``), posix, no ``.gitkeep``."""
    result = _run_git_readonly(
        git_exe,
        ["ls-files", "-z"],
        cwd=vault,
        timeout=120.0,
    )
    if result is None or result.returncode != 0:
        detail = ""
        if result is not None:
            detail = (result.stderr or result.stdout or "").strip()
        raise RepositoryError(
            detail or "Could not list tracked vault files (git ls-files failed).",
            details={"vault": str(vault)},
        )
    out: list[str] = []
    for raw in (result.stdout or "").split("\0"):
        rel = str(raw or "").replace("\\", "/").strip().lstrip("./")
        if not rel or rel.endswith("/"):
            continue
        if Path(rel).name in {".gitkeep", ".gitignore"}:
            continue
        try:
            out.append(assert_safe_relative_path(rel).as_posix())
        except Exception:  # noqa: BLE001 — skip unsafe/odd paths
            continue
    return out


def _clear_product_object_records(db: Session, product: Product) -> int:
    """Remove objects/versions/deps/checkouts for a product; keep the Product row."""
    objects = list(
        db.scalars(select(EngineeringObject).where(EngineeringObject.product_id == product.id))
    )
    object_ids = [item.id for item in objects]
    if not object_ids:
        db.execute(delete(Dependency).where(Dependency.product_id == product.id))
        db.flush()
        return 0
    db.execute(
        update(EngineeringObject)
        .where(EngineeringObject.id.in_(object_ids))
        .values(current_version_id=None)
    )
    db.flush()
    db.execute(delete(Parameter).where(Parameter.object_id.in_(object_ids)))
    db.execute(delete(Checkout).where(Checkout.object_id.in_(object_ids)))
    db.execute(
        delete(Dependency).where(
            or_(
                Dependency.parent_object_id.in_(object_ids),
                Dependency.child_object_id.in_(object_ids),
                Dependency.product_id == product.id,
            )
        )
    )
    # Keep audit rows; null live object FKs (snapshots remain on Activity).
    db.execute(update(Activity).where(Activity.object_id.in_(object_ids)).values(object_id=None))
    db.execute(delete(ObjectVersion).where(ObjectVersion.object_id.in_(object_ids)))
    db.execute(delete(EngineeringObject).where(EngineeringObject.id.in_(object_ids)))
    db.flush()
    # Core DELETE leaves ORM instances in the identity map; expire_all is not
    # enough — SQLite reuses PKs and SA warns "Identity map already had…".
    # Caller must re-load Product after this (expunge_all detaches it).
    db.expunge_all()
    return len(object_ids)


def _load_product_for_repair(
    db: Session, *, product_uuid: str
) -> Product:
    uuid_value = (product_uuid or "").strip()
    if not uuid_value:
        raise ValidationAppError("Choose a product.")
    product = db.scalar(select(Product).where(Product.uuid == uuid_value))
    if product is None:
        raise ProductNotFoundError("Product not found.", details={"uuid": uuid_value})
    return product


def _confirm_and_load_product_for_repair(
    ctx: AppContext,
    db: Session,
    *,
    product_uuid: str,
    confirm_password: str,
) -> Product:
    from creopdm.utils.danger_confirm import require_danger_password

    require_danger_password(ctx, db, confirm_password)
    return _load_product_for_repair(db, product_uuid=product_uuid)


def _count_active_checkouts(db: Session, product_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Checkout)
            .join(EngineeringObject, EngineeringObject.id == Checkout.object_id)
            .where(
                EngineeringObject.product_id == product_id,
                Checkout.status == CheckoutStatus.ACTIVE.value,
            )
        )
        or 0
    )


def clear_product_creo_metadata(
    ctx: AppContext,
    db: Session,
    *,
    product_uuid: str,
    confirm_password: str,
) -> tuple[Product, int]:
    """Strip collected Creo metadata from all versions for one product (DB only)."""
    product = _confirm_and_load_product_for_repair(
        ctx, db, product_uuid=product_uuid, confirm_password=confirm_password
    )
    object_ids = list(
        db.scalars(
            select(EngineeringObject.id).where(EngineeringObject.product_id == product.id)
        ).all()
    )
    if not object_ids:
        return product, 0
    with ctx.locks.acquire(product.uuid, timeout=60.0):
        db.execute(delete(Parameter).where(Parameter.object_id.in_(object_ids)))
        result = db.execute(
            update(ObjectVersion)
            .where(ObjectVersion.object_id.in_(object_ids))
            .values(
                identity_json=None,
                materials_json=None,
                bom_json=None,
                units_json=None,
                mass_json=None,
                family_table_json=None,
                features_json=None,
            )
        )
        cleared = int(result.rowcount or 0)
        ctx.activities.record(
            db,
            ActivityAction.PRODUCT_UPDATED,
            ctx.users.get_current_user(),
            product_id=product.id,
            object_id=None,
            details={
                "product": product.name,
                "action": "clear_creo_metadata",
                "versions_cleared": cleared,
            },
        )
        db.flush()
    return product, cleared


def repair_product_database(
    ctx: AppContext,
    db: Session,
    *,
    product_uuid: str,
    confirm_password: str,
    rebuild: bool = False,
    clear_metadata: bool = False,
    rebuild_where_used: bool = False,
) -> ProductDbRepairResult:
    """Run selected product DB repair actions (rebuild / clear metadata / rebuild WU)."""
    chosen = sum(bool(flag) for flag in (rebuild, clear_metadata, rebuild_where_used))
    if chosen != 1:
        raise ValidationAppError(
            "Choose one action: rebuild from vault, delete Creo metadata, "
            "or delete and rebuild Where Used."
        )
    product = _confirm_and_load_product_for_repair(
        ctx, db, product_uuid=product_uuid, confirm_password=confirm_password
    )

    rebuilt_flag = False
    head = ""
    objects_removed = 0
    files_registered = 0
    meta_cleared = False
    meta_versions = 0
    wu_rebuilt = False
    wu_added = 0
    wu_existing = 0

    if rebuild:
        rebuilt = rebuild_product_database_from_vault(
            ctx,
            db,
            product_uuid=product.uuid,
            confirm_password=confirm_password,
        )
        rebuilt_flag = True
        head = rebuilt.head
        objects_removed = rebuilt.objects_removed
        files_registered = rebuilt.files_registered
        # File-list rebuild drops old rows (metadata + Where Used go with them).
        meta_cleared = True
    elif clear_metadata:
        _, meta_versions = clear_product_creo_metadata(
            ctx, db, product_uuid=product.uuid, confirm_password=confirm_password
        )
        meta_cleared = True

    if rebuild_where_used:
        # Index after the request commits (same background job as the product gear).
        wu_rebuilt = True

    return ProductDbRepairResult(
        product_uuid=product.uuid,
        product_name=product.name,
        rebuilt=rebuilt_flag,
        head=head,
        objects_removed=objects_removed,
        files_registered=files_registered,
        metadata_cleared=meta_cleared,
        metadata_versions=meta_versions,
        where_used_rebuilt=wu_rebuilt,
        where_used_edges_added=wu_added,
        where_used_edges_existing=wu_existing,
    )


def rebuild_product_database_from_vault(
    ctx: AppContext,
    db: Session,
    *,
    product_uuid: str,
    confirm_password: str,
) -> RebuildProductDbResult:
    """Rebuild one product's file/version rows from the vault Git tip (DB only).

    Does not rewrite Git history. Clears checkouts, Where Used edges, and Creo
    metadata for that product's files. Works for locked / Archived products
    (admin recovery). Requires password re-auth and no active checkouts.
    """
    import uuid as uuid_mod

    product = _confirm_and_load_product_for_repair(
        ctx, db, product_uuid=product_uuid, confirm_password=confirm_password
    )

    active_checkouts = _count_active_checkouts(db, product.id)
    if active_checkouts:
        raise ValidationAppError(
            f"Release all checkouts first ({active_checkouts} active).",
            details={"active_checkouts": active_checkouts},
        )

    # Read-only path resolve — do not create a missing vault via ensure_vault.
    folder = _product_vault_folder_name(product)
    vault = _vault_path_without_mkdir(ctx.config.vaults_dir, folder)
    if vault is None or not vault.is_dir():
        raise ValidationAppError(
            "This product has no vault folder on disk to rebuild from.",
            details={"vault_folder": folder},
        )
    if not (vault / ".git").exists():
        raise ValidationAppError(
            "This product vault has no Git repository (.git missing).",
            details={"vault": str(vault)},
        )

    git_exe = (ctx.git.executable or "git").strip() or "git"
    head_proc = _run_git_readonly(git_exe, ["rev-parse", "HEAD"], cwd=vault, timeout=30.0)
    if head_proc is None or head_proc.returncode != 0:
        detail = ""
        if head_proc is not None:
            detail = (head_proc.stderr or head_proc.stdout or "").strip()
        raise ValidationAppError(
            detail or "Vault Git HEAD is unreadable; cannot rebuild from tip.",
            details={"vault": str(vault)},
        )
    head = (head_proc.stdout or "").strip()
    if not head:
        raise ValidationAppError("Vault Git HEAD is empty; cannot rebuild from tip.")

    tracked = _list_tracked_vault_relpaths(git_exe, vault)
    ignore = ctx.config.ignore_patterns()
    models = ctx.config.model_cad_extensions()
    data_extras = ctx.config.data_cad_extensions()
    documents = ctx.config.document_extensions()
    user = ctx.users.get_current_user()
    now = datetime.now(timezone.utc)

    with ctx.locks.acquire(product.uuid, timeout=120.0):
        active_checkouts = _count_active_checkouts(db, product.id)
        if active_checkouts:
            raise ValidationAppError(
                f"Release all checkouts first ({active_checkouts} active).",
                details={"active_checkouts": active_checkouts},
            )

        product_pk = int(product.id)
        removed = _clear_product_object_records(db, product)
        product = db.get(Product, product_pk)
        if product is None:
            raise ValidationAppError(
                "Product disappeared while rebuilding the database.",
                details={"product_id": product_pk},
            )
        registered = 0
        for rel in tracked:
            name = Path(rel).name
            if CreoFileManager.is_ignored(name, ignore):
                continue
            abs_path = vault / Path(rel)
            if not abs_path.is_file():
                continue
            logical = CreoFileManager.logical_repo_path(rel, models)
            stored_name = Path(logical).name
            stem = Path(stored_name).stem
            suffix = Path(stored_name).suffix.lower()
            object_type = classify_filename(
                stored_name,
                extra_cad_extensions=data_extras,
                model_extensions=models,
                document_extensions=documents,
            )
            try:
                digest = calculate_sha256(abs_path)
                size = int(abs_path.stat().st_size)
            except OSError as exc:
                raise RepositoryError(
                    f"Could not read vault file {rel}: {exc}",
                    details={"relative_path": rel},
                ) from exc
            release = creo_release_for(abs_path, stored_name)
            obj = EngineeringObject(
                uuid=str(uuid_mod.uuid4()),
                product_id=product.id,
                number=stem.upper()[:64] if stem else stored_name.upper()[:64],
                name=stem or stored_name,
                filename=stored_name,
                extension=(suffix or "")[:32],
                object_type=str(object_type.value),
                relative_path=logical,
                revision=DEFAULT_REVISION,
                iteration=INITIAL_ITERATION,
                lifecycle_state=LifecycleState.IN_WORK.value,
                created_at=now,
                updated_at=now,
            )
            db.add(obj)
            db.flush()
            version = ObjectVersion(
                uuid=str(uuid_mod.uuid4()),
                object_id=obj.id,
                revision=DEFAULT_REVISION,
                iteration=INITIAL_ITERATION,
                filename=stored_name,
                relative_path=logical,
                creo_release=release,
                git_commit_hash=head,
                content_hash=digest,
                file_size=size,
                created_by=user.user_name,
                created_at=now,
                comment="Rebuilt from vault Git tip",
            )
            db.add(version)
            db.flush()
            obj.current_version_id = version.id
            registered += 1

        product.updated_at = now
        ctx.activities.record(
            db,
            ActivityAction.PRODUCT_DB_REBUILT,
            user,
            product_id=product.id,
            object_id=None,
            details={
                "product": product.name,
                "head": head,
                "objects_removed": removed,
                "files_registered": registered,
            },
        )
        db.flush()

    logger.info(
        "Rebuilt product DB from vault for %s (%s): removed %s, registered %s @ %s",
        product.name,
        product.uuid,
        removed,
        registered,
        head[:12],
    )
    return RebuildProductDbResult(
        product_uuid=product.uuid,
        product_name=product.name,
        head=head,
        objects_removed=removed,
        files_registered=registered,
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


def _product_vault_folder_name(product: Product) -> str:
    return (product.vault_folder or "").strip() or product.uuid


def _vault_path_without_mkdir(vaults_dir: Path, folder_name: str) -> Path | None:
    """Resolve vaults/<folder> without creating directories (Health must stay read-only)."""
    try:
        folder = validate_vault_folder(folder_name)
    except (ValidationAppError, PathValidationError):
        return None
    return Path(vaults_dir) / folder


def _run_git_readonly(
    executable: str,
    args: list[str],
    *,
    cwd: Path,
    timeout: float = _PRODUCT_GIT_TIMEOUT_SEC,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            [executable, *args],
            cwd=str(cwd),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
            timeout=timeout,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None


def _issue(
    code: str,
    *,
    product_name: str = "",
    product_uuid: str = "",
    detail: str = "",
) -> UtilitiesProductIssue:
    return UtilitiesProductIssue(
        code=code,
        product_name=product_name,
        product_uuid=product_uuid,
        detail=detail,
    )


def collect_product_health(ctx: AppContext, db: Session) -> UtilitiesProductHealth:
    """Lightweight product vault / tip checks (no walks, no ensure_vault, no mutations)."""
    issues: list[UtilitiesProductIssue] = []
    products = list(db.scalars(select(Product).order_by(Product.name.asc())).all())
    vaults_dir = ctx.config.vaults_dir
    git_exe = (ctx.git.executable or "git").strip() or "git"
    known_folders: set[str] = set()

    for product in products:
        name = product.name or product.uuid
        uuid_value = product.uuid or ""
        raw_folder = _product_vault_folder_name(product)
        vault_path = _vault_path_without_mkdir(vaults_dir, raw_folder)
        if vault_path is None:
            issues.append(
                _issue(
                    "invalid_vault_folder",
                    product_name=name,
                    product_uuid=uuid_value,
                    detail=f"Invalid vault folder name: {raw_folder!r}",
                )
            )
            continue
        known_folders.add(vault_path.name.lower())

        if not vault_path.is_dir():
            issues.append(
                _issue(
                    "missing_vault",
                    product_name=name,
                    product_uuid=uuid_value,
                    detail=f"Vault folder missing: {path_for_settings_display(vault_path)}",
                )
            )
            continue

        git_dir = vault_path / ".git"
        if not git_dir.exists():
            issues.append(
                _issue(
                    "missing_git",
                    product_name=name,
                    product_uuid=uuid_value,
                    detail="Vault has no .git directory",
                )
            )
            continue

        head = _run_git_readonly(git_exe, ["rev-parse", "HEAD"], cwd=vault_path)
        if head is None or head.returncode != 0:
            detail = ""
            if head is not None:
                detail = (head.stderr or head.stdout or "").strip()
            issues.append(
                _issue(
                    "bad_git",
                    product_name=name,
                    product_uuid=uuid_value,
                    detail=detail or "git rev-parse HEAD failed",
                )
            )
            continue

        tip_hashes = list(
            db.scalars(
                select(ObjectVersion.git_commit_hash)
                .join(EngineeringObject, EngineeringObject.id == ObjectVersion.object_id)
                .where(
                    EngineeringObject.product_id == product.id,
                    EngineeringObject.current_version_id == ObjectVersion.id,
                    ObjectVersion.git_commit_hash.is_not(None),
                    ObjectVersion.git_commit_hash != "",
                )
                .distinct()
                .limit(_MAX_TIP_HASHES_PER_PRODUCT)
            ).all()
        )
        for tip_hash in tip_hashes:
            commit = str(tip_hash or "").strip()
            if not commit:
                continue
            probe = _run_git_readonly(
                git_exe, ["cat-file", "-e", f"{commit}^{{commit}}"], cwd=vault_path
            )
            if probe is None or probe.returncode != 0:
                issues.append(
                    _issue(
                        "missing_tip",
                        product_name=name,
                        product_uuid=uuid_value,
                        detail=f"Tip commit not in vault git: {commit[:12]}",
                    )
                )
                break

        versioned_without_tip = int(
            db.scalar(
                select(func.count())
                .select_from(EngineeringObject)
                .where(
                    EngineeringObject.product_id == product.id,
                    EngineeringObject.current_version_id.is_(None),
                    exists(
                        select(ObjectVersion.id).where(
                            ObjectVersion.object_id == EngineeringObject.id
                        )
                    ),
                )
            )
            or 0
        )
        if versioned_without_tip > 0:
            issues.append(
                _issue(
                    "missing_current_version",
                    product_name=name,
                    product_uuid=uuid_value,
                    detail=f"{versioned_without_tip} file(s) have history but no current version",
                )
            )

    # Orphan vault directories under vaults/ (no matching product folder).
    try:
        if vaults_dir.is_dir():
            for entry in vaults_dir.iterdir():
                try:
                    if not entry.is_dir():
                        continue
                    if entry.name.startswith("."):
                        continue
                    if entry.name.lower() in known_folders:
                        continue
                    issues.append(
                        _issue(
                            "orphan_vault",
                            product_name=entry.name,
                            detail=f"Vault folder has no product: {path_for_settings_display(entry)}",
                        )
                    )
                except OSError:
                    continue
    except OSError:
        pass

    # Active checkouts whose object row is gone (should be rare with FKs).
    dangling_checkouts = int(
        db.scalar(
            select(func.count())
            .select_from(Checkout)
            .outerjoin(EngineeringObject, EngineeringObject.id == Checkout.object_id)
            .where(
                Checkout.status == CheckoutStatus.ACTIVE.value,
                EngineeringObject.id.is_(None),
            )
        )
        or 0
    )
    if dangling_checkouts > 0:
        issues.append(
            _issue(
                "dangling_checkout",
                detail=f"{dangling_checkouts} active checkout(s) point at missing files",
            )
        )

    shown = issues[:_MAX_PRODUCT_ISSUES_SHOWN]
    issue_count = len(issues)
    checked = len(products)
    if checked == 0 and issue_count == 0:
        summary = "No products to check."
        status = "ok"
    elif issue_count == 0:
        summary = f"Checked {checked} product(s); no issues found."
        status = "ok"
    else:
        summary = f"Checked {checked} product(s); {issue_count} issue(s)."
        if issue_count > len(shown):
            summary += f" Showing first {len(shown)}."
        status = "degraded"

    return UtilitiesProductHealth(
        status=status,
        checked=checked,
        issue_count=issue_count,
        issues=shown,
        summary=summary,
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
    io = collect_io_usage()
    products = collect_product_health(ctx, db)
    if products.status != "ok" and overall == "ok":
        overall = "degraded"

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
        io=io,
        products=products,
        disk=disks,
        product_count=product_count,
        user_count=user_count,
        active_checkout_count=active_checkout_count,
        data_dir=path_for_settings_display(data_dir),
        vaults_dir=path_for_settings_display(vaults_dir),
        logs_dir=path_for_settings_display(logs_dir),
        agent_base_url=(ctx.settings.ui.agent_base_url or "http://127.0.0.1:8766").rstrip("/"),
    )
