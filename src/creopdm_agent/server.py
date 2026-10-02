"""Localhost HTTP API used by the CreoPDM page inside Creo's browser."""

from __future__ import annotations

import logging
import os
import re
import tempfile
import zipfile
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

# Allow spaces so vault folders like "from ptc" stay "from ptc" in the agent
# cache (older builds turned spaces into underscores → false New/Modified).
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\- ]+")
_LEGACY_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-]+")
# Dotfile (+ Windows hidden attr on save). Legacy underscore name is migrated on load.
_CACHE_INDEX_NAME = ".creopdm_cache_index.json"
_LEGACY_CACHE_INDEX_NAME = "_creopdm_cache_index.json"


def _safe_segment(value: str, fallback: str = "file") -> str:
    text = _SAFE_NAME.sub("_", (value or "").strip()) or fallback
    return text[:180]


def _legacy_safe_segment(value: str, fallback: str = "file") -> str:
    """Pre-space-preserving sanitizer (spaces → _). Used to find old cache paths."""
    text = _LEGACY_SAFE_NAME.sub("_", (value or "").strip()) or fallback
    return text[:180]


def _legacy_cache_dest_relative(relative_path: str | None, disk_name: str) -> Path:
    leaf = _legacy_safe_segment(Path(disk_name or "").name or "model.bin", "model.bin")
    rel = (relative_path or "").replace("\\", "/").lstrip("/")
    parts = [part for part in rel.split("/") if part and part not in {".", ".."}]
    if len(parts) <= 1:
        return Path(leaf)
    dirs = [_legacy_safe_segment(part, "x") for part in parts[:-1]]
    return Path(*dirs) / leaf


def _apply_mtime(path: Path, timestamp: float | None) -> None:
    """Set atime/mtime after write_bytes so materialize matches vault dates."""
    if timestamp is None or not path.is_file():
        return
    try:
        ts = float(timestamp)
        if ts <= 0:
            return
        os.utime(path, (ts, ts))
    except OSError as exc:
        logger.debug("Could not set mtime on %s: %s", path, exc)


def _mtime_from_http_headers(headers: object) -> float | None:
    """Parse Last-Modified from an httpx / Starlette response headers mapping."""
    if headers is None:
        return None
    raw = None
    try:
        get = getattr(headers, "get", None)
        if callable(get):
            raw = get("last-modified") or get("Last-Modified")
        elif isinstance(headers, dict):
            raw = headers.get("last-modified") or headers.get("Last-Modified")
    except Exception:
        raw = None
    if not raw:
        return None
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(str(raw)).timestamp()
    except Exception:
        return None


def _mtime_from_zipinfo(info: zipfile.ZipInfo) -> float | None:
    """Zip entry local date_time → epoch seconds (same approach as zipfile.extract)."""
    try:
        import time

        return time.mktime(info.date_time + (0, 0, -1))
    except Exception:
        return None


def _cache_dest_relative(relative_path: str | None, disk_name: str) -> Path:
    """Relative path under the product cache, preserving vault folders.

    Leaf name is always ``disk_name`` (Creo numbered save when present). Parent
    folders come from ``relative_path`` so ``lib/step/pin.prt`` + ``pin.prt.1``
    becomes ``lib/step/pin.prt.1``.
    """
    leaf = _safe_segment(Path(disk_name or "").name or "model.bin", "model.bin")
    rel = (relative_path or "").replace("\\", "/").lstrip("/")
    parts = [part for part in rel.split("/") if part and part not in {".", ".."}]
    if len(parts) <= 1:
        return Path(leaf)
    dirs = [_safe_segment(part, "x") for part in parts[:-1]]
    return Path(*dirs) / leaf


def _product_cache_key(product_id: str = "", vault_folder: str = "") -> str:
    """Local agent-cache folder name: prefer vault_folder, else product UUID."""
    folder = (vault_folder or "").strip()
    if folder:
        return _safe_segment(folder, "local")
    return _safe_segment((product_id or "").strip() or "local", "local")


class MaterializeItem(BaseModel):
    object_id: str | None = None
    product_id: str | None = None
    relative_path: str | None = None
    filename: str | None = None
    disk_name: str | None = None


class MaterializeRequest(BaseModel):
    pdm_url: str = ""
    object_id: str | None = None
    product_id: str | None = None
    vault_folder: str = ""
    relative_path: str | None = None
    filename: str | None = None
    disk_name: str | None = None
    token: str | None = None
    companions: list[MaterializeItem] = Field(default_factory=list)
    # After History revert: download vault tip and trash local higher .N siblings.
    replace_newer: bool = False


class MaterializeResponse(BaseModel):
    path: str
    working_directory: str
    filename: str
    disk_name: str
    bytes_written: int = 0
    companions_written: int = 0
    purged_newer: list[str] = Field(default_factory=list)


class MaterializeZipRequest(BaseModel):
    pdm_url: str = ""
    product_id: str = ""
    vault_folder: str = ""
    object_ids: list[str] = Field(min_length=1)
    token: str | None = None


class MaterializeZipResponse(BaseModel):
    working_directory: str
    extracted_count: int = 0
    bytes_written: int = 0
    skipped_count: int = 0
    kept_newer_count: int = 0
    download_count: int = 0


class CachePlanItem(BaseModel):
    object_id: str
    filename: str = ""
    disk_name: str = ""
    relative_path: str = ""
    content_hash: str = ""
    file_size: int = 0


class CachePlanRequest(BaseModel):
    pdm_url: str = ""
    product_id: str = ""
    vault_folder: str = ""
    object_ids: list[str] = Field(min_length=1)
    token: str | None = None


class CachePlanResponse(BaseModel):
    download_ids: list[str] = Field(default_factory=list)
    skipped_count: int = 0
    kept_newer_count: int = 0
    total: int = 0


class OpenLocalRequest(BaseModel):
    path: str
    # association = Windows default app; creo = launch Parametric with the file.
    mode: str = "association"


class OpenLocalResponse(BaseModel):
    ok: bool = True
    path: str
    mode: str = "association"


class OpenFolderRequest(BaseModel):
    product_id: str = ""
    vault_folder: str = ""
    folder: str = ""


class OpenFolderResponse(BaseModel):
    ok: bool = True
    path: str


class PickFilesRequest(BaseModel):
    initial_directory: str = ""
    title: str = "Add files to the product"
    # Settings → Purgeable extensions; older .ext.N saves are omitted when set.
    purgeable_extensions: list[str] = Field(default_factory=list)
    recursive: bool = True
    # ``add`` = Creo/CAD filters; ``archive`` = *.zip first (Compressed data…).
    filter_mode: str = "add"


def _agent_purgeable_extensions(raw: list[str] | None) -> list[str]:
    """Normalize payload purgeable list; fall back to built-in defaults."""
    from creopdm.constants import DEFAULT_PURGEABLE_EXTENSIONS

    cleaned = [
        str(item).strip().lower()
        for item in (raw or [])
        if str(item or "").strip()
    ]
    return cleaned or list(DEFAULT_PURGEABLE_EXTENSIONS)


class PickFilesResponse(BaseModel):
    selected: list[str] = Field(default_factory=list)
    cancelled: bool = False
    folder: str = ""


class ExportZipRequest(BaseModel):
    pdm_url: str = ""
    product_id: str = ""
    object_ids: list[str] = Field(default_factory=list)
    folder_paths: list[str] = Field(default_factory=list)
    suggested_name: str = "export.zip"
    token: str | None = None


