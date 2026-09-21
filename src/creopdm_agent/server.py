"""Localhost HTTP API used by the CreoPDM page inside Creo's browser."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from creopdm_agent import __version__
from creopdm_agent.config import AgentConfig
from creopdm_agent.trash import move_to_trash

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


class OpenFolderRequest(BaseModel):
    project_id: str = ""
    folder: str = ""


class OpenFolderResponse(BaseModel):
    ok: bool = True
    path: str


class PushItem(BaseModel):
    object_id: str
    filename: str = ""


class PushRequest(BaseModel):
    pdm_url: str = ""
    project_id: str = ""
    token: str | None = None
    items: list[PushItem] = Field(default_factory=list)


class PushItemResult(BaseModel):
    object_id: str
    filename: str = ""
    ok: bool = False
    path: str | None = None
    bytes_written: int = 0
    message: str = ""


class PushResponse(BaseModel):
    ok: list[PushItemResult] = Field(default_factory=list)
    failed: list[PushItemResult] = Field(default_factory=list)


class PushPathsRequest(BaseModel):
    pdm_url: str = ""
    project_id: str = ""
    token: str | None = None
    relative_paths: list[str] = Field(default_factory=list)


class CacheFileInfo(BaseModel):
    relative_path: str
    filename: str
    size: int = 0
    saved_at: str = ""


class CacheFilesResponse(BaseModel):
    root: str
    files: list[CacheFileInfo] = Field(default_factory=list)


class DeletePathsRequest(BaseModel):
    project_id: str = ""
    relative_paths: list[str] = Field(default_factory=list)


class DeletePathsResponse(BaseModel):
    ok: list[PushItemResult] = Field(default_factory=list)
    failed: list[PushItemResult] = Field(default_factory=list)


class PurgeFloor(BaseModel):
    logical_path: str = ""
    min_keep: int = 0


class PurgeVersionsRequest(BaseModel):
    project_id: str = ""
    model_extensions: list[str] = Field(default_factory=list)
    floors: list[PurgeFloor] = Field(default_factory=list)
    dry_run: bool = False


class PurgeVersionsResponse(BaseModel):
    ok: list[PushItemResult] = Field(default_factory=list)
    failed: list[PushItemResult] = Field(default_factory=list)
    deleted: int = 0


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


def _find_cache_file(cache_dir: Path, filename: str) -> Path | None:
    """Latest Creo save (or exact name) for filename under the project cache folder."""
    from creopdm.creo.file_manager import CreoFileManager

    name = Path(filename or "").name.strip()
    if not name or not cache_dir.is_dir():
        return None
    # None → built-in versioned CAD set (models + openable + extras), so .tph.N works.
    latest = CreoFileManager.latest_in_directory(cache_dir, name, None)
    if latest is not None and latest.is_file():
        return latest
    exact = cache_dir / name
    return exact if exact.is_file() else None


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
        return {
            "ok": True,
            "app": "creopdm-agent",
            "version": __version__,
            "pdm_url": settings.pdm_url or None,
            "local_root": str(root),
            "port": settings.port,
            "health_interval_seconds": int(settings.health_interval_seconds or 0),
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

    def _project_cache_dir(project_id: str = "", folder: str = "") -> Path:
        base = settings.ensure_dirs().resolve()
        key = (project_id or "").strip()
        target = base / _safe_segment(key, "local") if key else base
        target.mkdir(parents=True, exist_ok=True)
        rel = (folder or "").replace("\\", "/").strip().strip("/")
        if rel:
            candidate = (target / Path(rel)).resolve()
            try:
                candidate.relative_to(target.resolve())
            except ValueError as exc:
                raise HTTPException(
                    status_code=403,
                    detail="Refusing to open a path outside the agent cache.",
                ) from exc
            if candidate.is_dir():
                return candidate
        return target.resolve()

    @app.post("/open-folder", response_model=OpenFolderResponse)
    def open_folder(payload: OpenFolderRequest) -> OpenFolderResponse:
        """Open the local agent cache folder in Explorer (client PC, not CreoPDM server)."""
        from creopdm.utils.launch import open_windows_folder

        target = _project_cache_dir(payload.project_id, payload.folder)
        try:
            open_windows_folder(target)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        logger.info("Opened local workspace folder %s", target)
        return OpenFolderResponse(path=str(target))

    @app.post("/push", response_model=PushResponse)
    def push_to_vault(payload: PushRequest) -> PushResponse:
        """Upload local agent-cache files into the CreoPDM vault working copies."""
        base = _normalize_base(payload.pdm_url or settings.pdm_url)
        project_key = _safe_segment(payload.project_id or "local", "local")
        cache_dir = root / project_key
        headers: dict[str, str] = {}
        token = (payload.token or settings.token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        ok: list[PushItemResult] = []
        failed: list[PushItemResult] = []
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            for item in payload.items:
                object_id = (item.object_id or "").strip()
                filename = Path(item.filename or "").name
                if not object_id:
                    failed.append(
                        PushItemResult(
                            object_id="",
                            filename=filename,
                            message="object_id is required.",
                        )
                    )
                    continue
                local = _find_cache_file(cache_dir, filename) if filename else None
                if local is None:
                    failed.append(
                        PushItemResult(
                            object_id=object_id,
                            filename=filename or object_id,
                            message=f"No local cache file found for {filename or object_id}.",
                        )
                    )
                    continue
                url = f"{base}/api/objects/{quote(object_id)}/workspace-content"
                try:
                    with local.open("rb") as handle:
                        response = client.put(
                            url,
                            headers=headers,
                            files={"file": (local.name, handle, "application/octet-stream")},
                        )
                except httpx.HTTPError as exc:
                    failed.append(
                        PushItemResult(
                            object_id=object_id,
                            filename=local.name,
                            message=f"Could not reach CreoPDM: {exc}",
                        )
                    )
                    continue
                if response.status_code >= 400:
                    detail = ""
                    try:
                        body = response.json()
                        detail = (
                            body.get("error", {}).get("message")
                            or body.get("detail")
                            or response.text
                        )
                    except Exception:
                        detail = response.text[:300]
                    failed.append(
                        PushItemResult(
                            object_id=object_id,
                            filename=local.name,
                            message=detail or f"CreoPDM returned {response.status_code}",
                        )
                    )
                    continue
                nbytes = local.stat().st_size
                ok.append(
                    PushItemResult(
                        object_id=object_id,
                        filename=local.name,
                        ok=True,
                        path=str(local),
                        bytes_written=nbytes,
                    )
                )
                logger.info("Pushed %s → vault (%s bytes)", local.name, nbytes)
        return PushResponse(ok=ok, failed=failed)

    @app.get("/files", response_model=CacheFilesResponse)
    def list_cache_files(project_id: str = "") -> CacheFilesResponse:
        """List files under the project agent-cache folder (local workspace)."""
        from datetime import datetime

        from creopdm.creo.file_manager import CreoFileManager

        target = _project_cache_dir(project_id)
        files: list[CacheFileInfo] = []
        skip_dirs = {".git", ".creopdm", "__pycache__"}
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [name for name in dirnames if name.lower() not in skip_dirs]
            folder = Path(dirpath)
            for name in filenames:
                if name.startswith(".") or CreoFileManager.is_ignored(name):
                    continue
                path = folder / name
                if not path.is_file():
                    continue
                try:
                    rel = path.resolve().relative_to(target.resolve()).as_posix()
                except ValueError:
                    continue
                size = 0
                stamp = ""
                try:
                    info = path.stat()
                    size = int(info.st_size)
                    stamp = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")
                except OSError:
                    pass
                files.append(
                    CacheFileInfo(
                        relative_path=rel,
                        filename=path.name,
                        size=size,
                        saved_at=stamp,
                    )
                )
        files.sort(key=lambda item: item.relative_path.lower())
        return CacheFilesResponse(root=str(target), files=files)

    @app.post("/push-paths", response_model=PushResponse)
    def push_paths_to_vault(payload: PushPathsRequest) -> PushResponse:
        """Upload new local-cache paths into the vault (for New files / Add)."""
        base = _normalize_base(payload.pdm_url or settings.pdm_url)
        project_id = (payload.project_id or "").strip()
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required.")
        cache_dir = _project_cache_dir(project_id)
        headers: dict[str, str] = {}
        token = (payload.token or settings.token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        ok: list[PushItemResult] = []
        failed: list[PushItemResult] = []
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            for raw in payload.relative_paths:
                rel = str(raw or "").replace("\\", "/").lstrip("/")
                if not rel or ".." in rel.split("/"):
                    failed.append(
                        PushItemResult(object_id=project_id, filename=rel, message="Invalid path.")
                    )
                    continue
                local = (cache_dir / rel).resolve()
                try:
                    local.relative_to(cache_dir.resolve())
                except ValueError:
                    failed.append(
                        PushItemResult(
                            object_id=project_id,
                            filename=Path(rel).name,
                            message="Path is outside the agent cache.",
                        )
                    )
                    continue
                if not local.is_file():
                    failed.append(
                        PushItemResult(
                            object_id=project_id,
                            filename=Path(rel).name,
                            message=f"No local cache file found for {rel}.",
                        )
                    )
                    continue
                url = (
                    f"{base}/api/projects/{quote(project_id)}/workspace-content"
                    f"?path={quote(rel)}"
                )
                try:
                    with local.open("rb") as handle:
                        response = client.put(
                            url,
                            headers=headers,
                            files={"file": (local.name, handle, "application/octet-stream")},
                        )
                except httpx.HTTPError as exc:
                    failed.append(
                        PushItemResult(
                            object_id=project_id,
                            filename=local.name,
                            message=f"Could not reach CreoPDM: {exc}",
                        )
                    )
                    continue
                if response.status_code >= 400:
                    detail = ""
                    try:
                        body = response.json()
                        detail = (
                            body.get("error", {}).get("message")
                            or body.get("detail")
                            or response.text
                        )
                    except Exception:
                        detail = response.text[:300]
                    failed.append(
                        PushItemResult(
                            object_id=project_id,
                            filename=local.name,
                            message=detail or f"CreoPDM returned {response.status_code}",
                        )
                    )
                    continue
                nbytes = local.stat().st_size
                ok.append(
                    PushItemResult(
                        object_id=project_id,
                        filename=local.name,
                        ok=True,
                        path=str(local),
                        bytes_written=nbytes,
                        message=rel,
                    )
                )
                logger.info("Pushed new path %s → vault (%s bytes)", rel, nbytes)
        return PushResponse(ok=ok, failed=failed)

    @app.post("/delete-paths", response_model=DeletePathsResponse)
    def delete_cache_paths(payload: DeletePathsRequest) -> DeletePathsResponse:
        """Delete files from the local agent cache (discard New file local rows)."""
        project_id = (payload.project_id or "").strip()
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required.")
        cache_dir = _project_cache_dir(project_id)
        ok: list[PushItemResult] = []
        failed: list[PushItemResult] = []
        for raw in payload.relative_paths:
            rel = str(raw or "").replace("\\", "/").lstrip("/")
            if not rel or ".." in rel.split("/"):
                failed.append(
                    PushItemResult(object_id=project_id, filename=rel, message="Invalid path.")
                )
                continue
            local = (cache_dir / rel).resolve()
            try:
                local.relative_to(cache_dir.resolve())
            except ValueError:
                failed.append(
                    PushItemResult(
                        object_id=project_id,
                        filename=Path(rel).name,
                        message="Path is outside the agent cache.",
                    )
                )
                continue
            if not local.is_file():
                failed.append(
                    PushItemResult(
                        object_id=project_id,
                        filename=Path(rel).name,
                        message=f"No local cache file found for {rel}.",
                    )
                )
                continue
            try:
                move_to_trash(local)
            except OSError as exc:
                failed.append(
                    PushItemResult(
                        object_id=project_id,
                        filename=local.name,
                        message=str(exc),
                    )
                )
                continue
            ok.append(
                PushItemResult(
                    object_id=project_id,
                    filename=local.name,
                    ok=True,
                    path=str(local),
                    message=rel,
                )
            )
            logger.info("Moved local cache path to trash %s", rel)
        return DeletePathsResponse(ok=ok, failed=failed)

    @app.post("/purge-versions", response_model=PurgeVersionsResponse)
    def purge_older_versions(payload: PurgeVersionsRequest) -> PurgeVersionsResponse:
        """Delete local cache saves strictly older than vault floors (keep == and >)."""
        from creopdm.constants import DEFAULT_CREO_MODEL_EXTENSIONS
        from creopdm.creo.file_manager import CreoFileManager

        project_id = (payload.project_id or "").strip()
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required.")
        cache_dir = _project_cache_dir(project_id)
        models = [str(item or "").strip() for item in payload.model_extensions if str(item or "").strip()]
        if not models:
            models = list(DEFAULT_CREO_MODEL_EXTENSIONS)
        floor_pairs: list[tuple[str, int]] = []
        for item in payload.floors:
            logical = str(item.logical_path or "").replace("\\", "/").lstrip("/")
            if not logical:
                continue
            floor_pairs.append((logical, int(item.min_keep or 0)))
        obsolete = CreoFileManager.paths_older_than_vault_floors(cache_dir, floor_pairs, models)
        ok: list[PushItemResult] = []
        failed: list[PushItemResult] = []
        cache_resolved = cache_dir.resolve()
        for local in obsolete:
            try:
                resolved = local.resolve()
                resolved.relative_to(cache_resolved)
            except (OSError, ValueError):
                failed.append(
                    PushItemResult(
                        object_id=project_id,
                        filename=local.name,
                        message="Path is outside the agent cache.",
                    )
                )
                continue
            try:
                rel = resolved.relative_to(cache_resolved).as_posix()
            except ValueError:
                rel = local.name
            if not resolved.is_file():
                continue
            if payload.dry_run:
                ok.append(
                    PushItemResult(
                        object_id=project_id,
                        filename=resolved.name,
                        ok=True,
                        path=str(resolved),
                        message=rel,
                    )
                )
                continue
            try:
                move_to_trash(resolved)
            except OSError as exc:
                failed.append(
                    PushItemResult(
                        object_id=project_id,
                        filename=resolved.name,
                        message=str(exc),
                    )
                )
                continue
            ok.append(
                PushItemResult(
                    object_id=project_id,
                    filename=resolved.name,
                    ok=True,
                    path=str(resolved),
                    message=rel,
                )
            )
            logger.info("Purged older-than-vault cache save to trash %s", rel)
        return PurgeVersionsResponse(ok=ok, failed=failed, deleted=len(ok))

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
