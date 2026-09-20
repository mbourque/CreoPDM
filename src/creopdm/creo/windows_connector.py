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

_PROCESS_NAMES = ("xtop.exe", "parametric.exe", "parametric", "xtop")
_CREOJS_LIBRARY = Path("Common Files") / "apps" / "creojs" / "creojsweb" / "creojs.js"


def locate_creojs_library(executable: Path | str | None) -> Path | None:
    """Find Creo.JS next to parametric / parametric.exe (Creo loadpoint)."""
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


def _creo_loadpoint_roots() -> list[Path]:
    roots: list[Path] = []
    for key in ("CREOPDM_CREO", "PTC_CREO", "PRO_DIRECTORY", "CREO_START"):
        raw = os.environ.get(key)
        if not raw:
            continue
        path = Path(raw).expanduser()
        roots.append(path.parent if path.is_file() else path)
    for base in (
        Path("/opt/ptc"),
        Path("/opt/PTC"),
        Path.home() / "ptc",
        Path.home() / "PTC",
        Path("/usr/cad"),
        Path(r"C:\Program Files\PTC"),
        Path(r"C:\Program Files (x86)\PTC"),
        Path(r"C:\ptc"),
    ):
        if not base.is_dir():
            continue
        roots.append(base)
        roots.extend(sorted(base.glob("Creo *"), reverse=True))
    return roots


def resolve_creojs_setting(value: Path | str | None) -> Path | None:
    """Resolve a settings/env value that is either creojs.js or a Creo loadpoint folder."""
    if not value:
        return None
    path = Path(value).expanduser()
    try:
        path = path.resolve()
    except OSError:
        pass
    if path.is_file():
        return path
    if path.is_dir():
        direct = path / _CREOJS_LIBRARY
        if direct.is_file():
            return direct.resolve()
        return locate_creojs_library(path)
    return None


def discover_creojs_library(executable: Path | str | None = None) -> Path | None:
    """Locate creojs.js from an explicit path, Creo executable, env, or common install roots."""
    raw = (os.environ.get("CREOPDM_CREOJS") or "").strip()
    if raw:
        found = resolve_creojs_setting(raw)
        if found is not None:
            return found
    found = locate_creojs_library(executable)
    if found is not None:
        return found
    which = shutil.which("parametric") or shutil.which("parametric.exe")
    if which:
        found = locate_creojs_library(which)
        if found is not None:
            return found
    for root in _creo_loadpoint_roots():
        found = resolve_creojs_setting(root)
        if found is not None:
            return found
        for relative in (
            Path("Parametric") / "bin" / "parametric",
            Path("Parametric") / "bin" / "parametric.exe",
            Path("bin") / "parametric",
            Path("bin") / "parametric.exe",
        ):
            found = locate_creojs_library(root / relative)
            if found is not None:
                return found
    return None