class ExportZipResponse(BaseModel):
    ok: bool = True
    cancelled: bool = False
    path: str = ""
    bytes_written: int = 0
    file_count: int = 0
    message: str = ""


class PushItem(BaseModel):
    object_id: str
    filename: str = ""
    relative_path: str = ""


class PushRequest(BaseModel):
    pdm_url: str = ""
    product_id: str = ""
    vault_folder: str = ""
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
    product_id: str = ""
    vault_folder: str = ""
    token: str | None = None
    relative_paths: list[str] = Field(default_factory=list)


class AddPathsRequest(BaseModel):
    """Absolute Windows paths from the native multi-select picker → product Add."""

    pdm_url: str = ""
    product_id: str = ""
    token: str | None = None
    absolute_paths: list[str] = Field(default_factory=list)
    comment: str | None = None
    # Folder pick: keep vault-relative paths under this directory.
    base_folder: str = ""
    # When true (default), vault paths start with the chosen folder name
    # (Library/part.prt). When false, paths are relative to that folder only
    # (part.prt or sub/part.prt).
    keep_root_folder: bool = True
    # Files view location on the PDM product — prefix vault paths with this.
    parent_folder: str = ""
    # Browser batch progress (for logs only).
    client_offset: int = 0
    client_total: int = 0
    # Settings → Purgeable extensions (omit older .ext.N on upload).
    purgeable_extensions: list[str] = Field(default_factory=list)


class BatchAddItem(BaseModel):
    uuid: str = ""
    filename: str = ""
    status: str = ""
    code: str = ""
    message: str = ""


class AddPathsResponse(BaseModel):
    ok: list[BatchAddItem] = Field(default_factory=list)
    failed: list[BatchAddItem] = Field(default_factory=list)


class ImportZipRequest(BaseModel):
    """Stream a local .zip to CreoPDM objects/from-zip."""

    pdm_url: str = ""
    product_id: str = ""
    token: str | None = None
    zip_path: str = ""
    parent_folder: str = ""
    comment: str | None = None


class ImportZipResponse(BaseModel):
    ok: list[BatchAddItem] = Field(default_factory=list)
    failed: list[BatchAddItem] = Field(default_factory=list)
    message: str = ""


class CacheFileInfo(BaseModel):
    relative_path: str
    filename: str
    size: int = 0
    saved_at: str = ""


class CacheFilesResponse(BaseModel):
    root: str
    files: list[CacheFileInfo] = Field(default_factory=list)


class HashPathsRequest(BaseModel):
    product_id: str = ""
    vault_folder: str = ""
    relative_paths: list[str] = Field(default_factory=list)


class HashPathResult(BaseModel):
    relative_path: str
    content_hash: str = ""
    size: int = 0
    ok: bool = True
    message: str = ""


class HashPathsResponse(BaseModel):
    files: list[HashPathResult] = Field(default_factory=list)


class DeletePathsRequest(BaseModel):
    product_id: str = ""
    vault_folder: str = ""
    relative_paths: list[str] = Field(default_factory=list)


class DeletePathsResponse(BaseModel):
    ok: list[PushItemResult] = Field(default_factory=list)
    failed: list[PushItemResult] = Field(default_factory=list)


class DeleteProductCacheRequest(BaseModel):
    product_id: str = ""
    vault_folder: str = ""


class DeleteProductCacheResponse(BaseModel):
    ok: bool = True
    deleted: bool = False
    path: str = ""
    message: str = ""


class PurgeFloor(BaseModel):
    logical_path: str = ""
    min_keep: int = 0


class PurgeVersionsRequest(BaseModel):
    product_id: str = ""
    vault_folder: str = ""
    model_extensions: list[str] = Field(default_factory=list)
    floors: list[PurgeFloor] = Field(default_factory=list)
    dry_run: bool = False


class PurgeVersionsResponse(BaseModel):
    ok: list[PushItemResult] = Field(default_factory=list)
    failed: list[PushItemResult] = Field(default_factory=list)
    deleted: int = 0


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
    if item.product_id and item.relative_path:
        rel = item.relative_path.replace("\\", "/").lstrip("/")
        name = item.disk_name or item.filename or Path(rel).name
        return (
            f"{base}/api/products/{quote(item.product_id)}/workspace/content?path={quote(rel)}",
            name,
        )
    raise HTTPException(
        status_code=400,
        detail="Provide object_id, or product_id with relative_path.",
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
    dest_rel = _cache_dest_relative(item.relative_path, disk_name)
    target = target_dir / dest_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s from CreoPDM…", dest_rel.as_posix())
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
    # write_bytes stamps "now"; restore vault mtime from Last-Modified when present.
    _apply_mtime(target, _mtime_from_http_headers(getattr(response, "headers", None)))
    # Drop legacy underscore path when vault folders used spaces ("from ptc" → "from_ptc").
    legacy_rel = _legacy_cache_dest_relative(item.relative_path, disk_name)
    if legacy_rel != dest_rel:
        legacy = target_dir / legacy_rel
        if legacy.is_file() and legacy.resolve() != target.resolve():
            try:
                move_to_trash(legacy)
                logger.info("Trashed legacy sanitized cache path %s", legacy_rel.as_posix())
            except OSError as exc:
                logger.debug("Could not trash legacy cache path %s: %s", legacy, exc)
    logger.info("Wrote %s (%s bytes) → %s", dest_rel.as_posix(), len(response.content), target)
    return target, logical, disk_name, len(response.content)


def _extract_cache_zip(
    zip_path: Path,
    target_dir: Path,
    hashes_by_name: dict[str, str] | None = None,
) -> tuple[int, int]:
    """Extract zip entries into target_dir, preserving nested vault folders."""
    target_resolved = target_dir.resolve()
    extracted = 0
    nbytes = 0
    index = _load_cache_index(target_dir)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            raw = str(info.filename or "").replace("\\", "/")
            parts = [part for part in raw.split("/") if part and part not in {".", ".."}]
            if not parts:
                continue
            safe_parts = [_safe_segment(part, "x") for part in parts]
            dest = target_dir.joinpath(*safe_parts)
            try:
                dest.resolve().relative_to(target_resolved)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsafe zip entry: {info.filename}",
                ) from exc
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = zf.read(info.filename)
            dest.write_bytes(data)
            _apply_mtime(dest, _mtime_from_zipinfo(info))
            extracted += 1
            nbytes += len(data)
            rel_key = dest.relative_to(target_dir).as_posix()
            digest = (
                (hashes_by_name or {}).get(rel_key)
                or (hashes_by_name or {}).get(dest.name)
                or (hashes_by_name or {}).get(Path(info.filename).name)
            )
            if digest:
                index[rel_key] = {"hash": digest, "size": len(data)}
                index[dest.name] = {"hash": digest, "size": len(data)}
    if hashes_by_name:
        _save_cache_index(target_dir, index)
    return extracted, nbytes


# Older tests/imports may still call the flat name.
_extract_flat_zip = _extract_cache_zip


def _load_cache_index(cache_dir: Path) -> dict[str, dict[str, object]]:
    path = cache_dir / _CACHE_INDEX_NAME
    legacy = cache_dir / _LEGACY_CACHE_INDEX_NAME
    if not path.is_file() and legacy.is_file():
        path = legacy
    if not path.is_file():
        return {}
    try:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, object]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, dict):
            out[key] = value
    return out


