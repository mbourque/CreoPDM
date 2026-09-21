"""Localhost HTTP API used by the CreoPDM page inside Creo's browser."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from creopdm_agent import __version__
from creopdm_agent.config import AgentConfig

logger = logging.getLogger("creopdm_agent")

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-]+")


class MaterializeItem(BaseModel):
    object_id: str | None = None
    project_id: str | None = None
    relative_path: str | None = None
    filename: str | None = None
    disk_name: str | None = None


class MaterializeRequest(BaseModel):
    pdm_url: str = ""
    object_id: str | None = None
    project_id: str | None = None
    relative_path: str | None = None
    filename: str | None = None
    disk_name: str | None = None
    token: str | None = None
    companions: list[MaterializeItem] = Field(default_factory=list)


class MaterializeResponse(BaseModel):
    path: str
    working_directory: str
    filename: str
    disk_name: str
    bytes_written: int = 0
    companions_written: int = 0


class OpenLocalRequest(BaseModel):
    path: str
    # association = Windows default app; creo = launch Parametric with the file.
    mode: str = "association"


class OpenLocalResponse(BaseModel):
    ok: bool = True
    path: str
    mode: str = "association"


def _safe_segment(value: str, fallback: str = "file") -> str:
    text = _SAFE_NAME.sub("_", (value or "").strip()) or fallback
    return text[:180]


def _normalize_base(url: str) -> str:
    text = (url or "").strip().rstrip("/")
    if not text:
        raise HTTPException(status_code=400, detail="pdm_url is required.")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="pdm_url must be an http(s) URL.")
    return text


def _content_url(base: str, item: MaterializeItem) -> tuple[str, str]:
    if item.object_id:
        name = item.disk_name or item.filename or f"{item.object_id}.bin"
        return f"{base}/api/objects/{quote(item.object_id)}/content", name
    if item.project_id and item.relative_path:
        rel = item.relative_path.replace("\\", "/").lstrip("/")
        name = item.disk_name or item.filename or Path(rel).name
        return (
            f"{base}/api/projects/{quote(item.project_id)}/workspace/content?path={quote(rel)}",
            name,
        )
    raise HTTPException(
        status_code=400,
        detail="Provide object_id, or project_id with relative_path.",
    )


def _download(
    client: httpx.Client,
    base: str,
    item: MaterializeItem,
    target_dir: Path,
    headers: dict[str, str],
) -> tuple[Path, str, str, int]:
    url, suggested_name = _content_url(base, item)
    disk_name = _safe_segment(item.disk_name or suggested_name, "model.bin")
    logical = _safe_segment(
        item.filename or Path(disk_name).stem + Path(disk_name).suffix,
        disk_name,
    )
    target = target_dir / disk_name
    try:
        response = client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach CreoPDM at {base}: {exc}",
        ) from exc
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"CreoPDM returned {response.status_code} for {url}",
        )
    target.write_bytes(response.content)
    return target, logical, disk_name, len(response.content)


def create_agent_app(settings: AgentConfig) -> FastAPI:
    app = FastAPI(title="CreoPDM Agent", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    root = settings.ensure_dirs()

    @app.get("/health")
    def health() -> dict[str, object]:
        # Re-read disk so status_poll_interval_seconds is live after Settings save.
        try:
            from creopdm_agent.config import apply_runtime_settings, load_config

            apply_runtime_settings(settings, load_config())
        except Exception:
            pass
        return {
            "ok": True,
            "app": "creopdm-agent",
            "version": __version__,
            "pdm_url": settings.pdm_url or None,
            "local_root": str(root),
            "port": settings.port,
            "health_interval_seconds": settings.health_interval_seconds,
            "status_poll_interval_seconds": int(settings.status_poll_interval_seconds or 0),
        }

    @app.get("/workdir")
    def workdir(project_id: str = "") -> dict[str, str]:
        """Return (and create) the local cache folder Creo should use as WD."""
        base = settings.ensure_dirs()
        key = (project_id or "").strip()
        if key:
            path = base / _safe_segment(key, "local")
            path.mkdir(parents=True, exist_ok=True)
        else:
            path = base
        return {
            "path": str(path.resolve()),
            "local_root": str(base.resolve()),
        }

    @app.post("/materialize", response_model=MaterializeResponse)
    def materialize(payload: MaterializeRequest) -> MaterializeResponse:
        base = _normalize_base(payload.pdm_url or settings.pdm_url)
        primary = MaterializeItem(
            object_id=payload.object_id,
            project_id=payload.project_id,
            relative_path=payload.relative_path,
            filename=payload.filename,
            disk_name=payload.disk_name,
        )
        project_key = _safe_segment(payload.project_id or payload.object_id or "local", "local")
        target_dir = root / project_key
        target_dir.mkdir(parents=True, exist_ok=True)
        headers: dict[str, str] = {}
        token = (payload.token or settings.token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            target, logical, disk_name, nbytes = _download(
                client, base, primary, target_dir, headers
            )
            companions_written = 0
            for item in payload.companions:
                if not item.object_id and not (item.project_id and item.relative_path):
                    continue
                _download(client, base, item, target_dir, headers)
                companions_written += 1
        logger.info(
            "Materialized %s (%s bytes, %s companion%s) → %s",
            disk_name,
            nbytes,
            companions_written,
            "" if companions_written == 1 else "s",
            target_dir,
        )
        return MaterializeResponse(
            path=str(target.resolve()),
            working_directory=str(target_dir.resolve()),
            filename=logical,
            disk_name=disk_name,
            bytes_written=nbytes,
            companions_written=companions_written,
        )

    @app.post("/open", response_model=OpenLocalResponse)
    def open_local(payload: OpenLocalRequest) -> OpenLocalResponse:
        """Open a cache file with Creo Parametric or the Windows association."""
        from creopdm.creo.windows_connector import WindowsCreoConnector
        from creopdm.utils.launch import open_windows_file, start_executable, working_directory_for

        try:
            target = Path(payload.path).resolve()
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid path: {exc}") from exc
        root_resolved = root.resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail="Refusing to open a path outside the agent cache.",
            ) from exc
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"File not found: {target}")

        mode = (payload.mode or "association").strip().lower()
        if mode not in {"association", "creo"}:
            raise HTTPException(status_code=400, detail="mode must be 'association' or 'creo'.")

        workdir = working_directory_for(target)
        try:
            if mode == "creo":
                parametric = WindowsCreoConnector().find_executable()
                if parametric is None:
                    raise HTTPException(
                        status_code=500,
                        detail="Creo Parametric was not found on this PC.",
                    )
                # Keep the real disk name (.sldprt); do not normalize to Creo .prt.
                start_executable(
                    parametric,
                    target,
                    cwd=workdir,
                    logical_name=False,
                )
                logger.info("Opened %s with %s", target, parametric)
            else:
                open_windows_file(target, cwd=workdir)
                logger.info("Opened %s via Windows association", target)
        except HTTPException:
            raise
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return OpenLocalResponse(path=str(target), mode=mode)

    return app
