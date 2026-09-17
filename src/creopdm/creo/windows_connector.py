"""Launch Creo Parametric from the OS without embedding a specific Creo API."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from creopdm.creo.base import (
    CreoBomLine,
    CreoConnector,
    CreoDependency,
    CreoModelRef,
    CreoParameter,
)
from creopdm.exceptions import CreoUnavailableError
from creopdm.logging_setup import get_logger
from creopdm.utils.launch import open_windows_file, start_executable, working_directory_for

logger = get_logger("creo")

_PROCESS_NAMES = ("xtop.exe", "parametric.exe")
_CREOJS_LIBRARY = Path("Common Files") / "apps" / "creojs" / "creojsweb" / "creojs.js"


def locate_creojs_library(executable: Path | str | None) -> Path | None:
    """Find Creo.JS next to parametric.exe / parametric.bat (Creo loadpoint)."""
    if not executable:
        return None
    start = Path(executable).expanduser()
    try:
        start = start.resolve()
    except OSError:
        pass
    current = start.parent if start.is_file() or start.suffix else start
    roots = [current, *current.parents]
    seen: set[Path] = set()
    for root in roots:
        try:
            key = root.resolve()
        except OSError:
            key = root
        if key in seen:
            continue
        seen.add(key)
        candidate = root / _CREOJS_LIBRARY
        if candidate.is_file():
            return candidate
    return None


class WindowsCreoConnector(CreoConnector):
    """Detect a local Creo install and open models via parametric.exe or the shell."""

    def __init__(self, executable: str | None = None, open_mode: str = "executable") -> None:
        self._executable_override = executable
        self._open_mode = (open_mode or "executable").strip().lower()

    def is_available(self) -> bool:
        return self.find_executable() is not None

    def is_running(self) -> bool:
        if os.name != "nt":
            return False
        for name in _PROCESS_NAMES:
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
                    capture_output=True,
                    text=True,
                    check=False,
                    shell=False,
                )
            except FileNotFoundError:
                return False
            output = (result.stdout or "").lower()
            if name.lower() in output and "no tasks" not in output:
                return True
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
        target = Path(path)
        if not target.is_file():
            raise CreoUnavailableError(
                "The file to open in Creo was not found.",
                details={"path": str(target)},
            )
        workdir = working_directory_for(target)
        if self._open_mode == "embedded":
            raise CreoUnavailableError(
                "Open this model from Creo's built-in browser.",
                details={"path": str(target)},
            )
        parametric = self.find_executable()
        if self._open_mode == "association" or parametric is None:
            if os.name == "nt":
                logger.info("Opening %s from working directory %s", target.name, workdir)
                open_windows_file(target, cwd=workdir)
                return
            raise CreoUnavailableError(
                "Creo is not installed and no file association is available.",
                details={"path": str(target)},
            )
        logger.info("Opening %s with %s from %s", target.name, parametric, workdir)
        start_executable(parametric, target, cwd=workdir)

    def find_executable(self) -> Path | None:
        for candidate in self._candidates():
            if candidate.is_file():
                return candidate
        return None

    def cad_open_mode(self) -> str:
        return self._open_mode

    def find_creojs_library(self) -> Path | None:
        return locate_creojs_library(self.find_executable())

    def _candidates(self) -> list[Path]:
        found: list[Path] = []
        if self._executable_override:
            found.append(Path(self._executable_override))
        for key in ("CREOPDM_CREO", "PTC_CREO", "PRO_DIRECTORY"):
            raw = os.environ.get(key)
            if not raw:
                continue
            path = Path(raw)
            if path.is_file():
                found.append(path)
            else:
                found.extend(
                    [
                        path / "parametric.exe",
                        path / "bin" / "parametric.exe",
                        path / "Parametric" / "bin" / "parametric.exe",
                    ]
                )
        which = shutil.which("parametric") or shutil.which("parametric.exe")
        if which:
            found.append(Path(which))
        program_files = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ]
        for root in program_files:
            if not root:
                continue
            ptc = Path(root) / "PTC"
            if not ptc.is_dir():
                continue
            for creo_dir in sorted(ptc.glob("Creo *"), reverse=True):
                found.extend(creo_dir.glob("Parametric/bin/parametric.exe"))
                found.extend(creo_dir.glob("*/Parametric/bin/parametric.exe"))
        return found
