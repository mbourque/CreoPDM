"""Download Material Icon Theme filetype icons (MIT) into static/icons.

These are purpose-built filetype glyphs — not Windows “open with” associations
(so Image is a picture icon, not Snagit; JSON/DXF are distinct, not blank docs).

Source: https://github.com/material-extensions/vscode-material-icon-theme
CDN:    https://cdn.jsdelivr.net/npm/material-icon-theme@5.38.1/icons/

Do NOT use extract_windows_filetype_icons.py for the list UI — that pulls
whatever app is registered on this PC.

Run (from repo root):

  python scripts/fetch_type_icons.py
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "creopdm" / "static" / "icons"
CONSTANTS = ROOT / "src" / "creopdm" / "constants.py"

# Prefer pinned version; fall back to latest package path / GitHub raw.
VERSIONS = ("5.38.1", "5.37.0", "")
CDN_TMPL = "https://cdn.jsdelivr.net/npm/material-icon-theme{ver}/icons/{name}.svg"
GH_TMPL = (
    "https://raw.githubusercontent.com/material-extensions/"
    "vscode-material-icon-theme/main/icons/{name}.svg"
)

# Our filename → upstream material-icon-theme icon name (no .svg).
# See icons list in the material-icon-theme repo.
ICONS: dict[str, str] = {
    "pdf.svg": "pdf",
    "xps.svg": "pdf",
    "word.svg": "word",
    "rtf.svg": "word",
    "excel.svg": "table",
    "csv.svg": "table",
    "powerpoint.svg": "powerpoint",
    "visio.svg": "drawio",
    "project.svg": "document",
    "publisher.svg": "document",
    "onenote.svg": "document",
    "webpage.svg": "html",
    "email.svg": "email",
    "photoshop.svg": "adobe-photoshop",
    "xml.svg": "xml",
    "log.svg": "log",
    "text.svg": "document",
    "css.svg": "css",
    "javascript.svg": "javascript",
    "markdown.svg": "markdown",
    "json.svg": "json",
    "exe.svg": "exe",
    "ini.svg": "settings",
    "audio.svg": "audio",
    "video.svg": "video",
    "font.svg": "font",
    # CAD / 3D — Material "3d" glyph (not Windows app associations).
    "sldprt.svg": "3d",
    "sldasm.svg": "3d",
    "slddrw.svg": "3d",
    "model3d.svg": "3d",
    "obj.svg": "3d",
    "step.svg": "3d",
    "stl.svg": "3d",
    "dxf.svg": "3d",
    "dwg.svg": "3d",
    "image.svg": "image",
    "archive.svg": "zip",
    "file.svg": "file",
}

# If primary name 404s, try these (Material renamed some icons over time).
ALIASES: dict[str, tuple[str, ...]] = {
    "adobe-photoshop": ("photoshop", "image"),
    "log": ("console", "document"),
    "drawio": ("diagram", "document"),
    "table": ("excel", "document"),
    "3d": ("cube", "file"),
    "settings": ("tune", "document"),
    "zip": ("folder-zip", "document"),
}

# Label → icon file written into constants.py
LABEL_ICONS: dict[str, str] = {
    "Part": "part.png",
    "Assembly": "assembly.png",
    "Drawing": "drawing.png",
    "PDF Document": "pdf.svg",
    "XPS Document": "xps.svg",
    "Word Document": "word.svg",
    "Rich Text Document": "rtf.svg",
    "Excel Document": "excel.svg",
    "CSV File": "csv.svg",
    "PowerPoint Presentation": "powerpoint.svg",
    "Visio Drawing": "visio.svg",
    "Microsoft Project": "project.svg",
    "Publisher Document": "publisher.svg",
    "OneNote": "onenote.svg",
    "Webpage": "webpage.svg",
    "Email": "email.svg",
    "Photoshop": "photoshop.svg",
    "XML File": "xml.svg",
    "Log file": "log.svg",
    "ModelCHECK Error Log": "log.svg",
    "Text File": "text.svg",
    "Stylesheet": "css.svg",
    "JavaScript": "javascript.svg",
    "Markdown": "markdown.svg",
    "JSON": "json.svg",
    "Executable": "exe.svg",
    "Configuration File": "ini.svg",
    "Audio": "audio.svg",
    "Video": "video.svg",
    "Font": "font.svg",
    "SOLIDWORKS Part": "sldprt.svg",
    "SOLIDWORKS Assembly": "sldasm.svg",
    "SOLIDWORKS Drawing": "slddrw.svg",
    "3MF Model": "model3d.svg",
    "OBJ Model": "obj.svg",
    "STEP Model": "step.svg",
    "IGES Model": "model3d.svg",
    "STL Model": "stl.svg",
    "Parasolid Model": "model3d.svg",
    "ACIS Model": "model3d.svg",
    "JT Model": "model3d.svg",
    "DXF Drawing": "dxf.svg",
    "DWG Drawing": "dwg.svg",
    "Image File": "image.svg",
    "Archive": "archive.svg",
    "Inventor Part": "model3d.svg",
    "Inventor Assembly": "model3d.svg",
    "Inventor Drawing": "dwg.svg",
    "Solid Edge Part": "model3d.svg",
    "Solid Edge Assembly": "model3d.svg",
    "Solid Edge Draft": "dwg.svg",
    "VRML": "model3d.svg",
}


def _urls_for(name: str) -> list[str]:
    urls: list[str] = []
    for ver in VERSIONS:
        suffix = f"@{ver}" if ver else ""
        urls.append(CDN_TMPL.format(ver=suffix, name=name))
    urls.append(GH_TMPL.format(name=name))
    return urls


def fetch_svg(name: str) -> bytes | None:
    for cand in (name, *ALIASES.get(name, ())):
        for url in _urls_for(cand):
            try:
                with urllib.request.urlopen(url, timeout=45) as resp:
                    data = resp.read()
                text = data.lstrip()
                if text.startswith(b"<") or text.startswith(b"<?xml"):
                    print(f"  ← {cand}.svg  ({url})")
                    return data
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                print(f"  miss {url}: {exc}")
    return None


def update_constants() -> None:
    """Point DEFAULT_TYPE_ICON_BY_LABEL at the Material SVG filenames."""
    text = CONSTANTS.read_text(encoding="utf-8")
    new = text
    # Flip any Windows-extracted .png entries back to Material .svg names.
    for svg_name in ICONS:
        png_name = svg_name.replace(".svg", ".png")
        new = new.replace(f'"{png_name}"', f'"{svg_name}"')
    # Dedicated OBJ icon when present
    if (OUT / "obj.svg").is_file():
        new = new.replace('"OBJ Model": "model3d.svg"', '"OBJ Model": "obj.svg"')
        new = new.replace('"OBJ Model": "model3d.png"', '"OBJ Model": "obj.svg"')
    # Ensure label map matches LABEL_ICONS for known keys (rewrite block when present).
    start = new.find("DEFAULT_TYPE_ICON_BY_LABEL")
    if start >= 0:
        brace = new.find("{", start)
        close = new.find("\n}", brace)
        if brace > 0 and close > brace:
            body_lines = ["DEFAULT_TYPE_ICON_BY_LABEL: dict[str, str] = {"]
            for label, icon in LABEL_ICONS.items():
                body_lines.append(f'    "{label}": "{icon}",')
            body_lines.append("}")
            line_end = new.find("\n", close + 2)
            if line_end < 0:
                line_end = len(new)
            new = new[:start] + "\n".join(body_lines) + new[line_end:]
    if new != text:
        CONSTANTS.write_text(new, encoding="utf-8")
        print(f"Updated {CONSTANTS.relative_to(ROOT)}")
    else:
        print("constants.py already up to date")


def remove_windows_pngs(keep: set[str]) -> None:
    """Remove shell-extracted PNGs we are replacing with Material SVGs."""
    for path in OUT.glob("*.png"):
        if path.name in keep:
            continue
        # Keep Creo custom art; drop association PNGs that match our svg basenames.
        stem_svg = f"{path.stem}.svg"
        if stem_svg in ICONS:
            path.unlink()
            print(f"Removed old {path.name}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ok = 0
    failed: list[str] = []
    for dest_name, upstream in ICONS.items():
        data = fetch_svg(upstream)
        if not data:
            failed.append(dest_name)
            print(f"FAIL {dest_name}")
            continue
        (OUT / dest_name).write_bytes(data)
        ok += 1
        print(f"OK   {dest_name}")

    remove_windows_pngs(keep={"part.png", "assembly.png", "drawing.png"})
    if ok:
        update_constants()

    # Point JS fallback at svg
    app_js = ROOT / "src" / "creopdm" / "static" / "js" / "app.js"
    if app_js.is_file():
        js = app_js.read_text(encoding="utf-8")
        js2 = js.replace('|| "file.png"', '|| "file.svg"').replace(
            'get("_default", "file.png")', 'get("_default", "file.svg")'
        )
        # classify.py too via separate edit if needed
        if js2 != js:
            app_js.write_text(js2, encoding="utf-8")
            print("Updated app.js default icon to file.svg")

    classify = ROOT / "src" / "creopdm" / "utils" / "classify.py"
    if classify.is_file():
        py = classify.read_text(encoding="utf-8")
        py2 = py.replace('labels.get("_default", "file.png")', 'labels.get("_default", "file.svg")')
        if py2 != py:
            classify.write_text(py2, encoding="utf-8")
            print("Updated classify.py default icon to file.svg")

    print(f"\nDone: {ok}/{len(ICONS)} icons → {OUT}")
    if failed:
        print("Failed:")
        for name in failed:
            print(f"  - {name}")
        return 1
    print("\nAttribution: Material Icon Theme (MIT) — material-extensions/vscode-material-icon-theme")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