def _save_cache_index(cache_dir: Path, index: dict[str, dict[str, object]]) -> None:
    import json

    from creopdm.utils.files import set_hidden

    path = cache_dir / _CACHE_INDEX_NAME
    try:
        path.write_text(json.dumps(index, indent=0, sort_keys=True), encoding="utf-8")
        set_hidden(path, True)
    except OSError as exc:
        logger.warning("Could not write cache index %s: %s", path, exc)
        return
    legacy = cache_dir / _LEGACY_CACHE_INDEX_NAME
    if legacy.is_file() and legacy.resolve() != path.resolve():
        try:
            legacy.unlink()
        except OSError as exc:
            logger.warning("Could not remove legacy cache index %s: %s", legacy, exc)


def _remember_cache_file(cache_dir: Path, disk_name: str, content_hash: str, size: int) -> None:
    if not content_hash or not disk_name:
        return
    index = _load_cache_index(cache_dir)
    index[disk_name] = {"hash": content_hash, "size": int(size)}
    _save_cache_index(cache_dir, index)


def _plan_cache_downloads(
    cache_dir: Path,
    items: list[CachePlanItem],
) -> tuple[list[str], int, int]:
    """Decide which object ids need a vault download.

    Equal content_hash → skip. Local Creo save newer than vault disk_name → keep.
    """
    from creopdm.creo.file_manager import CreoFileManager
    from creopdm.utils.hashing import calculate_sha256

    index = _load_cache_index(cache_dir)
    download_ids: list[str] = []
    skipped = 0
    kept_newer = 0
    index_dirty = False

    for item in items:
        object_id = (item.object_id or "").strip()
        if not object_id:
            continue
        filename = (item.filename or item.disk_name or "").strip()
        disk_name = (item.disk_name or filename).strip()
        expected_hash = (item.content_hash or "").strip().lower()
        expected_size = int(item.file_size or 0)
        local = _find_planned_cache_file(cache_dir, item)
        if local is None or not local.is_file():
            download_ids.append(object_id)
            continue

        vault_save = CreoFileManager.save_number(disk_name, None)
        local_save = CreoFileManager.save_number(local.name, None)
        if local_save > vault_save:
            kept_newer += 1
            continue

        try:
            local_size = local.stat().st_size
        except OSError:
            download_ids.append(object_id)
            continue

        try:
            rel_key = local.resolve().relative_to(cache_dir.resolve()).as_posix()
        except ValueError:
            rel_key = local.name
        cached = index.get(rel_key) or index.get(local.name) or index.get(disk_name)
        if (
            expected_hash
            and isinstance(cached, dict)
            and str(cached.get("hash") or "").lower() == expected_hash
            and int(cached.get("size") or -1) == local_size
        ):
            # Size+remembered hash match: safe skip (content change without size change
            # still invalidates when hash was updated after a prior verify).
            skipped += 1
            continue

        # Always hash when we need a content check. Never treat "size matches"
        # alone as proof the file is unchanged (edits can preserve size).
        if expected_hash:
            try:
                digest = calculate_sha256(local).lower()
            except Exception:
                download_ids.append(object_id)
                continue
            if digest == expected_hash:
                index[rel_key] = {"hash": digest, "size": local_size}
                index[local.name] = {"hash": digest, "size": local_size}
                index_dirty = True
                skipped += 1
                continue

        download_ids.append(object_id)

    if index_dirty:
        _save_cache_index(cache_dir, index)
    return download_ids, skipped, kept_newer


def _find_planned_cache_file(cache_dir: Path, item: CachePlanItem) -> Path | None:
    """Prefer the vault-relative folder; fall back to flat / walk search."""
    from creopdm.creo.file_manager import CreoFileManager

    filename = (item.filename or item.disk_name or "").strip()
    disk_name = (item.disk_name or filename).strip()
    rel = (item.relative_path or "").replace("\\", "/").lstrip("/")
    if rel and "/" in rel:
        folder = cache_dir / Path(rel).parent
        if folder.is_dir():
            found = CreoFileManager.latest_in_directory(folder, filename or disk_name, None)
            if found is not None and found.is_file():
                return found
            exact = folder / Path(disk_name).name
            if exact.is_file():
                return exact
    return _find_cache_file(cache_dir, filename or disk_name)


def _find_cache_file(cache_dir: Path, filename: str) -> Path | None:
    """Latest Creo save (or exact name) for filename under the product cache folder.

    Searches the whole cache tree (root and subfolders) and returns the highest
    numbered save. Older flat copies and newer nested materialize can coexist.
    """
    from creopdm.creo.file_manager import CreoFileManager

    name = Path(filename or "").name.strip()
    if not name or not cache_dir.is_dir():
        return None
    wanted = CreoFileManager.logical_filename(name, None).lower()
    matches: list[Path] = []
    skip_dirs = {".git", ".creopdm", "__pycache__"}
    for dirpath, dirnames, filenames in os.walk(cache_dir):
        dirnames[:] = [item for item in dirnames if item.lower() not in skip_dirs]
        folder = Path(dirpath)
        for entry in filenames:
            if CreoFileManager.logical_filename(entry, None).lower() != wanted:
                continue
            path = folder / entry
            if path.is_file():
                matches.append(path)
    if matches:
        return CreoFileManager.select_latest_creo_version(matches, None) or matches[0]
    exact = cache_dir / name
    return exact if exact.is_file() else None


