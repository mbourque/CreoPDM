"""Null Creo connector so CreoPDM runs without Creo installed."""

from __future__ import annotations

from pathlib import Path

from creopdm.creo.base import (
    CreoBomLine,
    CreoConnector,
    CreoDependency,
    CreoModelRef,
    CreoParameter,
)
from creopdm.exceptions import CreoUnavailableError


class NullCreoConnector(CreoConnector):
    """Always-unavailable connector used when no Creo integration is configured."""

    def is_available(self) -> bool:
        return False

    def is_running(self) -> bool:
        return False

    def get_active_model(self) -> CreoModelRef | None:
        return None

    def get_dependencies(self, model: CreoModelRef) -> list[CreoDependency]:
        return []

    def get_parameters(self, model: CreoModelRef) -> list[CreoParameter]:
        return []

    def get_bom(self, assembly: CreoModelRef) -> list[CreoBomLine]:
        return []

    def open_model(self, path: Path) -> None:
        raise CreoUnavailableError(
            "Creo is not connected. File management remains available.",
            details={"path": str(path)},
        )
