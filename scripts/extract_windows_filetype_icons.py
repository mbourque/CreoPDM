"""Extract real Windows Explorer filetype icons (32×32 PNG).

Uses the same shell associations as File Explorer — so .sldprt looks like
SOLIDWORKS, .docx like Word, .pdf like your PDF app, etc. Apps must be
installed and registered on this PC for branded icons to appear.

Run (from repo root, on Windows):

  python scripts/extract_windows_filetype_icons.py

Optional:

  python scripts/extract_windows_filetype_icons.py --size 32
  python scripts/extract_windows_filetype_icons.py --overwrite-creo

Requires: Windows + Pillow  (pip install pillow)
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "creopdm" / "static" / "icons"

# Pointer-sized handles — wintypes.HICON is often 32-bit and overflows on Win64.
HANDLE = ctypes.c_void_p
HICON = ctypes.c_void_p
HBITMAP = ctypes.c_void_p
HDC = ctypes.c_void_p

# Our icon filename → probe extension (Windows looks up the association).
# Do not list part/assembly/drawing.png here unless --overwrite-creo.
ICON_FROM_EXT: dict[str, str] = {
    "pdf.png": ".pdf",
    "xps.png": ".xps",
    "word.png": ".docx",
    "rtf.png": ".rtf",
    "excel.png": ".xlsx",
    "csv.png": ".csv",
    "powerpoint.png": ".pptx",
    "visio.png": ".vsdx",
    "project.png": ".mpp",
    "publisher.png": ".pub",
    "onenote.png": ".one",
    "webpage.png": ".html",
    "email.png": ".eml",
    "photoshop.png": ".psd",
    "xml.png": ".xml",
    "log.png": ".log",
    "text.png": ".txt",
    "css.png": ".css",
    "javascript.png": ".js",
    "markdown.png": ".md",
    "json.png": ".json",
    "exe.png": ".exe",
    "ini.png": ".ini",
    "audio.png": ".mp3",
    "video.png": ".mp4",
    "font.png": ".ttf",
    "sldprt.png": ".sldprt",
    "sldasm.png": ".sldasm",
    "slddrw.png": ".slddrw",
    "model3d.png": ".3mf",
    "obj.png": ".obj",
    "step.png": ".stp",
    "stl.png": ".stl",
    "dxf.png": ".dxf",
    "dwg.png": ".dwg",
    "image.png": ".png",
    "archive.png": ".zip",
    "file.png": ".xyz_unknown_creopdm",  # generic document fallback
}

CREO_ICONS: dict[str, str] = {
    "part.png": ".prt",
    "assembly.png": ".asm",
    "drawing.png": ".drw",
}

SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
SHGFI_SMALLICON = 0x000000001
SHGFI_USEFILEATTRIBUTES = 0x000000010
FILE_ATTRIBUTE_NORMAL = 0x00000080
DI_NORMAL = 0x0003
BI_RGB = 0


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", wintypes.WCHAR * 260),
        ("szTypeName", wintypes.WCHAR * 80),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


shell32 = ctypes.windll.shell32
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

shell32.SHGetFileInfoW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(SHFILEINFOW),
    wintypes.UINT,
    wintypes.UINT,
]
shell32.SHGetFileInfoW.restype = ctypes.c_size_t

user32.DestroyIcon.argtypes = [HICON]
user32.DestroyIcon.restype = wintypes.BOOL
user32.GetDC.argtypes = [HANDLE]
user32.GetDC.restype = HDC
user32.ReleaseDC.argtypes = [HANDLE, HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.DrawIconEx.argtypes = [
    HDC,
    ctypes.c_int,
    ctypes.c_int,
    HICON,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
    HANDLE,
    wintypes.UINT,
]
user32.DrawIconEx.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [HDC]
gdi32.CreateCompatibleDC.restype = HDC
gdi32.DeleteDC.argtypes = [HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.CreateDIBSection.argtypes = [
    HDC,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    HANDLE,
    wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = HBITMAP
gdi32.SelectObject.argtypes = [HDC, HANDLE]
gdi32.SelectObject.restype = HANDLE
gdi32.DeleteObject.argtypes = [HANDLE]
gdi32.DeleteObject.restype = wintypes.BOOL


def _require_pillow():
    try:
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Pillow is required. Install with:\n  pip install pillow\n"
        ) from exc


def icon_to_image(hicon, size: int):
    """Rasterize HICON via DrawIconEx (Win64-safe HANDLE types)."""
    from PIL import Image

    hdc_screen = user32.GetDC(None)
    if not hdc_screen:
        raise OSError("GetDC failed")
    hdc = gdi32.CreateCompatibleDC(hdc_screen)
    if not hdc:
        user32.ReleaseDC(None, hdc_screen)
        raise OSError("CreateCompatibleDC failed")

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = size
    bmi.bmiHeader.biHeight = -size  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB

    bits = ctypes.c_void_p()
    dib = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    if not dib or not bits.value:
        gdi32.DeleteDC(hdc)
        user32.ReleaseDC(None, hdc_screen)
        raise OSError("CreateDIBSection failed")

    previous = gdi32.SelectObject(hdc, dib)
    try:
        # Clear to transparent, then draw.
        ctypes.memset(bits.value, 0, size * size * 4)
        if not user32.DrawIconEx(hdc, 0, 0, hicon, size, size, 0, None, DI_NORMAL):
            raise OSError("DrawIconEx failed")
        raw = ctypes.string_at(bits.value, size * size * 4)
        # BGRA → RGBA
        img = Image.frombuffer("RGBA", (size, size), raw, "raw", "BGRA", 0, 1).copy()
        return img
    finally:
        gdi32.SelectObject(hdc, previous)
        gdi32.DeleteObject(dib)
        gdi32.DeleteDC(hdc)
        user32.ReleaseDC(None, hdc_screen)


def extract_for_extension(ext: str, size: int):
    """Return a PIL Image for the Windows association of this extension."""
    ext = ext if ext.startswith(".") else f".{ext}"
    with tempfile.TemporaryDirectory(prefix="creopdm_icons_") as tmp:
        probe = Path(tmp) / f"probe{ext}"
        probe.write_bytes(b"")
        sfi = SHFILEINFOW()
        flags = SHGFI_ICON | SHGFI_USEFILEATTRIBUTES | (
            SHGFI_LARGEICON if size >= 32 else SHGFI_SMALLICON
        )
        ok = shell32.SHGetFileInfoW(
            str(probe),
            FILE_ATTRIBUTE_NORMAL,
            ctypes.byref(sfi),
            ctypes.sizeof(sfi),
            flags,
        )
        if not ok or not sfi.hIcon:
            raise OSError(f"No shell icon for {ext}")
        try:
            return icon_to_image(sfi.hIcon, size)
        finally:
            user32.DestroyIcon(sfi.hIcon)


def update_constants_to_png() -> None:
    """Rewrite DEFAULT_TYPE_ICON_BY_LABEL entries from .svg → matching .png."""
    path = ROOT / "src" / "creopdm" / "constants.py"
    text = path.read_text(encoding="utf-8")
    replacements = {
        '"pdf.svg"': '"pdf.png"',
        '"xps.svg"': '"xps.png"',
        '"word.svg"': '"word.png"',
        '"rtf.svg"': '"rtf.png"',
        '"excel.svg"': '"excel.png"',
        '"csv.svg"': '"csv.png"',
        '"powerpoint.svg"': '"powerpoint.png"',
        '"visio.svg"': '"visio.png"',
        '"project.svg"': '"project.png"',
        '"publisher.svg"': '"publisher.png"',
        '"onenote.svg"': '"onenote.png"',
        '"webpage.svg"': '"webpage.png"',
        '"email.svg"': '"email.png"',
        '"photoshop.svg"': '"photoshop.png"',
        '"xml.svg"': '"xml.png"',
        '"log.svg"': '"log.png"',
        '"text.svg"': '"text.png"',
        '"css.svg"': '"css.png"',
        '"javascript.svg"': '"javascript.png"',
        '"markdown.svg"': '"markdown.png"',
        '"json.svg"': '"json.png"',
        '"exe.svg"': '"exe.png"',
        '"ini.svg"': '"ini.png"',
        '"audio.svg"': '"audio.png"',
        '"video.svg"': '"video.png"',
        '"font.svg"': '"font.png"',
        '"sldprt.svg"': '"sldprt.png"',
        '"sldasm.svg"': '"sldasm.png"',
        '"slddrw.svg"': '"slddrw.png"',
        '"model3d.svg"': '"model3d.png"',
        '"step.svg"': '"step.png"',
        '"stl.svg"': '"stl.png"',
        '"dxf.svg"': '"dxf.png"',
        '"dwg.svg"': '"dwg.png"',
        '"image.svg"': '"image.png"',
        '"archive.svg"': '"archive.png"',
        '"file.svg"': '"file.png"',
    }
    new = text
    for old, repl in replacements.items():
        new = new.replace(old, repl)
    if (OUT / "obj.png").is_file():
        new = new.replace('"OBJ Model": "model3d.png"', '"OBJ Model": "obj.png"')
        new = new.replace('"OBJ Model": "model3d.svg"', '"OBJ Model": "obj.png"')
    if new != text:
        path.write_text(new, encoding="utf-8")
        print(f"Updated {path.relative_to(ROOT)} (.svg → .png)")


def remove_old_svgs(names: list[str]) -> None:
    for name in names:
        svg = OUT / name.replace(".png", ".svg")
        if svg.is_file():
            svg.unlink()
            print(f"Removed old {svg.name}")


def main() -> int:
    if sys.platform != "win32":
        print("This script only runs on Windows (needs Explorer shell icons).")
        return 1
    _require_pillow()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=32, help="Icon size in pixels (default 32)")
    parser.add_argument(
        "--overwrite-creo",
        action="store_true",
        help="Also replace part.png / assembly.png / drawing.png from .prt/.asm/.drw associations",
    )
    parser.add_argument(
        "--no-constants",
        action="store_true",
        help="Do not rewrite constants.py to use .png names",
    )
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    jobs = dict(ICON_FROM_EXT)
    if args.overwrite_creo:
        jobs.update(CREO_ICONS)

    ok = 0
    failed: list[str] = []
    written: list[str] = []
    for dest_name, ext in jobs.items():
        dest = OUT / dest_name
        try:
            img = extract_for_extension(ext, args.size)
            img.save(dest, format="PNG")
            ok += 1
            written.append(dest_name)
            print(f"OK   {dest_name:20} ← {ext}")
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{dest_name} ({ext}): {exc}")
            print(f"FAIL {dest_name:20} ← {ext}  ({exc})")

    remove_old_svgs(written)
    if not args.no_constants:
        update_constants_to_png()

    print(f"\nDone: {ok}/{len(jobs)} icons → {OUT}")
    if failed:
        print("\nStill failed:")
        for line in failed:
            print(f"  - {line}")
        print(
            "\nTip: branded icons need that app registered in Explorer "
            "(SOLIDWORKS for .sldprt, a PDF reader for .pdf, etc.)."
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