def _purge_newer_local_saves(cache_dir: Path, kept: Path) -> list[str]:
    """Trash same-logical Creo saves with a higher .N than ``kept`` under the cache.

    Used after History revert so local workspace matches the restored vault tip
    (e.g. drop start_part.prt.3 when vault tip is start_part.prt.1).
    """
    from creopdm.creo.file_manager import CreoFileManager

    if not kept.is_file() or not cache_dir.is_dir():
        return []
    try:
        kept_resolved = kept.resolve()
        cache_resolved = cache_dir.resolve()
        kept_resolved.relative_to(cache_resolved)
    except (OSError, ValueError):
        return []
    keep_num = CreoFileManager.save_number(kept.name, None)
    logical = CreoFileManager.logical_filename(kept.name, None).lower()
    if not logical:
        return []
    removed: list[str] = []
    skip_dirs = {".git", ".creopdm", "__pycache__"}
    for dirpath, dirnames, filenames in os.walk(cache_dir):
        dirnames[:] = [item for item in dirnames if item.lower() not in skip_dirs]
        folder = Path(dirpath)
        for entry in filenames:
            if CreoFileManager.logical_filename(entry, None).lower() != logical:
                continue
            if CreoFileManager.save_number(entry, None) <= keep_num:
                continue
            path = folder / entry
            try:
                resolved = path.resolve()
                resolved.relative_to(cache_resolved)
            except (OSError, ValueError):
                continue
            if resolved == kept_resolved:
                continue
            try:
                rel = resolved.relative_to(cache_resolved).as_posix()
            except ValueError:
                rel = entry
            try:
                move_to_trash(resolved)
            except OSError as exc:
                logger.warning("Could not trash newer local save %s: %s", rel, exc)
                continue
            removed.append(rel)
            logger.info("Trashed newer local save after vault replace: %s", rel)
    return removed


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
    def workdir(product_id: str = "", vault_folder: str = "") -> dict[str, str]:
        """Return (and create) the local cache folder Creo should use as WD."""
        base = settings.ensure_dirs()
        key = _product_cache_key(product_id, vault_folder)
        path = base / key
        path.mkdir(parents=True, exist_ok=True)
        return {
            "path": str(path.resolve()),
            "local_root": str(base.resolve()),
        }

    def _product_cache_dir(
        product_id: str = "",
        folder: str = "",
        vault_folder: str = "",
        *,
        create: bool = True,
    ) -> Path:
        base = settings.ensure_dirs().resolve()
        key = _product_cache_key(product_id, vault_folder)
        target = base / key
        if create:
            target.mkdir(parents=True, exist_ok=True)
        target_resolved = target.resolve()
        rel = (folder or "").replace("\\", "/").strip().strip("/")
        if rel:
            candidate = (target / Path(rel)).resolve()
            try:
                candidate.relative_to(target_resolved)
            except ValueError as exc:
                raise HTTPException(
                    status_code=403,
                    detail="Refusing to open a path outside the agent cache.",
                ) from exc
            if candidate.is_dir():
                return candidate
        return target_resolved

    @app.post("/open-folder", response_model=OpenFolderResponse)
    def open_folder(payload: OpenFolderRequest) -> OpenFolderResponse:
        """Open the local agent cache folder in Explorer (client PC, not CreoPDM server).

        Creates the product cache folder when nothing has been materialized yet.
        """
        from creopdm.utils.launch import open_windows_folder

        target = _product_cache_dir(payload.product_id, payload.folder, payload.vault_folder)
        try:
            open_windows_folder(target)
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Could not open the local workspace folder: {exc}",
            ) from exc
        logger.info("Opened local workspace folder %s", target)
        return OpenFolderResponse(path=str(target))

    @app.post("/pick-files", response_model=PickFilesResponse)
    def pick_files_endpoint(payload: PickFilesRequest) -> PickFilesResponse:
        """Native file dialog on this Creo PC (Creo filters, or archive filters)."""
        from creopdm.exceptions import ValidationAppError
        from creopdm.utils.native_dialog import pick_files

        raw = (payload.initial_directory or "").strip()
        start = Path(raw) if raw else Path.home()
        if not start.is_dir():
            start = start.parent if start.parent.is_dir() else Path.home()
        filter_mode = (payload.filter_mode or "add").strip().lower() or "add"
        title = (payload.title or "").strip() or (
            "Choose a compressed zip file"
            if filter_mode in {"archive", "zip", "compressed"}
            else "Add files to the product"
        )
        try:
            selected = pick_files(start, title=title, filter_mode=filter_mode)
        except ValidationAppError as exc:
            raise HTTPException(status_code=400, detail=exc.message) from exc
        except Exception as exc:
            logger.exception("Agent file picker failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        present = [path for path in selected if path.is_file()]
        if filter_mode in {"archive", "zip", "compressed"}:
            # One zip path — do not apply Creo numbered-save collapse.
            paths = [str(path) for path in present]
            return PickFilesResponse(selected=paths, cancelled=not paths)
        from creopdm.creo.file_manager import CreoFileManager

        purgeable = _agent_purgeable_extensions(payload.purgeable_extensions)
        try:
            latest = CreoFileManager.filter_to_latest_saves(
                present,
                purgeable,
                scan_disk_siblings=True,
            )
        except Exception:
            latest = present
        paths = [str(path) for path in latest]
        return PickFilesResponse(selected=paths, cancelled=not paths)

    @app.post("/export-zip", response_model=ExportZipResponse)
    def export_zip_endpoint(payload: ExportZipRequest) -> ExportZipResponse:
        """Ask where to save, download product/selection zip from CreoPDM, write it."""
        from creopdm.utils.native_dialog import pick_save_file

        product_id = (payload.product_id or "").strip()
        if not product_id:
            raise HTTPException(status_code=400, detail="product_id is required.")
        suggested = Path(payload.suggested_name or "export.zip").name
        if not suggested.lower().endswith(".zip"):
            suggested = f"{suggested}.zip"
        start = Path.home() / "Downloads"
        if not start.is_dir():
            start = Path.home()
        try:
            chosen = pick_save_file(
                start,
                title="Save CreoPDM export zip",
                default_name=suggested,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if chosen is None:
            return ExportZipResponse(ok=True, cancelled=True, message="Cancelled.")
        dest = Path(chosen)
        if dest.suffix.lower() != ".zip":
            dest = dest.with_suffix(".zip")
        dest.parent.mkdir(parents=True, exist_ok=True)

        base = _normalize_base(payload.pdm_url or settings.pdm_url)
        headers: dict[str, str] = {}
        token = (payload.token or settings.token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"{base}/api/products/{quote(product_id)}/export"
        body = {
            "object_ids": list(payload.object_ids or []),
            "folder_paths": list(payload.folder_paths or []),
        }
        try:
            with httpx.Client(timeout=600.0, follow_redirects=True) as client:
                response = client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not reach CreoPDM to build the export: {exc}",
            ) from exc
        if response.status_code >= 400:
            detail = ""
            try:
                payload_err = response.json()
                detail = (
                    payload_err.get("error", {}).get("message")
                    or payload_err.get("detail")
                    or response.text
                )
            except Exception:
                detail = response.text[:300]
            raise HTTPException(
                status_code=502,
                detail=detail or f"CreoPDM returned {response.status_code}",
            )
        data = response.content
        dest.write_bytes(data)
        file_count = 0
        try:
            file_count = int(response.headers.get("X-CreoPDM-File-Count") or 0)
        except ValueError:
            file_count = 0
        logger.info("Saved export zip %s (%s bytes, %s files)", dest, len(data), file_count)
        return ExportZipResponse(
            ok=True,
            path=str(dest),
            bytes_written=len(data),
            file_count=file_count,
        )

    @app.post("/pick-folder", response_model=PickFilesResponse)
    def pick_folder_endpoint(payload: PickFilesRequest) -> PickFilesResponse:
        """Native folder picker on this Creo PC; returns importable files under it."""
        from creopdm.creo.file_manager import CreoFileManager
        from creopdm.exceptions import ValidationAppError
        from creopdm.utils.native_dialog import pick_folder

        raw = (payload.initial_directory or "").strip()
        start = Path(raw) if raw else Path.home()
        if not start.is_dir():
            start = start.parent if start.parent.is_dir() else Path.home()
        title = (payload.title or "").strip() or "Add a folder to the product"
        try:
            chosen = pick_folder(start, title=title)
        except ValidationAppError as exc:
            raise HTTPException(status_code=400, detail=exc.message) from exc
        except Exception as exc:
            logger.exception("Agent folder picker failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if chosen is None:
            return PickFilesResponse(selected=[], cancelled=True)
        purgeable = _agent_purgeable_extensions(payload.purgeable_extensions)
        recursive = bool(payload.recursive)
        try:
            files = CreoFileManager.list_latest_in_folder(
                chosen, purgeable, recursive=recursive
            )
        except Exception:
            logger.exception("Listing folder for agent pick failed: %s", chosen)
            if recursive:
                files = [path for path in chosen.rglob("*") if path.is_file()]
            else:
                try:
                    files = [path for path in chosen.iterdir() if path.is_file()]
                except OSError:
                    files = []
        paths = [str(path) for path in files if path.is_file()]
        logger.info(
            "Pick folder %s → %s importable file(s) (purgeable=%s recursive=%s)",
            chosen,
            len(paths),
            len(purgeable),
            recursive,
        )
        return PickFilesResponse(selected=paths, cancelled=False, folder=str(chosen))

    @app.get("/local-file")
    def local_file(path: str = ""):
        """Read a local file the user just picked (Add upload via agent)."""
        from fastapi.responses import FileResponse

        raw = (path or "").strip()
        if not raw:
            raise HTTPException(status_code=400, detail="path is required")
        try:
            target = Path(raw).resolve()
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid path: {exc}") from exc
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"File not found: {target}")
        return FileResponse(
            path=target,
            filename=target.name,
            media_type="application/octet-stream",
        )

    @app.post("/push", response_model=PushResponse)
    def push_to_vault(payload: PushRequest) -> PushResponse:
        """Upload local agent-cache files into the CreoPDM vault working copies."""
        base = _normalize_base(payload.pdm_url or settings.pdm_url)
        product_key = _product_cache_key(payload.product_id, payload.vault_folder)
        cache_dir = root / product_key
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
                rel = (item.relative_path or "").replace("\\", "/").lstrip("/")
                local = None
                if filename or rel:
                    local = _find_planned_cache_file(
                        cache_dir,
                        CachePlanItem(
                            object_id=object_id,
                            filename=filename or Path(rel).name,
                            disk_name=filename or Path(rel).name,
                            relative_path=rel,
                        ),
                    )
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
    def list_cache_files(product_id: str = "", vault_folder: str = "") -> CacheFilesResponse:
        """List files under the product agent-cache folder (local workspace)."""
        from datetime import datetime

        from creopdm.creo.file_manager import CreoFileManager

        target = _product_cache_dir(product_id, vault_folder=vault_folder)
        files: list[CacheFileInfo] = []
        skip_dirs = {".git", ".creopdm", "__pycache__"}
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [name for name in dirnames if name.lower() not in skip_dirs]
            folder = Path(dirpath)
            for name in filenames:
                if name.startswith(".") or name.startswith("_creopdm") or CreoFileManager.is_ignored(name):
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

    @app.post("/hash-paths", response_model=HashPathsResponse)
    def hash_cache_paths(payload: HashPathsRequest) -> HashPathsResponse:
        """SHA-256 local agent-cache files (same-size content-replace detection)."""
        from creopdm.utils.hashing import calculate_sha256

        product_id = (payload.product_id or "").strip()
        if not product_id:
            raise HTTPException(status_code=400, detail="product_id is required.")
        cache_dir = _product_cache_dir(product_id, vault_folder=payload.vault_folder)
        root = cache_dir.resolve()
        results: list[HashPathResult] = []
        index = _load_cache_index(cache_dir)
        index_dirty = False
        for raw in payload.relative_paths:
            rel = str(raw or "").replace("\\", "/").lstrip("/")
            if not rel or ".." in rel.split("/"):
                results.append(
                    HashPathResult(relative_path=rel, ok=False, message="Invalid path.")
                )
                continue
            local = (cache_dir / rel).resolve()
            try:
                local.relative_to(root)
            except ValueError:
                results.append(
                    HashPathResult(
                        relative_path=rel,
                        ok=False,
                        message="Path is outside the agent cache.",
                    )
                )
                continue
            if not local.is_file():
                results.append(
                    HashPathResult(
                        relative_path=rel,
                        ok=False,
                        message=f"No local cache file found for {rel}.",
                    )
                )
                continue
            try:
                size = int(local.stat().st_size)
                digest = calculate_sha256(local).lower()
            except OSError as exc:
                results.append(
                    HashPathResult(
                        relative_path=rel,
                        ok=False,
                        message=str(exc),
                    )
                )
                continue
            index[rel] = {"hash": digest, "size": size}
            index[local.name] = {"hash": digest, "size": size}
            index_dirty = True
            results.append(
                HashPathResult(
                    relative_path=rel,
                    content_hash=digest,
                    size=size,
                    ok=True,
                )
            )
        if index_dirty:
            _save_cache_index(cache_dir, index)
        return HashPathsResponse(files=results)

    @app.post("/push-paths", response_model=PushResponse)
    def push_paths_to_vault(payload: PushPathsRequest) -> PushResponse:
        """Upload new local-cache paths into the vault (for New files / Add)."""
        base = _normalize_base(payload.pdm_url or settings.pdm_url)
        product_id = (payload.product_id or "").strip()
        if not product_id:
            raise HTTPException(status_code=400, detail="product_id is required.")
        cache_dir = _product_cache_dir(product_id, vault_folder=payload.vault_folder)
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
                        PushItemResult(object_id=product_id, filename=rel, message="Invalid path.")
                    )
                    continue
                local = (cache_dir / rel).resolve()
                try:
                    local.relative_to(cache_dir.resolve())
                except ValueError:
                    failed.append(
                        PushItemResult(
                            object_id=product_id,
                            filename=Path(rel).name,
                            message="Path is outside the agent cache.",
                        )
                    )
                    continue
                if not local.is_file():
                    failed.append(
                        PushItemResult(
                            object_id=product_id,
                            filename=Path(rel).name,
                            message=f"No local cache file found for {rel}.",
                        )
                    )
                    continue
                url = (
                    f"{base}/api/products/{quote(product_id)}/workspace-content"
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
                            object_id=product_id,
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
                            object_id=product_id,
                            filename=local.name,
                            message=detail or f"CreoPDM returned {response.status_code}",
                        )
                    )
                    continue
                nbytes = local.stat().st_size
                ok.append(
                    PushItemResult(
                        object_id=product_id,
                        filename=local.name,
                        ok=True,
                        path=str(local),
                        bytes_written=nbytes,
                        message=rel,
                    )
                )
                logger.info("Pushed new path %s → vault (%s bytes)", rel, nbytes)
        return PushResponse(ok=ok, failed=failed)

    @app.post("/add-paths", response_model=AddPathsResponse)
    def add_absolute_paths_to_product(payload: AddPathsRequest) -> AddPathsResponse:
        """Upload picked local files into the product (from-uploads), chunked.

        Used after the native multi-select picker so the browser never loads
        thousands of file bodies into memory.
        """
        from creopdm.creo.file_manager import CreoFileManager, common_import_root

        base = _normalize_base(payload.pdm_url or settings.pdm_url)
        product_id = (payload.product_id or "").strip()
        if not product_id:
            raise HTTPException(status_code=400, detail="product_id is required.")
        if not base:
            raise HTTPException(status_code=400, detail="pdm_url is required.")
        raw_paths = [str(item or "").strip() for item in payload.absolute_paths if str(item or "").strip()]
        if not raw_paths:
            return AddPathsResponse()
        present: list[Path] = []
        failed: list[BatchAddItem] = []

        def _fail(filename: str, code: str, message: str) -> None:
            item = BatchAddItem(filename=filename, code=code, message=message)
            failed.append(item)
            logger.warning("Agent add-paths failed %s [%s]: %s", filename or "(unknown)", code, message)

        for raw in raw_paths:
            path = Path(raw)
            if not path.is_file():
                _fail(path.name or raw, "NOT_FOUND", f"File not found: {raw}")
                continue
            # Keep the pick spelling for vault-relative paths. resolve() can leave
            # the chosen tree (junctions) and must not flatten to basename.
            present.append(path)
        try:
            purgeable = _agent_purgeable_extensions(payload.purgeable_extensions)
            # Disk siblings: a chunk may only list .prt.1 while .prt.4 is nearby.
            selected = CreoFileManager.filter_to_latest_saves(
                present,
                purgeable,
                scan_disk_siblings=True,
            )
        except Exception:
            selected = present
        base_raw = (payload.base_folder or "").strip()
        base_parent = Path(base_raw) if base_raw else None
        if base_parent is not None and not base_parent.is_dir():
            base_parent = None
        root = base_parent or common_import_root(selected)

        def _inner_relative(path: Path, base: Path) -> str | None:
            for file_p, root_p in (
                (path, base),
                (
                    path.resolve(),
                    base.resolve(),
                ),
            ):
                try:
                    return file_p.relative_to(root_p).as_posix()
                except (ValueError, OSError):
                    continue
            return None

        jobs: list[tuple[Path, str]] = []
        for path in selected:
            try:
                open_path = path.resolve()
            except OSError as exc:
                _fail(path.name, "IO_ERROR", f"Could not resolve path: {exc}")
                continue
            if not open_path.is_file():
                _fail(path.name, "NOT_FOUND", f"File not found: {path}")
                continue
            try:
                size = open_path.stat().st_size
            except OSError as exc:
                _fail(path.name, "IO_ERROR", f"Could not stat file: {exc}")
                continue
            if size <= 0:
                _fail(path.name, "EMPTY", "The file is empty (0 bytes) on disk.")
                continue
            if root is not None:
                inner = _inner_relative(path, root)
                if inner is None:
                    _fail(
                        path.name,
                        "OUTSIDE_BASE",
                        f"File is outside the chosen folder ({root}); skipped to avoid flattening.",
                    )
                    continue
                # Keep root: Library/sub/part.prt. Omit root: sub/part.prt.
                if payload.keep_root_folder and root.name:
                    rel = f"{root.name}/{inner}"
                else:
                    rel = inner
            else:
                rel = path.name
            parent = (payload.parent_folder or "").strip().replace("\\", "/").strip("/")
            if parent and rel != parent and not rel.startswith(f"{parent}/"):
                rel = f"{parent}/{rel}"
            jobs.append((open_path, rel))
        logger.info(
            "Agent add-paths: client %s–%s of %s; %s path(s) → %s job(s), %s failed before upload (base=%s)",
            int(payload.client_offset) + 1,
            int(payload.client_offset) + len(raw_paths),
            int(payload.client_total) or "?",
            len(raw_paths),
            len(jobs),
            len(failed),
            base_raw or "(none)",
        )
        headers: dict[str, str] = {}
        token = (payload.token or settings.token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"{base}/api/products/{quote(product_id)}/objects/from-uploads"
        ok: list[BatchAddItem] = []
        # Small chunks avoid reverse-proxy body limits on Snagit media batches.
        chunk_size = 5
        comment = (payload.comment or "").strip() or None
        with httpx.Client(timeout=600.0, follow_redirects=True) as client:
            for offset in range(0, len(jobs), chunk_size):
                chunk = jobs[offset : offset + chunk_size]
                files: list[tuple[str, tuple[str, object, str]]] = []
                data: dict[str, str] = {}
                handles: list = []
                response = None
                try:
                    for path, rel in chunk:
                        try:
                            handle = path.open("rb")
                        except OSError as exc:
                            _fail(path.name, "IO_ERROR", f"Could not read file: {exc}")
                            continue
                        handles.append(handle)
                        files.append(
                            ("files", (path.name, handle, "application/octet-stream"))
                        )
                        # httpx multipart: repeat relative_paths fields
                        files.append(("relative_paths", (None, rel)))
                    if not files:
                        logger.warning(
                            "Agent add-paths chunk %s–%s: nothing readable to upload",
                            offset + 1,
                            offset + len(chunk),
                        )
                        continue
                    if comment and offset == 0:
                        data["comment"] = comment
                    try:
                        response = client.post(url, headers=headers, data=data or None, files=files)
                    except httpx.HTTPError as exc:
                        message = f"Could not reach CreoPDM: {exc}"
                        logger.warning(
                            "Agent add-paths chunk %s–%s NETWORK: %s",
                            offset + 1,
                            offset + len(chunk),
                            message,
                        )
                        for path, _rel in chunk:
                            failed.append(
                                BatchAddItem(
                                    filename=path.name,
                                    code="NETWORK",
                                    message=message,
                                )
                            )
                        continue
                finally:
                    for handle in handles:
                        try:
                            handle.close()
                        except OSError:
                            pass
                if response is None:
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
                    message = detail or f"CreoPDM returned {response.status_code}"
                    logger.warning(
                        "Agent add-paths chunk %s–%s HTTP %s: %s",
                        offset + 1,
                        offset + len(chunk),
                        response.status_code,
                        message,
                    )
                    for path, _rel in chunk:
                        failed.append(
                            BatchAddItem(
                                filename=path.name,
                                code="HTTP_ERROR",
                                message=message,
                            )
                        )
                    continue
                try:
                    body = response.json()
                except Exception:
                    logger.warning(
                        "Agent add-paths chunk %s–%s: invalid JSON from CreoPDM",
                        offset + 1,
                        offset + len(chunk),
                    )
                    for path, _rel in chunk:
                        failed.append(
                            BatchAddItem(
                                filename=path.name,
                                code="BAD_RESPONSE",
                                message="CreoPDM returned an invalid response.",
                            )
                        )
                    continue
                for item in body.get("ok") or []:
                    ok.append(
                        BatchAddItem(
                            uuid=str(item.get("uuid") or ""),
                            filename=str(item.get("filename") or ""),
                            status=str(item.get("status") or "added"),
                        )
                    )
                for item in body.get("failed") or []:
                    fail_item = BatchAddItem(
                        uuid=str(item.get("uuid") or ""),
                        filename=str(item.get("filename") or ""),
                        code=str(item.get("code") or "FAILED"),
                        message=str(item.get("message") or "The file was not added."),
                    )
                    failed.append(fail_item)
                    logger.warning(
                        "Agent add-paths failed %s [%s]: %s",
                        fail_item.filename or "(unknown)",
                        fail_item.code,
                        fail_item.message,
                    )
                logger.info(
                    "Agent add-paths chunk %s–%s → ok=%s failed=%s",
                    offset + 1,
                    offset + len(chunk),
                    len(body.get("ok") or []),
                    len(body.get("failed") or []),
                )
        # Summarize codes for the agent log (and UI via returned failed list).
        by_code: dict[str, int] = {}
        for item in failed:
            key = (item.code or "FAILED").strip() or "FAILED"
            by_code[key] = by_code.get(key, 0) + 1
        summary = ", ".join(f"{code}={count}" for code, count in sorted(by_code.items())) or "none"
        logger.info(
            "Agent add-paths done: ok=%s failed=%s (%s)",
            len(ok),
            len(failed),
            summary,
        )
        return AddPathsResponse(ok=ok, failed=failed)

    @app.post("/import-zip", response_model=ImportZipResponse)
    def import_zip_to_product(payload: ImportZipRequest) -> ImportZipResponse:
        """Upload a local .zip to CreoPDM from-zip (server extracts and imports)."""
        from creopdm.exceptions import ValidationAppError
        from creopdm.utils.zip_import import MAX_ZIP_IMPORT_BYTES, assert_zip_filename

        base = _normalize_base(payload.pdm_url or settings.pdm_url)
        product_id = (payload.product_id or "").strip()
        if not product_id:
            raise HTTPException(status_code=400, detail="product_id is required.")
        if not base:
            raise HTTPException(status_code=400, detail="pdm_url is required.")
        raw = (payload.zip_path or "").strip()
        if not raw:
            raise HTTPException(status_code=400, detail="zip_path is required.")
        path = Path(raw)
        if not path.is_file():
            raise HTTPException(status_code=400, detail=f"Zip not found: {raw}")
        try:
            filename = assert_zip_filename(path.name)
        except ValidationAppError as exc:
            raise HTTPException(status_code=400, detail=exc.message) from exc
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"Could not read zip: {exc}") from exc
        if size <= 0:
            raise HTTPException(status_code=400, detail="The zip file is empty.")
        if size > MAX_ZIP_IMPORT_BYTES:
            raise HTTPException(
                status_code=400,
                detail="That zip is larger than the 2 GB limit.",
            )
        headers: dict[str, str] = {}
        token = (payload.token or settings.token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"{base}/api/products/{quote(product_id)}/objects/from-zip"
        parent = (payload.parent_folder or "").strip().replace("\\", "/").strip("/")
        data: dict[str, str] = {}
        if parent:
            data["parent_folder"] = parent
        comment = (payload.comment or "").strip()
        if comment:
            data["comment"] = comment
        zip_timeout = httpx.Timeout(connect=30.0, read=3600.0, write=3600.0, pool=30.0)
        try:
            with path.open("rb") as handle:
                files = {
                    "file": (filename, handle, "application/zip"),
                }
                with httpx.Client(timeout=zip_timeout, follow_redirects=True) as client:
                    response = client.post(
                        url,
                        headers=headers,
                        data=data or None,
                        files=files,
                    )
        except httpx.HTTPError as exc:
            logger.warning("Agent import-zip NETWORK: %s", exc)
            raise HTTPException(
                status_code=502,
                detail=f"Could not reach CreoPDM: {exc}",
            ) from exc
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
            message = detail or f"CreoPDM returned {response.status_code}"
            logger.warning("Agent import-zip HTTP %s: %s", response.status_code, message)
            raise HTTPException(status_code=400, detail=message)
        try:
            body = response.json()
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="CreoPDM returned invalid JSON after zip import.",
            ) from exc
        ok = [
            BatchAddItem(
                uuid=str(item.get("uuid") or ""),
                filename=str(item.get("filename") or ""),
                status=str(item.get("status") or "added"),
            )
            for item in (body.get("ok") or [])
            if isinstance(item, dict)
        ]
        failed = [
            BatchAddItem(
                uuid=str(item.get("uuid") or ""),
                filename=str(item.get("filename") or ""),
                code=str(item.get("code") or ""),
                message=str(item.get("message") or ""),
            )
            for item in (body.get("failed") or [])
            if isinstance(item, dict)
        ]
        logger.info(
            "Agent import-zip done: ok=%s failed=%s (%s)",
            len(ok),
            len(failed),
            path.name,
        )
        return ImportZipResponse(ok=ok, failed=failed)

    @app.post("/delete-paths", response_model=DeletePathsResponse)
    def delete_cache_paths(payload: DeletePathsRequest) -> DeletePathsResponse:
        """Delete files from the local agent cache (discard New file local rows).

        Each path also removes Creo numbered siblings in the same folder
        (``shaft.prt`` → ``shaft.prt.1``, ``shaft.prt.2``, …) so the UI does not
        need to list the whole cache before Remove.
        """
        from creopdm.creo.file_manager import CreoFileManager

        product_id = (payload.product_id or "").strip()
        if not product_id:
            raise HTTPException(status_code=400, detail="product_id is required.")
        cache_dir = _product_cache_dir(product_id, vault_folder=payload.vault_folder)
        cache_resolved = cache_dir.resolve()
        ok: list[PushItemResult] = []
        failed: list[PushItemResult] = []
        seen: set[str] = set()

        def trash_one(local: Path, rel_label: str) -> None:
            key = str(local.resolve()).casefold()
            if key in seen:
                return
            seen.add(key)
            if not local.is_file():
                failed.append(
                    PushItemResult(
                        object_id=product_id,
                        filename=Path(rel_label).name,
                        message=f"No local cache file found for {rel_label}.",
                    )
                )
                return
            try:
                move_to_trash(local)
            except OSError as exc:
                failed.append(
                    PushItemResult(
                        object_id=product_id,
                        filename=local.name,
                        message=str(exc),
                    )
                )
                return
            try:
                rel_out = str(local.resolve().relative_to(cache_resolved)).replace("\\", "/")
            except ValueError:
                rel_out = rel_label
            ok.append(
                PushItemResult(
                    object_id=product_id,
                    filename=local.name,
                    ok=True,
                    path=str(local),
                    message=rel_out,
                )
            )
            logger.info("Moved local cache path to trash %s", rel_out)

        for raw in payload.relative_paths:
            rel = str(raw or "").replace("\\", "/").lstrip("/")
            if not rel or ".." in rel.split("/"):
                failed.append(
                    PushItemResult(object_id=product_id, filename=rel, message="Invalid path.")
                )
                continue
            local = (cache_dir / rel).resolve()
            try:
                local.relative_to(cache_resolved)
            except ValueError:
                failed.append(
                    PushItemResult(
                        object_id=product_id,
                        filename=Path(rel).name,
                        message="Path is outside the agent cache.",
                    )
                )
                continue
            parent = local.parent
            wanted = CreoFileManager.logical_filename(local.name).lower()
            siblings: list[Path] = []
            if parent.is_dir() and wanted:
                for path in parent.iterdir():
                    if not path.is_file():
                        continue
                    if CreoFileManager.logical_filename(path.name).lower() == wanted:
                        siblings.append(path)
            if not siblings and local.is_file():
                siblings = [local]
            if not siblings:
                failed.append(
                    PushItemResult(
                        object_id=product_id,
                        filename=Path(rel).name,
                        message=f"No local cache file found for {rel}.",
                    )
                )
                continue
            for path in siblings:
                trash_one(path, rel)
        return DeletePathsResponse(ok=ok, failed=failed)

    @app.post("/delete-product-cache", response_model=DeleteProductCacheResponse)
    def delete_product_cache(payload: DeleteProductCacheRequest) -> DeleteProductCacheResponse:
        """Remove the whole local agent-cache folder for a product (Recycle Bin when possible).

        May fail while Creo still has files open or its working directory is that folder.
        """
        product_id = (payload.product_id or "").strip()
        vault_folder = (payload.vault_folder or "").strip()
        if not product_id and not vault_folder:
            raise HTTPException(status_code=400, detail="product_id or vault_folder is required.")
        cache_dir = _product_cache_dir(product_id, vault_folder=vault_folder, create=False)
        root_resolved = settings.ensure_dirs().resolve()
        try:
            cache_dir.resolve().relative_to(root_resolved)
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail="Refusing to delete a path outside the agent cache.",
            ) from exc
        if cache_dir.resolve() == root_resolved:
            raise HTTPException(status_code=400, detail="Refusing to delete the agent cache root.")
        if not cache_dir.exists():
            return DeleteProductCacheResponse(
                ok=True,
                deleted=False,
                path=str(cache_dir),
                message="Local workspace folder was already gone.",
            )
        try:
            move_to_trash(cache_dir)
        except OSError as exc:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Could not delete the local workspace. Close open files in Creo "
                    f"(and change Creo's working directory if it still points here): {exc}"
                ),
            ) from exc
        if cache_dir.exists():
            raise HTTPException(
                status_code=409,
                detail=(
                    "Could not delete the local workspace. Close open files in Creo "
                    "or change Creo's working directory away from this folder, then try again."
                ),
            )
        logger.info("Deleted local product cache %s", cache_dir)
        return DeleteProductCacheResponse(
            ok=True,
            deleted=True,
            path=str(cache_dir),
            message="Local workspace moved to the Recycle Bin.",
        )

    @app.post("/purge-versions", response_model=PurgeVersionsResponse)
    def purge_older_versions(payload: PurgeVersionsRequest) -> PurgeVersionsResponse:
        """Delete local cache saves strictly older than vault floors (keep == and >)."""
        from creopdm.constants import DEFAULT_CREO_MODEL_EXTENSIONS
        from creopdm.creo.file_manager import CreoFileManager

        product_id = (payload.product_id or "").strip()
        if not product_id:
            raise HTTPException(status_code=400, detail="product_id is required.")
        cache_dir = _product_cache_dir(product_id, vault_folder=payload.vault_folder)
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
                        object_id=product_id,
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
                        object_id=product_id,
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
                        object_id=product_id,
                        filename=resolved.name,
                        message=str(exc),
                    )
                )
                continue
            ok.append(
                PushItemResult(
                    object_id=product_id,
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
            product_id=payload.product_id,
            relative_path=payload.relative_path,
            filename=payload.filename,
            disk_name=payload.disk_name,
        )
        product_key = _product_cache_key(
            payload.product_id or payload.object_id or "local",
            payload.vault_folder,
        )
        target_dir = root / product_key
        target_dir.mkdir(parents=True, exist_ok=True)
        headers: dict[str, str] = {}
        token = (payload.token or settings.token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        logger.info(
            "Materialize start: %s (+%s companion request%s) → %s",
            primary.disk_name or primary.filename or primary.object_id,
            len(payload.companions),
            "" if len(payload.companions) == 1 else "s",
            target_dir,
        )
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            target, logical, disk_name, nbytes = _download(
                client, base, primary, target_dir, headers
            )
            companions_written = 0
            for item in payload.companions:
                if not item.object_id and not (item.product_id and item.relative_path):
                    continue
                logger.info(
                    "Downloading companion %s…",
                    item.disk_name or item.filename or item.object_id,
                )
                _download(client, base, item, target_dir, headers)
                companions_written += 1
        purged_newer: list[str] = []
        if payload.replace_newer:
            purged_newer = _purge_newer_local_saves(target_dir, target)
            logger.info(
                "replace_newer: kept %s, trashed %s newer local save(s)",
                disk_name,
                len(purged_newer),
            )
        logger.info(
            "Materialize done: %s ready for Creo (%s bytes, %s companion%s) in %s — "
            "metadata save happens on the CreoPDM server after Creo.JS gather, not in the agent",
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
            purged_newer=purged_newer,
        )

    @app.post("/materialize-zip", response_model=MaterializeZipResponse)
    def materialize_zip(payload: MaterializeZipRequest) -> MaterializeZipResponse:
        base = _normalize_base(payload.pdm_url or settings.pdm_url)
        product_key = _product_cache_key(payload.product_id, payload.vault_folder)
        target_dir = root / product_key
        target_dir.mkdir(parents=True, exist_ok=True)
        headers: dict[str, str] = {}
        token = (payload.token or settings.token or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        zip_timeout = httpx.Timeout(connect=30.0, read=3600.0, write=30.0, pool=30.0)
        manifest_url = f"{base}/api/objects/batch/agent-cache-manifest"
        archive_url = f"{base}/api/objects/batch/agent-cache-archive"

        with httpx.Client(timeout=zip_timeout, follow_redirects=True) as client:
            try:
                manifest_response = client.post(
                    manifest_url,
                    json={"object_ids": payload.object_ids},
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Could not fetch cache manifest from CreoPDM: {exc}",
                ) from exc
            if manifest_response.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=f"CreoPDM manifest returned {manifest_response.status_code}",
                )
            try:
                manifest_body = manifest_response.json()
            except Exception as exc:
                raise HTTPException(status_code=502, detail="Invalid cache manifest.") from exc
            raw_items = manifest_body.get("items") if isinstance(manifest_body, dict) else None
            items = [
                CachePlanItem(
                    object_id=str(item.get("object_id") or ""),
                    filename=str(item.get("filename") or ""),
                    disk_name=str(item.get("disk_name") or ""),
                    relative_path=str(item.get("relative_path") or ""),
                    content_hash=str(item.get("content_hash") or ""),
                    file_size=int(item.get("file_size") or 0),
                )
                for item in (raw_items or [])
                if isinstance(item, dict)
            ]
            download_ids, skipped, kept_newer = _plan_cache_downloads(target_dir, items)
            if not download_ids:
                logger.info(
                    "Agent cache up to date (%s skipped, %s kept newer) → %s",
                    skipped,
                    kept_newer,
                    target_dir,
                )
                return MaterializeZipResponse(
                    working_directory=str(target_dir.resolve()),
                    extracted_count=0,
                    bytes_written=0,
                    skipped_count=skipped,
                    kept_newer_count=kept_newer,
                    download_count=0,
                )

            download_set = set(download_ids)
            hashes_by_name: dict[str, str] = {}
            for item in items:
                if item.object_id not in download_set or not item.content_hash:
                    continue
                if item.disk_name:
                    hashes_by_name[item.disk_name] = item.content_hash
                dest_rel = _cache_dest_relative(item.relative_path, item.disk_name or item.filename)
                hashes_by_name[dest_rel.as_posix()] = item.content_hash
            fd, raw_tmp = tempfile.mkstemp(suffix=".zip", prefix="creopdm-agent-")
            os.close(fd)
            zip_path = Path(raw_tmp)
            try:
                with client.stream(
                    "POST",
                    archive_url,
                    json={"object_ids": download_ids},
                    headers=headers,
                ) as response:
                    if response.status_code >= 400:
                        detail = ""
                        try:
                            detail = response.read().decode("utf-8", errors="replace")[:500]
                        except Exception:
                            detail = f"CreoPDM returned {response.status_code}"
                        raise HTTPException(
                            status_code=502,
                            detail=detail or f"CreoPDM returned {response.status_code}",
                        )
                    with zip_path.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
                extracted, nbytes = _extract_cache_zip(zip_path, target_dir, hashes_by_name)
            except httpx.HTTPError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Could not download archive from CreoPDM: {exc}",
                ) from exc
            finally:
                zip_path.unlink(missing_ok=True)

        logger.info(
            "Materialized zip (%s downloaded, %s skipped, %s kept newer, %s bytes) → %s",
            extracted,
            skipped,
            kept_newer,
            nbytes,
            target_dir,
        )
        return MaterializeZipResponse(
            working_directory=str(target_dir.resolve()),
            extracted_count=extracted,
            bytes_written=nbytes,
            skipped_count=skipped,
            kept_newer_count=kept_newer,
            download_count=len(download_ids),
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
