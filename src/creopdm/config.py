"""Application configuration manager.

Settings live in the application data directory, not in project Git repositories.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from creopdm.constants import (
    APP_NAME,
    CREO_OPEN_MODES,
    CREO_VIEW_OPEN_MODES,
    DEFAULT_CAD_MODELS_EXTENSIONS,
    DEFAULT_CREO_MODEL_EXTENSIONS,
    DEFAULT_DOCUMENT_EXTENSIONS,
    DEFAULT_EXTRA_CAD_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
    DEFAULT_LFS_PATTERNS,
    DEFAULT_OPENABLE_CAD_EXTENSIONS,
    DEFAULT_TYPE_LABELS,
    PREVIOUS_DEFAULT_CREO_MODEL_SETS,
    PREVIOUS_DEFAULT_DOCUMENT_SETS,
    PREVIOUS_DEFAULT_EXTRA_CAD_SETS,
    PREVIOUS_DEFAULT_IGNORE_SETS,
    PREVIOUS_DEFAULT_TYPE_LABEL_SETS,
)
from creopdm.exceptions import ConfigurationError, PathValidationError
from creopdm.utils.classify import (
    exclude_extensions,
    extra_cad_set,
    parse_extension_text,
    unique_extensions,
    unique_type_labels,
)
from creopdm.utils.ignore import parse_ignore_text, unique_ignore_patterns


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 0

    @field_validator("host")
    @classmethod
    def default_all_interfaces(cls, value: str) -> str:
        return value.strip() or "0.0.0.0"

    @field_validator("port")
    @classmethod
    def valid_port(cls, value: int) -> int:
        if not 0 <= int(value) <= 65535:
            raise ValueError("Port must be 0 (automatic) or 1–65535.")
        return int(value)


class GitConfig(BaseModel):
    executable: str = "git"
    lfs_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_LFS_PATTERNS))


class CreoConfig(BaseModel):
    connector: str = "auto"
    executable: str | None = None
    open_mode: str = "executable"
    view_executable: str | None = None
    view_open_mode: str = "executable"

    @field_validator("open_mode")
    @classmethod
    def valid_open_mode(cls, value: str) -> str:
        key = (value or "executable").strip().lower()
        if key not in CREO_OPEN_MODES:
            return "executable"
        return key

    @field_validator("view_open_mode")
    @classmethod
    def valid_view_open_mode(cls, value: str) -> str:
        key = (value or "executable").strip().lower()
        if key not in CREO_VIEW_OPEN_MODES:
            return "executable"
        return key


class DatabaseConfig(BaseModel):
    url: str = ""

    @field_validator("url")
    @classmethod
    def empty_or_sqlalchemy_url(cls, value: str) -> str:
        text = (value or "").strip()
        if not text:
            return ""
        if "://" not in text:
            raise ValueError(
                "Database URL must look like sqlite:///path or postgresql+psycopg://user@host/db"
            )
        return text


class WorkspaceConfig(BaseModel):
    root: str | None = None


class UiConfig(BaseModel):
    open_browser_on_start: bool = True
    last_project_uuid: str | None = None
    project_folders: dict[str, str] = Field(default_factory=dict)


def _normalize_extension_list(value: object, default: tuple[str, ...] | list[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, str):
        return parse_extension_text(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return unique_extensions(str(item) for item in value)
    return list(default)


class CadConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_CREO_MODEL_EXTENSIONS))
    cad_models_extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_CAD_MODELS_EXTENSIONS))
    document_extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_DOCUMENT_EXTENSIONS))
    openable_extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_OPENABLE_CAD_EXTENSIONS))
    extra_extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_EXTRA_CAD_EXTENSIONS))
    type_labels: list[dict[str, str]] = Field(
        default_factory=lambda: unique_type_labels(DEFAULT_TYPE_LABELS)
    )

    @field_validator("model_extensions", mode="before")
    @classmethod
    def normalize_model_extensions(cls, value: object) -> list[str]:
        return _normalize_extension_list(value, DEFAULT_CREO_MODEL_EXTENSIONS)

    @field_validator("cad_models_extensions", mode="before")
    @classmethod
    def normalize_cad_models_extensions(cls, value: object) -> list[str]:
        return _normalize_extension_list(value, DEFAULT_CAD_MODELS_EXTENSIONS)

    @field_validator("document_extensions", mode="before")
    @classmethod
    def normalize_document_extensions(cls, value: object) -> list[str]:
        return _normalize_extension_list(value, DEFAULT_DOCUMENT_EXTENSIONS)

    @field_validator("openable_extensions", mode="before")
    @classmethod
    def normalize_openable_extensions(cls, value: object) -> list[str]:
        return _normalize_extension_list(value, DEFAULT_OPENABLE_CAD_EXTENSIONS)

    @field_validator("extra_extensions", mode="before")
    @classmethod
    def normalize_extra_extensions(cls, value: object) -> list[str]:
        return _normalize_extension_list(value, DEFAULT_EXTRA_CAD_EXTENSIONS)

    @field_validator("type_labels", mode="before")
    @classmethod
    def normalize_type_labels(cls, value: object) -> list[dict[str, str]]:
        return unique_type_labels(value)

    @model_validator(mode="after")
    def extras_exclude_openable_models(self) -> CadConfig:
        self.openable_extensions = exclude_extensions(self.openable_extensions, self.model_extensions)
        self.extra_extensions = exclude_extensions(
            self.extra_extensions,
            (*self.model_extensions, *self.openable_extensions),
        )
        return self


class IgnoreConfig(BaseModel):
    patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_IGNORE_PATTERNS))

    @field_validator("patterns", mode="before")
    @classmethod
    def normalize_patterns(cls, value: object) -> list[str]:
        if value is None:
            return list(DEFAULT_IGNORE_PATTERNS)
        if isinstance(value, str):
            return parse_ignore_text(value)
        if isinstance(value, (list, tuple, set, frozenset)):
            return unique_ignore_patterns(str(item) for item in value)
        return list(DEFAULT_IGNORE_PATTERNS)


class AppSettings(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    creo: CreoConfig = Field(default_factory=CreoConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    cad: CadConfig = Field(default_factory=CadConfig)
    ignore: IgnoreConfig = Field(default_factory=IgnoreConfig)


_ADDED_DEFAULT_TYPE_LABELS = (
    "reviewref.inf",
    ".mrd",
    "mw_settings.xml",
    "mc_error.log",
    ".tmp",
    ".crc",
    ".css, .scss, .sass, .less",
    ".js, .mjs, .cjs, .jsx, .ts, .tsx",
    ".eda",
    ".mcdx",
    ".spro",
    ".rcp",
    ".mbx",
    ".lst",
    ".ncl.tl*",
    ".aux",
    ".cel",
    ".dat",
    ".edm",
    ".inf",
    ".memb",
    ".mtn",
    ".ncd",
    ".nck",
    ".plt",
    ".ppl",
    ".ptd",
    ".shd",
    ".sit",
    ".smt",
    ".docm, .dot, .dotx, .dotm",
    ".odt, .ott, .pages, .wpd",
    ".xlsm, .xlsb, .xlt, .xltx, .xltm",
    ".ods, .numbers",
    ".pptm, .pps, .ppsx, .pot, .potx",
    ".odp, .key",
    ".vsd, .vsdx, .vss, .vstx",
    ".msg, .eml, .oft",
    ".epub, .mobi",
    ".xps, .oxps",
    ".ps",
    ".yaml, .yml",
    ".toml",
    ".markdown, .rst, .adoc",
    ".xhtml, .mhtml",
    ".tsv",
    ".pub",
    ".one, .onepkg",
    ".mpt",
    ".tex, .ltx, .bib",
    ".odg",
    ".psd",
)


def _type_label_fingerprint(values: object) -> tuple[tuple[str, str], ...]:
    return tuple((item["extension"], item["label"]) for item in unique_type_labels(values))


def _previous_type_label_fingerprints() -> set[tuple[tuple[str, str], ...]]:
    found: set[tuple[tuple[str, str], ...]] = set(PREVIOUS_DEFAULT_TYPE_LABEL_SETS)
    skip: set[str] = set()
    for key in reversed(_ADDED_DEFAULT_TYPE_LABELS):
        skip.add(key)
        found.add(
            _type_label_fingerprint(
                item for item in DEFAULT_TYPE_LABELS if item["extension"] not in skip
            )
        )
    return found


def data_dir_from_environment() -> Path:
    """Resolve the application data directory.

    Override with CREOPDM_DATA_DIR for tests. Default is %LOCALAPPDATA%\\CreoPDM\\.
    """
    override = os.environ.get("CREOPDM_DATA_DIR")
    if override:
        return Path(override).expanduser()
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        return Path(local_app) / APP_NAME
    return Path.home() / "AppData" / "Local" / APP_NAME


class ConfigManager:
    """Loads, persists, and ensures the application data directory layout."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = (data_dir or data_dir_from_environment()).resolve()
        self.config_dir = self.data_dir / "config"
        self.database_dir = self.data_dir / "database"
        self.logs_dir = self.data_dir / "logs"
        self.cache_dir = self.data_dir / "cache"
        self.workspaces_dir = self.data_dir / "workspaces"
        self.temp_dir = self.data_dir / "temp"
        self.settings_path = self.config_dir / "settings.json"
        self.database_path = self.database_dir / "creopdm.db"
        self.log_path = self.logs_dir / "creopdm.log"
        self._settings: AppSettings | None = None

    def ensure_layout(self) -> None:
        for directory in (
            self.data_dir,
            self.config_dir,
            self.database_dir,
            self.logs_dir,
            self.cache_dir,
            self.workspaces_dir,
            self.temp_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppSettings:
        self.ensure_layout()
        if not self.settings_path.exists():
            settings = AppSettings()
            self.save(settings)
            self._settings = settings
            return settings
        try:
            raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
            settings = AppSettings.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ConfigurationError(f"Unable to read settings: {exc}") from exc
        dirty = False
        cad_raw = raw.get("cad") if isinstance(raw, dict) else None
        raw_extras = extra_cad_set((cad_raw or {}).get("extra_extensions")) if isinstance(cad_raw, dict) else extra_cad_set()
        if raw_extras in PREVIOUS_DEFAULT_EXTRA_CAD_SETS:
            settings.cad.extra_extensions = list(DEFAULT_EXTRA_CAD_EXTENSIONS)
            settings.cad.openable_extensions = list(DEFAULT_OPENABLE_CAD_EXTENSIONS)
            dirty = True
        raw_models = extra_cad_set((cad_raw or {}).get("model_extensions")) if isinstance(cad_raw, dict) else extra_cad_set()
        if raw_models in PREVIOUS_DEFAULT_CREO_MODEL_SETS:
            settings.cad.model_extensions = list(DEFAULT_CREO_MODEL_EXTENSIONS)
            dirty = True
        if not isinstance(cad_raw, dict) or "openable_extensions" not in cad_raw:
            settings.cad.openable_extensions = list(DEFAULT_OPENABLE_CAD_EXTENSIONS)
            dirty = True
        if not isinstance(cad_raw, dict) or "model_extensions" not in cad_raw:
            settings.cad.model_extensions = list(DEFAULT_CREO_MODEL_EXTENSIONS)
            dirty = True
        if not isinstance(cad_raw, dict) or "cad_models_extensions" not in cad_raw:
            settings.cad.cad_models_extensions = list(DEFAULT_CAD_MODELS_EXTENSIONS)
            dirty = True
        if not isinstance(cad_raw, dict) or "document_extensions" not in cad_raw:
            settings.cad.document_extensions = list(DEFAULT_DOCUMENT_EXTENSIONS)
            dirty = True
        raw_docs = (
            extra_cad_set((cad_raw or {}).get("document_extensions"))
            if isinstance(cad_raw, dict)
            else extra_cad_set()
        )
        if raw_docs in PREVIOUS_DEFAULT_DOCUMENT_SETS:
            settings.cad.document_extensions = list(DEFAULT_DOCUMENT_EXTENSIONS)
            dirty = True
        stripped_openable = exclude_extensions(settings.cad.openable_extensions, settings.cad.model_extensions)
        if stripped_openable != unique_extensions(settings.cad.openable_extensions):
            settings.cad.openable_extensions = stripped_openable
            dirty = True
        stripped = exclude_extensions(
            settings.cad.extra_extensions,
            (*settings.cad.model_extensions, *settings.cad.openable_extensions),
        )
        if stripped != unique_extensions(settings.cad.extra_extensions):
            settings.cad.extra_extensions = stripped
            dirty = True
        raw_labels = (cad_raw or {}).get("type_labels") if isinstance(cad_raw, dict) else None
        label_fp = _type_label_fingerprint(raw_labels)
        if (
            not isinstance(cad_raw, dict)
            or "type_labels" not in cad_raw
            or label_fp in _previous_type_label_fingerprints()
        ):
            settings.cad.type_labels = unique_type_labels(DEFAULT_TYPE_LABELS)
            dirty = True
        if settings.server.host in {"127.0.0.1", "localhost"}:
            settings.server.host = "0.0.0.0"
            dirty = True
        if "database" not in raw:
            dirty = True
        ignore_raw = raw.get("ignore") if isinstance(raw, dict) else None
        raw_ignore = frozenset(
            str(item).strip().lower()
            for item in ((ignore_raw or {}).get("patterns") or [])
            if str(item).strip()
        ) if isinstance(ignore_raw, dict) else frozenset()
        if "ignore" not in raw or raw_ignore in PREVIOUS_DEFAULT_IGNORE_SETS:
            settings.ignore.patterns = list(DEFAULT_IGNORE_PATTERNS)
            dirty = True
        if dirty:
            self.save(settings)
        self._settings = settings
        return settings

    def save(self, settings: AppSettings) -> None:
        self.ensure_layout()
        payload: dict[str, Any] = settings.model_dump()
        self.settings_path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        self._settings = settings

    @property
    def settings(self) -> AppSettings:
        if self._settings is None:
            return self.load()
        return self._settings

    def default_sqlite_url(self) -> str:
        path = self.database_path.resolve().as_posix()
        return f"sqlite:///{path}"

    def database_url(self) -> str:
        env = (os.environ.get("CREOPDM_DATABASE_URL") or "").strip()
        if env:
            return env
        configured = (self.settings.database.url or "").strip()
        if configured:
            return configured
        return self.default_sqlite_url()

    def workspace_root(self) -> Path:
        configured = (self.settings.workspace.root or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
        return self.workspaces_dir

    def model_cad_extensions(self) -> list[str]:
        return unique_extensions(self.settings.cad.model_extensions or DEFAULT_CREO_MODEL_EXTENSIONS)

    def cad_models_extensions(self) -> list[str]:
        configured = self.settings.cad.cad_models_extensions
        if not configured:
            return list(DEFAULT_CAD_MODELS_EXTENSIONS)
        return unique_extensions(configured)

    def document_extensions(self) -> list[str]:
        configured = self.settings.cad.document_extensions
        if not configured:
            return list(DEFAULT_DOCUMENT_EXTENSIONS)
        return unique_extensions(configured)

    def openable_cad_extensions(self) -> list[str]:
        return exclude_extensions(self.settings.cad.openable_extensions, self.model_cad_extensions())

    def extra_cad_extensions(self) -> list[str]:
        return exclude_extensions(
            self.settings.cad.extra_extensions,
            (*self.model_cad_extensions(), *self.openable_cad_extensions()),
        )

    def data_cad_extensions(self) -> list[str]:
        return unique_extensions((*self.openable_cad_extensions(), *self.extra_cad_extensions()))

    def all_cad_extensions(self) -> list[str]:
        return unique_extensions((*self.model_cad_extensions(), *self.data_cad_extensions()))

    def type_labels(self) -> list[dict[str, str]]:
        return unique_type_labels(self.settings.cad.type_labels)

    def ignore_patterns(self) -> list[str]:
        configured = self.settings.ignore.patterns
        if configured is None:
            return list(DEFAULT_IGNORE_PATTERNS)
        return unique_ignore_patterns(configured)

    def workspace_for_project(self, project_uuid: str) -> Path:
        if not project_uuid or any(ch in project_uuid for ch in r"/\:"):
            raise PathValidationError("Invalid project identifier for workspace path.")
        root = self.workspace_root()
        root.mkdir(parents=True, exist_ok=True)
        return root / project_uuid

    def remember_project(self, project_uuid: str | None) -> None:
        uuid_value = (project_uuid or "").strip() or None
        settings = self.settings
        if settings.ui.last_project_uuid == uuid_value:
            return
        settings.ui.last_project_uuid = uuid_value
        self.save(settings)

    def remembered_folder(self, project_uuid: str) -> str:
        from creopdm.utils.folders import normalize_folder_query

        return normalize_folder_query(self.settings.ui.project_folders.get(project_uuid, ""))

    def remember_folder(self, project_uuid: str, folder: str) -> None:
        from creopdm.utils.folders import normalize_folder_query

        uuid_value = (project_uuid or "").strip()
        if not uuid_value:
            return
        folder = normalize_folder_query(folder)
        settings = self.settings
        current = dict(settings.ui.project_folders)
        stored = current.get(uuid_value, "")
        if stored == folder:
            return
        if folder:
            current[uuid_value] = folder
        else:
            current.pop(uuid_value, None)
        settings.ui.project_folders = current
        self.save(settings)

    def forget_project_view(self, project_uuid: str) -> None:
        uuid_value = (project_uuid or "").strip()
        if not uuid_value:
            return
        settings = self.settings
        current = dict(settings.ui.project_folders)
        if uuid_value not in current:
            return
        current.pop(uuid_value, None)
        settings.ui.project_folders = current
        self.save(settings)
