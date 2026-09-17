"""Abstract Creo integration. The PDM core must not depend on a specific API."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CreoModelRef:
    name: str
    path: Path | None = None
    object_type: str | None = None


@dataclass(frozen=True, slots=True)
class CreoDependency:
    parent: str
    child: str
    quantity: float = 1.0
    dependency_type: str = "ASSEMBLY_MEMBER"


@dataclass(frozen=True, slots=True)
class CreoParameter:
    name: str
    value: str
    data_type: str = "STRING"
    units: str | None = None


@dataclass(frozen=True, slots=True)
class CreoBomLine:
    name: str
    quantity: float
    children: list["CreoBomLine"] = field(default_factory=list)


class CreoConnector(ABC):
    """Adapter over Creo Parametric. Implementations may be swapped later."""

    @abstractmethod
    def is_available(self) -> bool:
        """True when Creo appears to be installed or otherwise reachable."""

    @abstractmethod
    def is_running(self) -> bool:
        """True when a live Creo session is detected."""

    @abstractmethod
    def get_active_model(self) -> CreoModelRef | None:
        """Return the current model in session, if any."""

    @abstractmethod
    def get_dependencies(self, model: CreoModelRef) -> list[CreoDependency]:
        """Return assembly/drawing dependencies for a model."""

    @abstractmethod
    def get_parameters(self, model: CreoModelRef) -> list[CreoParameter]:
        """Return model parameters that can be stored per version."""

    @abstractmethod
    def get_bom(self, assembly: CreoModelRef) -> list[CreoBomLine]:
        """Return a structured BOM for an assembly."""

    @abstractmethod
    def open_model(self, path: Path) -> None:
        """Ask Creo to open a model from disk."""

    def cad_open_mode(self) -> str:
        """How CAD models are opened: executable, association, or embedded."""
        return "executable"

    def scan_model(self, path: Path) -> dict[str, Any]:
        """Optional combined scan used by later milestones."""
        raise NotImplementedError
