"""In-memory progress for Add ▾ → Compressed data… (zip import)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


# uploading | extracting | importing | committing | recording | done | error
_ACTIVE = frozenset({"queued", "uploading", "extracting", "importing", "committing", "recording"})


def _format_bytes(value: int) -> str:
    size = max(0, int(value))
    if size < 1024:
        return f"{size} B"
    amount = float(size)
    for unit in ("KB", "MB", "GB", "TB"):
        amount /= 1024.0
        if amount < 1024.0 or unit == "TB":
            text = f"{amount:.0f}" if amount >= 10 else f"{amount:.1f}".rstrip("0").rstrip(".")
            return f"{text} {unit}"
    return f"{size} B"


@dataclass
class ZipImportJobStatus:
    job_id: str
    product_id: str
    state: str = "queued"
    phase: str = "queued"
    message: str = "Starting compressed import…"
    bytes_total: int = 0
    bytes_done: int = 0
    files_total: int = 0
    files_done: int = 0
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None

    @property
    def done(self) -> bool:
        return self.state in {"done", "error"}


@dataclass
class ZipImportJobs:
    """One progress snapshot per zip-import job (memory only; not durable)."""

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _jobs: dict[str, ZipImportJobStatus] = field(default_factory=dict)

    def create(self, product_id: str) -> ZipImportJobStatus:
        job_id = str(uuid.uuid4())
        status = ZipImportJobStatus(
            job_id=job_id,
            product_id=product_id,
            state="queued",
            phase="queued",
            message="Starting compressed import…",
            started_at=time.time(),
        )
        with self._lock:
            self._jobs[job_id] = status
        return self.get(job_id)

    def get(self, job_id: str) -> ZipImportJobStatus | None:
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                return None
            return ZipImportJobStatus(
                job_id=current.job_id,
                product_id=current.product_id,
                state=current.state,
                phase=current.phase,
                message=current.message,
                bytes_total=current.bytes_total,
                bytes_done=current.bytes_done,
                files_total=current.files_total,
                files_done=current.files_done,
                error=current.error,
                started_at=current.started_at,
                finished_at=current.finished_at,
            )

    def update(
        self,
        job_id: str,
        *,
        phase: str | None = None,
        message: str | None = None,
        bytes_total: int | None = None,
        bytes_done: int | None = None,
        files_total: int | None = None,
        files_done: int | None = None,
        error: str | None = None,
        state: str | None = None,
    ) -> None:
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                return
            if phase is not None:
                current.phase = phase
                if state is None and phase in _ACTIVE:
                    current.state = phase if phase != "queued" else "queued"
            if state is not None:
                current.state = state
            if message is not None:
                current.message = message
            if bytes_total is not None:
                current.bytes_total = int(bytes_total)
            if bytes_done is not None:
                current.bytes_done = int(bytes_done)
            if files_total is not None:
                current.files_total = int(files_total)
            if files_done is not None:
                current.files_done = int(files_done)
            if error is not None:
                current.error = error
            if current.state in {"done", "error"} and current.finished_at is None:
                current.finished_at = time.time()

    def set_uploading(self, job_id: str, *, bytes_done: int, bytes_total: int) -> None:
        total = max(0, int(bytes_total))
        done = max(0, min(int(bytes_done), total if total else int(bytes_done)))
        if total > 0:
            pct = int(100.0 * done / total)
            msg = f"Uploading zip… {_format_bytes(done)} of {_format_bytes(total)} ({pct}%)"
        else:
            msg = f"Uploading zip… {_format_bytes(done)}"
        self.update(
            job_id,
            phase="uploading",
            state="uploading",
            message=msg,
            bytes_done=done,
            bytes_total=total,
        )

    def set_extracting(self, job_id: str) -> None:
        self.update(
            job_id,
            phase="extracting",
            state="extracting",
            message="Extracting zip…",
        )

    def set_importing(self, job_id: str, *, files_done: int, files_total: int) -> None:
        total = max(0, int(files_total))
        done = max(0, int(files_done))
        if total > 0:
            msg = f"Importing files… {done} of {total}"
        else:
            msg = "Importing files…"
        self.update(
            job_id,
            phase="importing",
            state="importing",
            message=msg,
            files_done=done,
            files_total=total,
        )

    def set_committing(self, job_id: str, *, files_total: int) -> None:
        self.update(
            job_id,
            phase="committing",
            state="committing",
            message=f"Committing {max(0, int(files_total))} files to Git…",
            files_total=files_total,
            files_done=files_total,
        )

    def set_recording(self, job_id: str, *, files_done: int = 0, files_total: int = 0) -> None:
        total = max(0, int(files_total))
        done = max(0, int(files_done))
        if total > 0 and done > 0:
            msg = f"Recording in database… {done} of {total}"
        elif total > 0:
            msg = f"Recording {total} files in database…"
        else:
            msg = "Recording in database…"
        self.update(
            job_id,
            phase="recording",
            state="recording",
            message=msg,
            files_done=done,
            files_total=total,
        )

    def set_done(self, job_id: str, *, files_total: int = 0) -> None:
        self.update(
            job_id,
            phase="done",
            state="done",
            message="Import complete.",
            files_total=files_total,
            files_done=files_total,
        )

    def set_error(self, job_id: str, message: str) -> None:
        self.update(
            job_id,
            phase="error",
            state="error",
            message=message or "Compressed import failed.",
            error=message or "Compressed import failed.",
        )
