"""Agent configuration and local cache layout."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator

APP_NAME = "CreoPDM-agent"
DEFAULT_PORT = 8766
DEFAULT_HEALTH_INTERVAL_SECONDS = 30
DEFAULT_STATUS_POLL_INTERVAL_SECONDS = 5


def default_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return (base / APP_NAME).resolve()
    xdg = (os.environ.get("XDG_DATA_HOME") or "").strip()
    root = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return (root / APP_NAME).resolve()


def build_pdm_url(host: str, port: int | None = None, *, https: bool = False) -> str:
    """Compose a CreoPDM base URL from host / port fields."""
    text = (host or "").strip()
    if not text:
        return ""
    if "://" in text:
        parsed = urlparse(text.rstrip("/"))
        scheme = parsed.scheme or ("https" if https else "http")
        hostname = parsed.hostname or ""
        if not hostname:
            return text.rstrip("/")
        use_port = port if port and int(port) > 0 else parsed.port
        if use_port and int(use_port) > 0:
            return f"{scheme}://{hostname}:{int(use_port)}"
        return f"{scheme}://{hostname}"
    scheme = "https" if https else "http"
    if port and int(port) > 0:
        return f"{scheme}://{text}:{int(port)}"
    return f"{scheme}://{text}"


def split_pdm_url(url: str) -> tuple[str, int | None, bool]:
    """Return (host, port, https) for settings UI fields."""
    text = (url or "").strip()
    if not text:
        return "", None, False
    if "://" not in text:
        if ":" in text and not text.startswith("["):
            host, _, port_text = text.rpartition(":")
            if host and port_text.isdigit():
                return host, int(port_text), False
        return text, None, False
    parsed = urlparse(text)
    host = parsed.hostname or ""
    port = parsed.port
    https = (parsed.scheme or "http").lower() == "https"
    return host, port, https


class AgentConfig(BaseModel):
    """Local agent settings (Creo workstation).

    The agent *listens* on host:port for the Creo embedded browser.
    It *calls* CreoPDM at pdm_url when materializing files (the page origin
    is preferred when the UI sends it). CreoPDM does not open a special
    inbound port for the tray — it is a normal HTTP client of CreoPDM.
    """

    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    pdm_url: str = ""
    local_root: str = ""
    token: str = ""
    health_interval_seconds: int = DEFAULT_HEALTH_INTERVAL_SECONDS
    # How often the CreoPDM page may re-check /health for the status pill (0 = once).
    status_poll_interval_seconds: int = DEFAULT_STATUS_POLL_INTERVAL_SECONDS

    @field_validator("host")
    @classmethod
    def normalize_host(cls, value: object) -> str:
        text = str(value or "").strip() or "127.0.0.1"
        return text

    @field_validator("port")
    @classmethod
    def normalize_port(cls, value: object) -> int:
        try:
            port = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError("Agent port must be an integer.") from exc
        if port < 1 or port > 65535:
            raise ValueError("Agent port must be between 1 and 65535.")
        return port

    @field_validator("pdm_url")
    @classmethod
    def normalize_pdm_url(cls, value: object) -> str:
        text = str(value or "").strip().rstrip("/")
        if not text:
            return ""
        if "://" not in text:
            # Allow host:port shorthand.
            return build_pdm_url(text)
        return text

    @field_validator("health_interval_seconds")
    @classmethod
    def normalize_health_interval(cls, value: object) -> int:
        try:
            seconds = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError("Health interval must be an integer.") from exc
        if seconds < 0:
            raise ValueError("Health interval cannot be negative.")
        if seconds == 0:
            return 0
        return max(5, seconds)

    @field_validator("status_poll_interval_seconds")
    @classmethod
    def normalize_status_poll_interval(cls, value: object) -> int:
        try:
            seconds = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError("Status poll interval must be an integer.") from exc
        if seconds < 0:
            raise ValueError("Status poll interval cannot be negative.")
        if seconds == 0:
            return 0
        return max(1, min(120, seconds))

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

    def pdm_parts(self) -> tuple[str, int | None, bool]:
        return split_pdm_url(self.pdm_url)

    def set_pdm_parts(self, host: str, port: int | None = None, *, https: bool = False) -> None:
        self.pdm_url = build_pdm_url(host, port, https=https)


def config_path() -> Path:
    return default_data_dir() / "config" / "settings.json"


def load_config() -> AgentConfig:
    path = config_path()
    data: dict = {}
    if path.is_file():
        try:
            # PowerShell Set-Content -Encoding UTF8 may write a BOM.
            text = path.read_text(encoding="utf-8-sig")
            raw = json.loads(text)
            if isinstance(raw, dict):
                data = raw
        except (OSError, json.JSONDecodeError, ValueError):
            data = {}
    # Settings dialog may write flat host/port fields before normalization.
    if "pdm_host" in data or "agent_port" in data:
        host = str(data.get("pdm_host") or "").strip()
        port_raw = data.get("pdm_port")
        try:
            pdm_port = int(port_raw) if port_raw not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            pdm_port = None
        data = {
            "host": data.get("host") or "127.0.0.1",
            "port": data.get("agent_port", data.get("port", DEFAULT_PORT)),
            "pdm_url": build_pdm_url(host, pdm_port, https=bool(data.get("pdm_https"))),
            "token": data.get("token") or "",
            "local_root": data.get("local_root") or "",
            "health_interval_seconds": data.get(
                "health_interval_seconds", DEFAULT_HEALTH_INTERVAL_SECONDS
            ),
            "status_poll_interval_seconds": data.get(
                "status_poll_interval_seconds", DEFAULT_STATUS_POLL_INTERVAL_SECONDS
            ),
        }
    env_url = (os.environ.get("CREOPDM_URL") or "").strip()
    env_port = (os.environ.get("CREOPDM_AGENT_PORT") or "").strip()
    env_root = (os.environ.get("CREOPDM_AGENT_ROOT") or "").strip()
    env_token = (os.environ.get("CREOPDM_TOKEN") or "").strip()
    env_health = (os.environ.get("CREOPDM_AGENT_HEALTH_INTERVAL") or "").strip()
    env_status = (os.environ.get("CREOPDM_AGENT_STATUS_POLL") or "").strip()
    if env_url:
        data["pdm_url"] = env_url
    if env_port.isdigit():
        data["port"] = int(env_port)
    if env_root:
        data["local_root"] = env_root
    if env_token:
        data["token"] = env_token
    if env_health.isdigit():
        data["health_interval_seconds"] = int(env_health)
    if env_status.isdigit():
        data["status_poll_interval_seconds"] = int(env_status)
    return AgentConfig.model_validate(data)


def save_config(settings: AgentConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings.model_dump_json(indent=2) + "\n", encoding="utf-8")


def apply_runtime_settings(target: AgentConfig, source: AgentConfig) -> list[str]:
    """Copy settings that can change without restarting the listen socket.

    Returns human-readable notes for any values that need a restart.
    """
    notes: list[str] = []
    target.pdm_url = source.pdm_url
    target.token = source.token
    target.local_root = source.local_root
    target.health_interval_seconds = source.health_interval_seconds
    target.status_poll_interval_seconds = source.status_poll_interval_seconds
    if source.host != target.host or source.port != target.port:
        notes.append(
            f"Listen address {source.host}:{source.port} is saved; "
            "quit and restart the agent tray to use it."
        )
    return notes
