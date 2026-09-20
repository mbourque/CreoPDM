"""Agent configuration and local cache layout."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel


APP_NAME = "CreoPDM-agent"
DEFAULT_PORT = 8766


def default_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return (base / APP_NAME).resolve()
    xdg = (os.environ.get("XDG_DATA_HOME") or "").strip()
    root = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return (root / APP_NAME).resolve()


class AgentConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    pdm_url: str = ""
    local_root: str = ""
    token: str = ""

    def resolved_root(self) -> Path:
        raw = (self.local_root or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
        return default_data_dir() / "workspaces"

    def ensure_dirs(self) -> Path:
        root = self.resolved_root()
        root.mkdir(parents=True, exist_ok=True)
        (default_data_dir() / "config").mkdir(parents=True, exist_ok=True)
        return root


def config_path() -> Path:
    return default_data_dir() / "config" / "settings.json"


def load_config() -> AgentConfig:
    path = config_path()
    data: dict = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (OSError, json.JSONDecodeError, ValueError):
            data = {}
    env_url = (os.environ.get("CREOPDM_URL") or "").strip()
    env_port = (os.environ.get("CREOPDM_AGENT_PORT") or "").strip()
    env_root = (os.environ.get("CREOPDM_AGENT_ROOT") or "").strip()
    env_token = (os.environ.get("CREOPDM_TOKEN") or "").strip()
    if env_url:
        data["pdm_url"] = env_url
    if env_port.isdigit():
        data["port"] = int(env_port)
    if env_root:
        data["local_root"] = env_root
    if env_token:
        data["token"] = env_token
    return AgentConfig.model_validate(data)


def save_config(settings: AgentConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings.model_dump_json(indent=2) + "\n", encoding="utf-8")
