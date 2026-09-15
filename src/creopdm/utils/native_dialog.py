"""Windows file dialog. Used because the browser cannot set the start folder."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from creopdm.exceptions import ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.utils.sta import run_on_sta

logger = get_logger("dialog")


def pick_files(initial_dir: Path, title: str = "Add files to the project") -> list[Path]:
    """Open a native multi-select file dialog starting in initial_dir.

    Does not change the PDM process working directory.
    """
    start = Path(initial_dir)
    start.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        return []
    try:
        return run_on_sta(lambda: _windows_open_dialog(start, title))
    except Exception:
        logger.exception("GetOpenFileNameW failed; trying Windows Forms picker")
        try:
            return _winforms_open_dialog(start, title)
        except Exception as exc:
            logger.exception("Windows Forms picker also failed")
            raise ValidationAppError(
                "The file picker could not be opened. Copy the files into the workspace folder and try again.",
                details={"reason": str(exc)},
            ) from exc


def _winforms_open_dialog(initial_dir: Path, title: str) -> list[Path]:
    """Fallback picker that does not need Tcl/Tk."""
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.OpenFileDialog; "
        "$d.InitialDirectory = $env:CREOPDM_DIALOG_DIR; "
        "$d.Title = $env:CREOPDM_DIALOG_TITLE; "
        "$d.Multiselect = $true; "
        "$d.Filter = 'All files (*.*)|*.*'; "
        "$d.CheckFileExists = $true; "
        "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
        "$d.FileNames | ForEach-Object { $_ } }"
    )
    env = os.environ.copy()
    env["CREOPDM_DIALOG_DIR"] = str(initial_dir)
    env["CREOPDM_DIALOG_TITLE"] = title
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-STA", "-WindowStyle", "Hidden", "-Command", script],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        raise ValidationAppError(
            "The file picker could not be opened.",
            details={"stderr": (result.stderr or "").strip()[:400]},
        )
    return [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]


def _windows_open_dialog(initial_dir: Path, title: str) -> list[Path]:
    import ctypes
    from ctypes import wintypes

    ofn_explorer = 0x00080000
    ofn_allow_multi = 0x00000200
    ofn_file_must_exist = 0x00001000
    ofn_path_must_exist = 0x00000800
    ofn_no_change_dir = 0x00000008
    ofn_hide_readonly = 0x00000004

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", ctypes.c_void_p),
            ("lpstrCustomFilter", ctypes.c_void_p),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", ctypes.c_void_p),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", ctypes.c_void_p),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", ctypes.c_void_p),
            ("lpstrTitle", ctypes.c_void_p),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", ctypes.c_void_p),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", ctypes.c_void_p),
            ("pvReserved", ctypes.c_void_p),
            ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]

    buffer_chars = 32768
    file_buf = ctypes.create_unicode_buffer(buffer_chars)
    filter_text = (
        "All files\0*.*\0"
        "Creo files\0*.prt;*.prt.*;*.asm;*.asm.*;*.drw;*.drw.*;*.mfg;*.mfg.*\0"
        "Documents\0*.pdf;*.docx;*.doc;*.xlsx;*.xls;*.txt;*.step;*.stp\0\0"
    )
    filter_buf = ctypes.create_unicode_buffer(len(filter_text) + 2)
    for index, char in enumerate(filter_text):
        filter_buf[index] = char
    initial_buf = ctypes.create_unicode_buffer(str(initial_dir))
    title_buf = ctypes.create_unicode_buffer(title)

    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    hwnd = 0
    try:
        get_console = ctypes.windll.kernel32.GetConsoleWindow
        get_console.restype = wintypes.HWND
        get_console.argtypes = []
        hwnd = get_console() or 0
    except Exception:
        hwnd = 0
    ofn.hwndOwner = hwnd
    ofn.lpstrFilter = ctypes.addressof(filter_buf)
    ofn.nFilterIndex = 1
    ofn.lpstrFile = ctypes.addressof(file_buf)
    ofn.nMaxFile = buffer_chars
    ofn.lpstrInitialDir = ctypes.addressof(initial_buf)
    ofn.lpstrTitle = ctypes.addressof(title_buf)
    ofn.Flags = (
        ofn_explorer
        | ofn_allow_multi
        | ofn_file_must_exist
        | ofn_path_must_exist
        | ofn_no_change_dir
        | ofn_hide_readonly
    )
    get_open = ctypes.windll.comdlg32.GetOpenFileNameW
    get_open.argtypes = [ctypes.POINTER(OPENFILENAMEW)]
    get_open.restype = wintypes.BOOL
    ok = get_open(ctypes.byref(ofn))
    if not ok:
        err = ctypes.windll.comdlg32.CommDlgExtendedError()
        if not err:
            return []
        raise ValidationAppError(
            "The file picker could not be opened.",
            details={"windows_error": int(err)},
        )
    raw = ctypes.wstring_at(ctypes.addressof(file_buf), buffer_chars)
    chunks = [item for item in raw.split("\0") if item]
    if not chunks:
        return []
    if len(chunks) == 1:
        return [Path(chunks[0])]
    folder = Path(chunks[0])
    return [folder / name for name in chunks[1:]]
