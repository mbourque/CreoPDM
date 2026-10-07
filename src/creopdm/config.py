"""Application configuration manager.

Settings live in the application data directory, not in product Git repositories.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

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
    DEFAULT_PURGEABLE_EXTENSIONS,
    DEFAULT_TYPE_LABELS,
    PREVIOUS_DEFAULT_CREO_MODEL_SETS,
    PREVIOUS_DEFAULT_DOCUMENT_SETS,
    PREVIOUS_DEFAULT_EXTRA_CAD_SETS,
    PREVIOUS_DEFAULT_IGNORE_SETS,
    PREVIOUS_DEFAULT_PURGEABLE_SETS,
    PREVIOUS_DEFAULT_TYPE_LABEL_SETS,
)
from creopdm.exceptions import ConfigurationError, PathValidationError
from creopdm.logging_setup import get_logger
from creopdm.utils.classify import (
    exclude_extensions,
    extra_cad_set,
    parse_extension_text,
    unique_extensions,
    unique_type_labels,
)
from creopdm.utils.ignore import parse_ignore_text, unique_ignore_patterns

logger = get_logger("config")

VAULTS_DIRNAME = "vaults"
LEGACY_VAULTS_DIRNAME = "workspaces"


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
    open_mode: str = "association"
    view_executable: str | None = None
    view_open_mode: str = "association"
    js_library: str | None = None

    @field_validator("open_mode")
    @classmethod
    def valid_open_mode(cls, value: str) -> str:
        key = (value or "association").strip().lower()
        if key not in CREO_OPEN_MODES:
            return "association"
        return key

    @field_validator("view_open_mode")
    @classmethod
    def valid_view_open_mode(cls, value: str) -> str:
        key = (value or "association").strip().lower()
        if key not in CREO_VIEW_OPEN_MODES:
            return "association"
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
        # Prefer a readable password (@ not %40) in settings.json.
        return database_url_for_display(text)


def _database_url_authority(url: str) -> tuple[str, str, str | None, str] | None:
    """Return scheme, user, password (None if omitted), host+path — or None."""
    text = (url or "").strip()
    if "://" not in text:
        return None
    scheme, rest = text.split("://", 1)
    if scheme.lower().startswith("sqlite"):
        return None
    cut = len(rest)
    for sep in ("/", "?", "#"):
        idx = rest.find(sep)
        if idx != -1:
            cut = min(cut, idx)
    authority, tail = rest[:cut], rest[cut:]
    if "@" not in authority:
        return None
    userinfo, hostport = authority.rsplit("@", 1)
    if ":" in userinfo:
        user, password = userinfo.split(":", 1)
    else:
        user, password = userinfo, None
    return scheme, user, password, f"{hostport}{tail}"


def database_url_for_connect(url: str) -> str:
    """Percent-encode user/password so SQLAlchemy accepts passwords with @, :, etc."""
    parts = _database_url_authority(url)
    if parts is None:
        return (url or "").strip()
    scheme, user, password, rest = parts
    user_q = quote(unquote(user), safe="")
    if password is None:
        return f"{scheme}://{user_q}@{rest}"
    pass_q = quote(unquote(password), safe="")
    return f"{scheme}://{user_q}:{pass_q}@{rest}"


def database_url_for_display(url: str) -> str:
    """Show passwords with literal special characters (e.g. @) in Settings."""
    parts = _database_url_authority(url)
    if parts is None:
        return (url or "").strip()
    scheme, user, password, rest = parts
    user_d = unquote(user)
    if password is None:
        return f"{scheme}://{user_d}@{rest}"
    return f"{scheme}://{user_d}:{unquote(password)}@{rest}"


class WorkspaceConfig(BaseModel):
    root: str | None = None


class UiConfig(BaseModel):
    open_browser_on_start: bool = True
    last_product_uuid: str | None = None
    product_folders: dict[str, str] = Field(default_factory=dict)
    # Embedded Creo browser calls this local agent (materialize / open).
    agent_base_url: str = "http://127.0.0.1:8766"
    # How often the product page polls workspace-watch for pending saves / new files.
    workspace_poll_interval_ms: int = 5000
    # Pause file-list polling after this many minutes with no pointer/keyboard/touch activity.
    # 0 = never pause for idle (tab-hidden still pauses).
    workspace_poll_idle_minutes: int = 10
    # Display-only: HTML for non-admins shows a message when "unavailable".
    site_availability: str = "available"
    site_unavailable_message: str = ""

    @field_validator("agent_base_url")
    @classmethod
    def normalize_agent_base_url(cls, value: object) -> str:
        text = str(value or "").strip().rstrip("/")
        return text or "http://127.0.0.1:8766"

    @field_validator("site_availability")
    @classmethod
    def normalize_site_availability(cls, value: object) -> str:
        from creopdm.site_availability import normalize_site_availability

        return normalize_site_availability(value)

    @field_validator("site_unavailable_message")
    @classmethod
    def normalize_site_unavailable_message(cls, value: object) -> str:
        from creopdm.site_availability import normalize_site_unavailable_message

        return normalize_site_unavailable_message(value)

    @field_validator("workspace_poll_interval_ms")
    @classmethod
    def normalize_workspace_poll(cls, value: object) -> int:
        try:
            ms = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError("File list refresh interval must be an integer.") from exc
        if ms < 500:
            return 500
        if ms > 120_000:
            return 120_000
        return ms

    @field_validator("workspace_poll_idle_minutes")
    @classmethod
    def normalize_workspace_poll_idle(cls, value: object) -> int:
        try:
            minutes = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError("File list idle pause must be an integer.") from exc
        if minutes < 0:
            return 0
        if minutes > 24 * 60:
            return 24 * 60
        return minutes


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
    purgeable_extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_PURGEABLE_EXTENSIONS))
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

    @field_validator("purgeable_extensions", mode="before")
    @classmethod
    def normalize_purgeable_extensions(cls, value: object) -> list[str]:
        return _normalize_extension_list(value, DEFAULT_PURGEABLE_EXTENSIONS)

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


class EmailConfig(BaseModel):
    """SMTP settings for notifications (defaults match local Postfix on Linux)."""

    enabled: bool = False
    # local = Postfix on 127.0.0.1:25 (no auth); smtp = external authenticated relay
    transport: str = "local"
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 25
    from_address: str = ""
    from_name: str = ""
    administrator_email: str = ""
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False
    smtp_use_auth: bool = False

    @model_validator(mode="before")
    @classmethod
    def infer_transport(cls, data: object) -> object:
        """Existing settings.json without transport: treat auth/remote host as smtp."""
        if not isinstance(data, dict):
            return data
        if "transport" in data and (data.get("transport") or "").strip():
            return data
        host = str(data.get("smtp_host") or "").strip().lower()
        if data.get("smtp_use_auth") or (
            host and host not in {"localhost", "127.0.0.1"}
        ):
            data = {**data, "transport": "smtp"}
        else:
            data = {**data, "transport": "local"}
        return data

    @field_validator("transport")
    @classmethod
    def valid_transport(cls, value: str) -> str:
        key = (value or "local").strip().lower()
        if key not in {"local", "smtp"}:
            return "local"
        return key

    @field_validator("smtp_host")
    @classmethod
    def default_host(cls, value: str) -> str:
        return (value or "").strip() or "127.0.0.1"

    @field_validator("smtp_port")
    @classmethod
    def valid_smtp_port(cls, value: int) -> int:
        port = int(value)
        if not 1 <= port <= 65535:
            raise ValueError("SMTP port must be 1–65535.")
        return port

    @field_validator("from_address", "from_name", "administrator_email", "smtp_username")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return (value or "").strip()

    def connection(self) -> tuple[str, int, bool, bool]:
        """Host, port, use_tls, use_auth for the active transport."""
        if self.transport == "local":
            return "127.0.0.1", 25, False, False
        host = (self.smtp_host or "").strip() or "127.0.0.1"
        return host, int(self.smtp_port or 25), bool(self.smtp_use_tls), bool(self.smtp_use_auth)


class AiConfig(BaseModel):
    """Local Ollama connection for snapshot compare and related AI help."""

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    # Editable on Administration → AI only (no code seed / reset).
    snapshot_compare_prompt: str = ""

    @field_validator("ollama_base_url")
    @classmethod
    def normalize_ollama_base_url(cls, value: object) -> str:
        from creopdm.services.ollama_service import normalize_ollama_base_url

        return normalize_ollama_base_url(value)

    @field_validator("ollama_model")
    @classmethod
    def strip_model(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("snapshot_compare_prompt", mode="before")
    @classmethod
    def normalize_snapshot_compare_prompt(cls, value: object) -> str:
        return str(value or "").strip()


class AppSettings(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    creo: CreoConfig = Field(default_factory=CreoConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    cad: CadConfig = Field(default_factory=CadConfig)
    ignore: IgnoreConfig = Field(default_factory=IgnoreConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    ai: AiConfig = Field(default_factory=AiConfig)


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
    "trail.txt*",
    ".bom",
    ".m_p",
    ".wrl",
    ".dgm",
    ".mrk",
    ".als",
    ".ref",
    ".tst",
    ".map",
    ".ers",
    ".info",
    ".cbl",
    ".con",
    ".lgh",
    ".mac",
    ".bde",
    ".bdi",
    ".bdm",
    ".ger",
    ".pls",
    ".txa",
)

# Keys added after the last shipped defaults (additions only — no renames).
_PRE_COMPANION_TYPE_LABEL_NEW_KEYS = frozenset(
    {
        "trail.txt*",
        ".bom",
        ".m_p",
        ".wrl",
        ".dgm",
        ".mrk",
        ".als",
        ".ref",
        ".tst",
        ".map",
        ".ers",
        ".info",
        ".cbl",
        ".con",
        ".lgh",
        ".mac",
        ".bde",
        ".bdi",
        ".bdm",
        ".ger",
        ".pls",
        ".txa",
    }
)


def _pre_companion_type_labels() -> list[dict[str, str]]:
    return [
        item
        for item in DEFAULT_TYPE_LABELS
        if item["extension"] not in _PRE_COMPANION_TYPE_LABEL_NEW_KEYS
    ]


def _type_label_fingerprint(values: object) -> tuple[tuple[str, str], ...]:
    return tuple((item["extension"], item["label"]) for item in unique_type_labels(values))


def _previous_type_label_fingerprints() -> set[tuple[tuple[str, str], ...]]:
    found: set[tuple[tuple[str, str], ...]] = set(PREVIOUS_DEFAULT_TYPE_LABEL_SETS)
    found.add(_type_label_fingerprint(_pre_companion_type_labels()))
    skip: set[str] = set()
    for key in reversed(_ADDED_DEFAULT_TYPE_LABELS):
        skip.add(key)
        found.add(
            _type_label_fingerprint(
                item for item in DEFAULT_TYPE_LABELS if item["extension"] not in skip
            )
        )
    return found


def user_home() -> Path:
    return Path.home()


def path_for_settings_display(path: Path | str) -> str:
    """Format a path for Settings UI hints without embedding the login name.

    Paths under the user home become ``~/...`` (posix separators). Others stay absolute.
    """
    try:
        resolved = Path(path).expanduser().resolve()
        home = user_home().resolve()
    except OSError:
        return str(path)
    try:
        relative = resolved.relative_to(home)
    except ValueError:
        return str(resolved)
    if str(relative) in {"", "."}:
        return "~"
    return "~/" + relative.as_posix()


def sqlite_url_for_settings_display(url: str) -> str:
    """Show SQLite URLs with ``~/...`` when the DB file lives under the user home."""
    text = (url or "").strip()
    if not text.lower().startswith("sqlite:///"):
        return database_url_for_display(text)
    raw_path = text[len("sqlite:///"):]
    if not raw_path:
        return text
    display = path_for_settings_display(raw_path)
    if display.startswith("~"):
        return f"sqlite:///{display}"
    # Absolute posix path needs the fourth slash (sqlite:////home/...).
    if display.startswith("/"):
        return f"sqlite:///{display}"
    return f"sqlite:///{display}"


def on_windows() -> bool:
    return os.name == "nt"


def linux_data_dir() -> Path:
    xdg = (os.environ.get("XDG_DATA_HOME") or "").strip()
    if xdg:
        return Path(xdg).expanduser() / APP_NAME
    return user_home() / ".local" / "share" / APP_NAME


def legacy_linux_data_dir() -> Path:
    return user_home() / "AppData" / "Local" / APP_NAME


def _dir_has_entries(path: Path) -> bool:
    try:
        return path.is_dir() and any(path.iterdir())
    except OSError:
        return False


def _store_has_products(path: Path) -> bool:
    if (path / "database" / "creopdm.db").is_file():
        return True
    return _dir_has_entries(path / VAULTS_DIRNAME) or _dir_has_entries(path / LEGACY_VAULTS_DIRNAME)


def _store_looks_unused(path: Path) -> bool:
    if not path.exists():
        return True
    if _dir_has_entries(path / VAULTS_DIRNAME) or _dir_has_entries(path / LEGACY_VAULTS_DIRNAME):
        return False
    try:
        for child in path.iterdir():
            if child.is_dir() and (child / ".git").is_dir():
                return False
    except OSError:
        return True
    return True


def adopt_legacy_linux_data_dir(target: Path) -> Path:
    """Move ~/AppData/Local/CreoPDM into the Linux data dir when that is still the live store."""
    if on_windows():
        return target
    legacy = legacy_linux_data_dir()
    try:
        chosen = target.expanduser().resolve()
    except OSError:
        return target
    if not legacy.exists():
        return chosen
    try:
        if chosen == legacy.resolve():
            return chosen
    except OSError:
        return target
    if not _store_has_products(legacy):
        return chosen
    if not _store_looks_unused(chosen):
        return chosen
    backup: Path | None = None
    try:
        chosen.parent.mkdir(parents=True, exist_ok=True)
        if chosen.exists():
            backup = chosen.with_name(f"{chosen.name}.empty-backup")
            if backup.exists():
                shutil.rmtree(backup)
            chosen.rename(backup)
        shutil.move(str(legacy), str(chosen))
        if backup is not None:
            shutil.rmtree(backup, ignore_errors=True)
        return chosen
    except OSError:
        if backup is not None and backup.exists() and not chosen.exists():
            try:
                backup.rename(chosen)
            except OSError:
                pass
        return legacy if legacy.exists() else chosen


def data_dir_from_environment() -> Path:
    """Resolve the application data directory.

    Override with CREOPDM_DATA_DIR. Windows uses %LOCALAPPDATA%\\CreoPDM\\.
    Linux uses ~/.local/share/CreoPDM and moves ~/AppData/Local/CreoPDM there once.
    """
    override = os.environ.get("CREOPDM_DATA_DIR")
    if override:
        chosen = Path(override).expanduser()
        if not on_windows():
            try:
                if chosen.expanduser().resolve() == linux_data_dir().resolve():
                    return adopt_legacy_linux_data_dir(chosen)
            except OSError:
                return chosen
        return chosen
    if on_windows():
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            return Path(local_app) / APP_NAME
        return user_home() / "AppData" / "Local" / APP_NAME
    return adopt_legacy_linux_data_dir(linux_data_dir())


class ConfigManager:
    """Loads, persists, and ensures the application data directory layout."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = (data_dir or data_dir_from_environment()).resolve()
        self.config_dir = self.data_dir / "config"
        self.database_dir = self.data_dir / "database"
        self.logs_dir = self.data_dir / "logs"
        self.cache_dir = self.data_dir / "cache"
        self.vaults_dir = self.data_dir / VAULTS_DIRNAME
        self.temp_dir = self.data_dir / "temp"
        self.settings_path = self.config_dir / "settings.json"
        self.database_path = self.database_dir / "creopdm.db"
        self.log_path = self.logs_dir / "creopdm.log"
        self._settings: AppSettings | None = None

    @property
    def workspaces_dir(self) -> Path:
        """Compatibility alias: vault folder on the CreoPDM host."""
        return self.vaults_dir

    def _migrate_vaults_dirname(self) -> None:
        """Prefer vaults/; rename legacy workspaces/ when safe."""
        vaults = self.data_dir / VAULTS_DIRNAME
        legacy = self.data_dir / LEGACY_VAULTS_DIRNAME
        if vaults.exists():
            self.vaults_dir = vaults
            return
        if legacy.is_dir():
            try:
                legacy.rename(vaults)
                logger.info("Renamed vault folder %s → %s", legacy, vaults)
                self.vaults_dir = vaults
                return
            except OSError:
                logger.warning("Could not rename %s to %s; keeping legacy path", legacy, vaults)
                self.vaults_dir = legacy
                return
        self.vaults_dir = vaults

    def ensure_layout(self) -> None:
        self._migrate_vaults_dirname()
        for directory in (
            self.data_dir,
            self.config_dir,
            self.database_dir,
            self.logs_dir,
            self.cache_dir,
            self.vaults_dir,
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
        ui_raw = raw.get("ui") if isinstance(raw, dict) else None
        # Old default was 2000 ms; bump installs still on that default to 5000.
        if isinstance(ui_raw, dict) and ui_raw.get("workspace_poll_interval_ms") == 2000:
            settings.ui.workspace_poll_interval_ms = 5000
            dirty = True
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
        if not isinstance(cad_raw, dict) or "purgeable_extensions" not in cad_raw:
            settings.cad.purgeable_extensions = list(DEFAULT_PURGEABLE_EXTENSIONS)
            dirty = True
        else:
            raw_purgeable = extra_cad_set((cad_raw or {}).get("purgeable_extensions"))
            if raw_purgeable in PREVIOUS_DEFAULT_PURGEABLE_SETS:
                settings.cad.purgeable_extensions = list(DEFAULT_PURGEABLE_EXTENSIONS)
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
        if self._normalize_workspace_root(settings):
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
            return database_url_for_connect(env)
        configured = (self.settings.database.url or "").strip()
        if configured:
            return database_url_for_connect(configured)
        return self.default_sqlite_url()

    def _normalize_workspace_root(self, settings: AppSettings) -> bool:
        """Drop a vault path that is the data dir, the default vaults folder, or a moved Linux AppData folder."""
        configured = (settings.workspace.root or "").strip()
        if not configured:
            return False
        try:
            location = Path(configured).expanduser().resolve()
            default = self.vaults_dir.resolve()
            data = self.data_dir.resolve()
            legacy_default = (self.data_dir / LEGACY_VAULTS_DIRNAME).resolve()
        except OSError:
            return False
        if location in {default, data, legacy_default}:
            settings.workspace.root = None
            return True
        # Settings still point at .../workspaces after an automatic rename to vaults/.
        if (
            location.name == LEGACY_VAULTS_DIRNAME
            and location.parent == data
            and not location.exists()
            and default.exists()
        ):
            settings.workspace.root = None
            return True
        if on_windows():
            return False
        for dirname in (LEGACY_VAULTS_DIRNAME, VAULTS_DIRNAME):
            legacy = legacy_linux_data_dir() / dirname
            try:
                if location == legacy.resolve() and not _dir_has_entries(legacy):
                    settings.workspace.root = None
                    return True
            except OSError:
                continue
        return False

    def workspace_root(self) -> Path:
        configured = (self.settings.workspace.root or "").strip()
        if configured:
            location = Path(configured).expanduser().resolve()
            if location == self.data_dir.resolve():
                return self.vaults_dir
            return location
        return self.vaults_dir

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

    def purgeable_cad_extensions(self) -> list[str]:
        configured = self.settings.cad.purgeable_extensions
        if not configured:
            return list(DEFAULT_PURGEABLE_EXTENSIONS)
        return unique_extensions(configured)

    def all_cad_extensions(self) -> list[str]:
        return unique_extensions((*self.model_cad_extensions(), *self.data_cad_extensions()))

    def type_labels(self) -> list[dict[str, str]]:
        return unique_type_labels(self.settings.cad.type_labels)

    def ignore_patterns(self) -> list[str]:
        configured = self.settings.ignore.patterns
        if configured is None:
            return list(DEFAULT_IGNORE_PATTERNS)
        return unique_ignore_patterns(configured)

    def workspace_for_product(self, vault_folder: str) -> Path:
        """Return the vault directory for a product folder name (UUID or custom)."""
        from creopdm.utils.vault_folder import validate_vault_folder

        folder = validate_vault_folder(vault_folder)
        root = self.workspace_root()
        root.mkdir(parents=True, exist_ok=True)
        return root / folder

    def remember_product(self, product_uuid: str | None) -> None:
        uuid_value = (product_uuid or "").strip() or None
        settings = self.settings
        if settings.ui.last_product_uuid == uuid_value:
            return
        settings.ui.last_product_uuid = uuid_value
        self.save(settings)

    def remembered_folder(self, product_uuid: str) -> str:
        from creopdm.utils.folders import normalize_folder_query

        return normalize_folder_query(self.settings.ui.product_folders.get(product_uuid, ""))

    def remember_folder(self, product_uuid: str, folder: str) -> None:
        from creopdm.utils.folders import normalize_folder_query

        uuid_value = (product_uuid or "").strip()
        if not uuid_value:
            return
        folder = normalize_folder_query(folder)
        settings = self.settings
        current = dict(settings.ui.product_folders)
        stored = current.get(uuid_value, "")
        if stored == folder:
            return
        if folder:
            current[uuid_value] = folder
        else:
            current.pop(uuid_value, None)
        settings.ui.product_folders = current
        self.save(settings)

    def forget_product_view(self, product_uuid: str) -> None:
        uuid_value = (product_uuid or "").strip()
        if not uuid_value:
            return
        settings = self.settings
        current = dict(settings.ui.product_folders)
        if uuid_value not in current:
            return
        current.pop(uuid_value, None)
        settings.ui.product_folders = current
        self.save(settings)
