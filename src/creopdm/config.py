"""Application configuration manager.

Settings live in the application data directory, not in project Git repositories.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from creopdm.constants import APP_NAME, DEFAULT_EXTRA_CAD_EXTENSIONS, DEFAULT_LFS_PATTERNS, PREVIOUS_DEFAULT_EXTRA_CAD_SETS
from creopdm.exceptions import ConfigurationError, PathValidationError
from creopdm.utils.classify import extra_cad_set, parse_extension_text


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 0

    @field_validator("host")
    @classmethod
    def default_localhost_only(cls, value: str) -> str:
        return value.strip() or "127.0.0.1"


class GitConfig(BaseModel):
    executable: str = "git"
    lfs_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_LFS_PATTERNS))


class CreoConfig(BaseModel):
    connector: str = "auto"
    executable: str | None = None
    open_mode: str = "executable"

    @field_validator("open_mode")
    @classmethod
    def valid_open_mode(cls, value: str) -> str:
        key = (value or "executable").strip().lower()
        if key not in {"executable", "association"}:
            return "executable"
        return key


class WorkspaceConfig(BaseModel):
    root: str | None = None


class UiConfig(BaseModel):
    open_browser_on_start: bool = True


class CadConfig(BaseModel):
    extra_extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_EXTRA_CAD_EXTENSIONS))

    @field_validator("extra_extensions", mode="before")
    @classmethod
    def normalize_extensions(cls, value: object) -> list[str]:
        if value is None:
            return list(DEFAULT_EXTRA_CAD_EXTENSIONS)
        if isinstance(value, str):
            return parse_extension_text(value)
        if isinstance(value, (list, tuple, set, frozenset)):
            return sorted(extra_cad_set(str(item) for item in value))
        return list(DEFAULT_EXTRA_CAD_EXTENSIONS)


class AppSettings(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    creo: CreoConfig = Field(default_factory=CreoConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    ui: UiConfig = Field(default_factory=UiConfig)
    cad: CadConfig = Field(default_factory=CadConfig)


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
        if extra_cad_set(settings.cad.extra_extensions) in PREVIOUS_DEFAULT_EXTRA_CAD_SETS:
            settings.cad.extra_extensions = list(DEFAULT_EXTRA_CAD_EXTENSIONS)
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

    def database_url(self) -> str:
        path = self.database_path.resolve().as_posix()
        return f"sqlite:///{path}"

    def workspace_root(self) -> Path:
        configured = (self.settings.workspace.root or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
        return self.workspaces_dir

    def extra_cad_extensions(self) -> list[str]:
        return sorted(extra_cad_set(self.settings.cad.extra_extensions))

    def workspace_for_project(self, project_uuid: str) -> Path:
        if not project_uuid or any(ch in project_uuid for ch in r"/\:"):
            raise PathValidationError("Invalid project identifier for workspace path.")
        root = self.workspace_root()
        root.mkdir(parents=True, exist_ok=True)
        return root / project_uuid
