"""Launch local files without changing the PDM process working directory."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from creopdm.creo.file_manager import CreoFileManager
from creopdm.logging_setup import get_logger
from creopdm.utils.sta import run_on_sta

logger = get_logger("launch")


def working_directory_for(path: Path) -> Path:
    """Directory Creo (or another app) should start in: the file's folder."""
    return path.resolve().parent


def open_windows_file(path: Path, cwd: Path | None = None) -> None:
    """Open a file with its Windows association, the same as double-clicking it.

    FastAPI worker threads are not STA, so ShellExecute is run on an STA thread.
    cmd ``start "" path`` is not used: an empty title plus a nested path is
    parsed as ``\\\\`` and Windows shows "cannot find '\\'".
    """
    target = path.resolve()
    if not target.is_file():
        raise FileNotFoundError(f"The file was not found: {target}")
    workdir = (cwd or working_directory_for(target)).resolve()
    _start_associated_file(target, workdir)


def _start_associated_file(target: Path, workdir: Path) -> None:
    path = os.fspath(target)
    folder = os.fspath(workdir) if workdir.is_dir() else None
    try:
        run_on_sta(lambda: _shell_execute_open(path, folder))
        logger.info("Opened %s with ShellExecute from %s", path, folder)
        return
    except OSError as exc:
        logger.warning("ShellExecute could not open %s: %s", path, exc)
    if _powershell_start(path, folder):
        logger.info("Opened %s with Start-Process", path)
        return
    try:
        os.startfile(path, cwd=folder)  # type: ignore[attr-defined]
        logger.info("Opened %s with os.startfile", path)
    except OSError as exc:
        raise OSError(f"Unable to open {target.name}: {exc}") from exc


def _shell_execute_open(path: str, folder: str | None) -> None:
    if os.name != "nt":
        raise OSError("ShellExecute is only available on Windows.")
    import ctypes

    shell_execute = ctypes.windll.shell32.ShellExecuteW
    shell_execute.restype = ctypes.c_void_p
    result = shell_execute(None, "open", path, None, folder, 1)
    code = int(result or 0)
    if code <= 32:
        raise OSError(f"Windows could not open the file (ShellExecute {code}): {path}")


def _powershell_start(path: str, folder: str | None) -> bool:
    env = os.environ.copy()
    env["CREOPDM_OPEN_FILE"] = path
    if folder:
        env["CREOPDM_OPEN_DIR"] = folder
    command = (
        "Start-Process -LiteralPath $env:CREOPDM_OPEN_FILE"
        + (" -WorkingDirectory $env:CREOPDM_OPEN_DIR" if folder else "")
    )
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-STA",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=folder,
            check=False,
            shell=False,
        )
    except OSError as exc:
        logger.warning("Start-Process could not run: %s", exc)
        return False
    if result.returncode == 0:
        return True
    logger.warning(
        "Start-Process failed (%s): %s",
        result.returncode,
        (result.stderr or result.stdout or "").strip()[:400],
    )
    return False


def open_windows_folder(path: Path) -> None:
    """Open a folder in Explorer, the same as double-clicking it in the shell."""
    target = path.resolve()
    if not target.is_dir():
        raise FileNotFoundError(f"The folder was not found: {target}")
    if os.name == "nt":
        subprocess.Popen(  # noqa: S603 — argument list, no shell
            ["explorer.exe", str(target)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        logger.info("Opened folder %s in Explorer", target)
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen(  # noqa: S603 — argument list, no shell
        [opener, str(target)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )


def start_executable(executable: Path, path: Path, cwd: Path | None = None) -> None:
    """Start an application with cwd set to the model's workspace folder.

    The model is passed as a relative filename so Creo uses that folder as
    its working directory for related parts, assemblies, and search paths.
    """
    target = path.resolve()
    workdir = (cwd or working_directory_for(target)).resolve()
    name = CreoFileManager.normalize_creo_filename(target.name)
    subprocess.Popen(  # noqa: S603 — argument list, no shell
        [str(executable), name],
        cwd=str(workdir),
        shell=False,
    )
