"""Windows file dialog. Used because the browser cannot set the start folder."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from creopdm.constants import (
    DEFAULT_CREO_MODEL_EXTENSIONS,
    DEFAULT_DOCUMENT_EXTENSIONS,
    DEFAULT_EXTRA_CAD_EXTENSIONS,
    DEFAULT_OPENABLE_CAD_EXTENSIONS,
)
from creopdm.exceptions import ValidationAppError
from creopdm.logging_setup import get_logger
from creopdm.utils.sta import run_on_sta

logger = get_logger("dialog")

# IFileDialog::Show / HRESULT_FROM_WIN32(ERROR_CANCELLED)
_HRESULT_CANCELLED = 0x800704C7
_WINERROR_CANCELLED = 1223


def is_user_cancelled(exc: BaseException) -> bool:
    """True when Windows reports that the user closed or cancelled a dialog."""
    candidates: list[object] = [
        getattr(exc, "winerror", None),
        getattr(exc, "errno", None),
    ]
    # On POSIX, OSError's 4th ctor arg is not stored as .winerror.
    args = getattr(exc, "args", ())
    if isinstance(args, tuple) and len(args) >= 4:
        candidates.append(args[3])
    for winerror in candidates:
        if winerror is None:
            continue
        try:
            code = int(winerror)
        except (TypeError, ValueError):
            continue
        if code in (_HRESULT_CANCELLED, _WINERROR_CANCELLED, -2147023673):
            return True
        if (code & 0xFFFFFFFF) == _HRESULT_CANCELLED:
            return True
    return False


def creo_model_dialog_filter_patterns() -> str:
    """Default Add filter: numbered Creo parts, assemblies, and drawings."""
    return "*.prt.*;*.asm.*;*.drw.*"


def cad_dialog_filter_patterns() -> str:
    """Glob list for the native file picker, including Creo numbered saves.

    Creo-openable models: *.ext, *.ext.*, and *.*.ext (name.N.ext).
    Other CAD data: *.ext and *.ext.* only.
    """
    seen: set[str] = set()
    openable = set(DEFAULT_CREO_MODEL_EXTENSIONS)
    patterns: list[str] = []
    for ext in (
        *DEFAULT_CREO_MODEL_EXTENSIONS,
        *DEFAULT_OPENABLE_CAD_EXTENSIONS,
        *DEFAULT_EXTRA_CAD_EXTENSIONS,
    ):
        if ext in seen:
            continue
        seen.add(ext)
        patterns.append(f"*{ext}")
        patterns.append(f"*{ext}.*")
        if ext in openable:
            patterns.append(f"*.*{ext}")
    return ";".join(patterns)


def document_dialog_filter_patterns() -> str:
    """Glob list for the Documents group in the native file picker."""
    return ";".join(f"*{ext}" for ext in DEFAULT_DOCUMENT_EXTENSIONS)


def add_files_dialog_filter_pairs() -> list[tuple[str, str]]:
    """Filter groups for Add files: Creo models first, then All files, then others."""
    return [
        ("Creo models (*.prt.*, *.asm.*, *.drw.*)", creo_model_dialog_filter_patterns()),
        ("All files (*.*)", "*.*"),
        ("CAD files", cad_dialog_filter_patterns()),
        ("Documents", document_dialog_filter_patterns()),
    ]


def _is_windows() -> bool:
    """Isolated so tests can fake Windows without patching os.name (breaks pathlib)."""
    return os.name == "nt"


def native_picker_available() -> bool:
    """True when this process can show a Windows file/folder picker."""
    return _is_windows()


def pick_files(initial_dir: Path, title: str = "Add files to the project") -> list[Path]:
    """Open a native multi-select file dialog starting in initial_dir.

    Does not change the PDM process working directory.
    """
    if not _is_windows():
        logger.info("Native file picker is not available; use the browser file chooser")
        return []
    start = Path(initial_dir)
    start.mkdir(parents=True, exist_ok=True)
    try:
        return run_on_sta(lambda: _windows_open_dialog(start, title))
    except Exception:
        logger.exception("GetOpenFileNameW failed; trying Windows Forms picker")
        try:
            return _winforms_open_dialog(start, title)
        except Exception as exc:
            logger.exception("Windows Forms picker also failed")
            raise ValidationAppError(
                "The file picker could not be opened. Copy the files into the vault folder and try again.",
                details={"reason": str(exc)},
            ) from exc


def pick_folder(initial_dir: Path, title: str = "Choose project folder") -> Path | None:
    """Open a native folder picker. Returns None if the user cancels."""
    if not _is_windows():
        logger.info("Native folder picker is not available; use the browser folder chooser")
        return None
    start = Path(initial_dir)
    if not start.is_dir():
        start = start.parent if start.parent.is_dir() else Path.home()
    hwnd = _dialog_owner_hwnd()
    try:
        return run_on_sta(lambda: _windows_folder_dialog(start, title, hwnd))
    except OSError as exc:
        if is_user_cancelled(exc):
            return None
        logger.exception("IFileOpenDialog folder picker failed; trying Windows Forms")
    except Exception:
        logger.exception("IFileOpenDialog folder picker failed; trying Windows Forms")
    try:
        return _winforms_folder_dialog(start, title)
    except Exception as fallback:
        logger.exception("Windows Forms folder picker also failed")
        raise ValidationAppError(
            "The folder picker could not be opened. Type a folder path instead.",
            details={"reason": str(fallback)},
        ) from fallback


def _dialog_owner_hwnd():
    """Own native pickers from the browser window, not the uvicorn console.

    GetConsoleWindow() makes IFileOpenDialog flash and close: the HTML
    <dialog> stays in front and Windows treats the picker as cancelled.
    """
    if not _is_windows():
        return 0
    try:
        import ctypes
        from ctypes.wintypes import HWND

        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = HWND
        user32.GetForegroundWindow.argtypes = []
        return user32.GetForegroundWindow() or 0
    except Exception:
        return 0


def default_project_location_start() -> Path:
    """Sensible starting folder for the New Project location picker."""
    for candidate in (
        Path(r"D:\Engineering\Projects"),
        Path.home() / "Documents",
        Path.home(),
    ):
        if candidate.is_dir():
            return candidate
    return Path.cwd()


def _winforms_open_dialog(initial_dir: Path, title: str) -> list[Path]:
    """Fallback picker that does not need Tcl/Tk."""
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.OpenFileDialog; "
        "$d.InitialDirectory = $env:CREOPDM_DIALOG_DIR; "
        "$d.Title = $env:CREOPDM_DIALOG_TITLE; "
        "$d.Multiselect = $true; "
        "$d.Filter = '"
        + "|".join(f"{label}|{patterns}" for label, patterns in add_files_dialog_filter_pairs())
        + "'; "
        "$d.FilterIndex = 1; "
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


def _winforms_folder_dialog(initial_dir: Path, title: str) -> Path | None:
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "[void][System.Windows.Forms.Application]::EnableVisualStyles(); "
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$d.Description = $env:CREOPDM_DIALOG_TITLE; "
        "$d.SelectedPath = $env:CREOPDM_DIALOG_DIR; "
        "$d.ShowNewFolderButton = $true; "
        "try { $d.UseDescriptionForTitle = $true } catch {}; "
        "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
        "$d.SelectedPath }"
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
            "The folder picker could not be opened.",
            details={"stderr": (result.stderr or "").strip()[:400]},
        )
    line = (result.stdout or "").strip().splitlines()
    if not line:
        return None
    chosen = Path(line[-1].strip())
    return chosen if chosen.is_dir() else None


def _windows_folder_dialog(initial_dir: Path, title: str, hwnd: int | None = None) -> Path | None:
    """Vista-style folder picker (IFileOpenDialog with FOS_PICKFOLDERS)."""
    import ctypes
    from ctypes import HRESULT, POINTER, byref, c_void_p
    from ctypes.wintypes import DWORD, HWND, LPCWSTR, LPWSTR

    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    ole32.CLSIDFromString.argtypes = [LPCWSTR, POINTER(GUID)]
    ole32.CLSIDFromString.restype = HRESULT
    ole32.CoCreateInstance.argtypes = [
        POINTER(GUID),
        c_void_p,
        DWORD,
        POINTER(GUID),
        POINTER(c_void_p),
    ]
    ole32.CoCreateInstance.restype = HRESULT
    ole32.CoTaskMemFree.argtypes = [c_void_p]
    shell32.SHCreateItemFromParsingName.argtypes = [
        LPCWSTR,
        c_void_p,
        POINTER(GUID),
        POINTER(c_void_p),
    ]
    shell32.SHCreateItemFromParsingName.restype = HRESULT

    def as_guid(value: str) -> GUID:
        guid = GUID()
        hr = ole32.CLSIDFromString(value, byref(guid))
        if hr:
            raise OSError(hr)
        return guid

    clsctx_inproc = 1
    fos_pickfolders = 0x20
    fos_forcefilesystem = 0x40
    fos_nochangedir = 0x8
    fos_pathmustexist = 0x800
    sigdn_filesyspath = 0x80058000
    error_cancelled = 0x800704C7

    dialog = c_void_p()
    hr = ole32.CoCreateInstance(
        byref(as_guid("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")),
        None,
        clsctx_inproc,
        byref(as_guid("{D57C7288-D4AD-4768-BE02-9D969532D960}")),
        byref(dialog),
    )
    if hr:
        raise OSError(hr)

    vtbl = ctypes.cast(dialog, POINTER(POINTER(c_void_p))).contents

    def method(index: int, restype, *argtypes):
        proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
        return proto(vtbl[index])

    release = method(2, ctypes.c_ulong)
    # c_long, not HRESULT: ctypes HRESULT restype raises OSError on cancel (0x800704C7).
    show = method(3, ctypes.c_long, HWND)
    set_options = method(9, HRESULT, DWORD)
    set_folder = method(12, HRESULT, c_void_p)
    set_title = method(17, HRESULT, LPCWSTR)
    get_result = method(20, HRESULT, POINTER(c_void_p))

    owner = hwnd if hwnd is not None else _dialog_owner_hwnd()

    try:
        set_options(dialog, fos_pickfolders | fos_forcefilesystem | fos_nochangedir | fos_pathmustexist)
        set_title(dialog, title)
        folder_item = c_void_p()
        if initial_dir.is_dir() and shell32.SHCreateItemFromParsingName(
            str(initial_dir),
            None,
            byref(as_guid("{43826D1E-E718-42EE-BC55-A1E261C37BFE}")),
            byref(folder_item),
        ) == 0 and folder_item:
            set_folder(dialog, folder_item)
            folder_vtbl = ctypes.cast(folder_item, POINTER(POINTER(c_void_p))).contents
            ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)(folder_vtbl[2])(folder_item)
        try:
            hr = show(dialog, owner)
        except OSError as exc:
            if is_user_cancelled(exc):
                return None
            raise
        hr_u = int(hr) & 0xFFFFFFFF
        if hr_u in (error_cancelled, _HRESULT_CANCELLED, _WINERROR_CANCELLED):
            return None
        if hr:
            raise OSError(None, "IFileOpenDialog.Show failed", None, int(hr))
        result_item = c_void_p()
        hr = get_result(dialog, byref(result_item))
        if hr or not result_item:
            return None
        item_vtbl = ctypes.cast(result_item, POINTER(POINTER(c_void_p))).contents
        get_display_name = ctypes.WINFUNCTYPE(HRESULT, c_void_p, DWORD, POINTER(LPWSTR))(
            item_vtbl[5]
        )
        release_item = ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)(item_vtbl[2])
        name = LPWSTR()
        hr = get_display_name(result_item, sigdn_filesyspath, byref(name))
        try:
            if hr or not name.value:
                return None
            chosen = Path(name.value)
        finally:
            if name:
                ole32.CoTaskMemFree(name)
            release_item(result_item)
        return chosen if chosen.is_dir() else None
    finally:
        release(dialog)


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
    # GetOpenFileNameW: pairs are display\0patterns\0… ending with \0\0.
    filter_chunks: list[str] = []
    for label, patterns in add_files_dialog_filter_pairs():
        # Strip "(*.*)" style hints from WinForms labels for the classic dialog.
        short_label = label.split(" (", 1)[0]
        filter_chunks.append(short_label)
        filter_chunks.append(patterns)
    filter_text = "\0".join(filter_chunks) + "\0\0"
    filter_buf = ctypes.create_unicode_buffer(len(filter_text) + 2)
    for index, char in enumerate(filter_text):
        filter_buf[index] = char
    initial_buf = ctypes.create_unicode_buffer(str(initial_dir))
    title_buf = ctypes.create_unicode_buffer(title)

    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.hwndOwner = _dialog_owner_hwnd()
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