class WindowsCreoConnector(CreoConnector):
    """Detect a local Creo install and open models via parametric.exe or the shell."""

    def __init__(
        self,
        executable: str | None = None,
        open_mode: str = "association",
        view_executable: str | None = None,
        view_open_mode: str = "association",
        js_library: str | None = None,
    ) -> None:
        self._executable_override = executable
        self._open_mode = (open_mode or "association").strip().lower()
        self._view_executable_override = view_executable
        self._view_open_mode = (view_open_mode or "association").strip().lower()
        self._js_library_override = js_library

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
        if self._open_mode == "view":
            self.open_view(target)
            return
        if self._open_mode == "embedded":
            raise CreoUnavailableError(
                "Open this model from Creo's built-in browser.",
                details={"path": str(target)},
            )
        parametric = self.find_executable()
        if self._open_mode == "association" or parametric is None:
            logger.info("Opening %s from working directory %s", target.name, workdir)
            if os.name == "nt":
                open_windows_file(target, cwd=workdir)
                return
            opener = "xdg-open" if os.name == "posix" else "open"
            result = subprocess.run(
                [opener, str(target)],
                cwd=str(workdir) if workdir.is_dir() else None,
                check=False,
                capture_output=True,
                shell=False,
            )
            if result.returncode != 0:
                raise CreoUnavailableError(
                    "Unable to open the file with the system viewer.",
                    details={"path": str(target)},
                )
            return
        logger.info("Opening %s with %s from %s", target.name, parametric, workdir)
        start_executable(parametric, target, cwd=workdir)

    def open_view(self, path: Path) -> None:
        target = Path(path)
        if not target.is_file():
            raise CreoUnavailableError(
                "The file to open in Creo View was not found.",
                details={"path": str(target)},
            )
        workdir = working_directory_for(target)
        viewer = self.find_view_executable()
        if self._view_open_mode == "association" or viewer is None:
            logger.info("Opening %s from working directory %s", target.name, workdir)
            if os.name == "nt":
                open_windows_file(target, cwd=workdir)
                return
            opener = "xdg-open" if os.name == "posix" else "open"
            result = subprocess.run(
                [opener, str(target)],
                cwd=str(workdir) if workdir.is_dir() else None,
                check=False,
                capture_output=True,
                shell=False,
            )
            if result.returncode != 0:
                raise CreoUnavailableError(
                    "Unable to open the file with the system viewer.",
                    details={"path": str(target)},
                )
            return
        logger.info("Opening %s with %s from %s", target.name, viewer, workdir)
        start_executable(viewer, target, cwd=workdir, logical_name=False)

    def find_executable(self) -> Path | None:
        for candidate in self._candidates():
            if candidate.is_file():
                return candidate
        return None

    def find_view_executable(self) -> Path | None:
        for candidate in self._view_candidates():
            if candidate.is_file():
                return candidate
        return None

    def cad_open_mode(self) -> str:
        return self._open_mode

    def view_open_mode(self) -> str:
        return self._view_open_mode

    def find_creojs_library(self) -> Path | None:
        if self._js_library_override:
            found = resolve_creojs_setting(self._js_library_override)
            if found is not None:
                return found
        return discover_creojs_library(self.find_executable() or self._executable_override)

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
                        path / "parametric",
                        path / "parametric.exe",
                        path / "bin" / "parametric",
                        path / "bin" / "parametric.exe",
                        path / "Parametric" / "bin" / "parametric",
                        path / "Parametric" / "bin" / "parametric.exe",
                    ]
                )
        which = shutil.which("parametric") or shutil.which("parametric.exe")
        if which:
            found.append(Path(which))
        for root in _creo_loadpoint_roots():
            found.extend(
                [
                    root / "Parametric" / "bin" / "parametric",
                    root / "Parametric" / "bin" / "parametric.exe",
                    root / "bin" / "parametric",
                    root / "bin" / "parametric.exe",
                ]
            )
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
                found.extend(creo_dir.glob("Parametric/bin/parametric"))
        return found

    def _view_candidates(self) -> list[Path]:
        found: list[Path] = []
        if self._view_executable_override:
            found.append(Path(self._view_executable_override))
        raw = os.environ.get("CREOPDM_CREO_VIEW")
        if raw:
            path = Path(raw)
            if path.is_file():
                found.append(path)
            else:
                found.extend([path / "pview.exe", path / "bin" / "pview.exe"])
        which = shutil.which("pview") or shutil.which("pview.exe")
        if which:
            found.append(Path(which))
        for parametric in self._candidates():
            start = parametric.parent if parametric.suffix else parametric
            for root in [start, *start.parents]:
                found.append(root / "View" / "bin" / "pview.exe")
        roots = [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
            Path(r"C:\ptc"),
        ]
        for root in roots:
            if not root or not root.is_dir():
                continue
            ptc = root / "PTC" if (root / "PTC").is_dir() else root
            if not ptc.is_dir():
                continue
            for creo_dir in sorted(ptc.glob("Creo *"), reverse=True):
                found.append(creo_dir / "View" / "bin" / "pview.exe")
            for view_dir in sorted(ptc.glob("Creo View*"), reverse=True):
                found.append(view_dir / "bin" / "pview.exe")
        return found
