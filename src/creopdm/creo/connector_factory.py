"""Factory for Creo connectors. Swap implementations without changing PDM core."""

from __future__ import annotations

from creopdm.creo.base import CreoConnector
from creopdm.creo.null_connector import NullCreoConnector
from creopdm.creo.windows_connector import WindowsCreoConnector
from creopdm.exceptions import ConfigurationError


def create_creo_connector(
    name: str,
    executable: str | None = None,
    open_mode: str = "executable",
    view_executable: str | None = None,
    view_open_mode: str = "executable",
) -> CreoConnector:
    key = (name or "auto").strip().lower()
    if key in {"null", "none", "off"}:
        return NullCreoConnector()
    if key in {"auto", "default", "windows", "process", "parametric"}:
        return WindowsCreoConnector(
            executable=executable,
            open_mode=open_mode,
            view_executable=view_executable,
            view_open_mode=view_open_mode,
        )
    raise ConfigurationError(
        f"Unknown Creo connector '{name}'.",
        details={"connector": name},
    )
