"""Download familiar Microsoft / Adobe / common filetype icons (vscode-icons).

These look like the usual Office / PDF / image badges people recognize — not
abstract Material glyphs, and not “whatever app is registered on this PC”.

True official Microsoft Office / Adobe / SOLIDWORKS product artwork cannot be
redistributed in our repo (trademark). vscode-icons provides the common
look-alikes used widely in IDEs (CC BY-SA; branded marks remain their owners’).

Source: https://github.com/vscode-icons/vscode-icons
Raw:    https://raw.githubusercontent.com/vscode-icons/vscode-icons/master/icons/

Run (from repo root):

  python scripts/fetch_type_icons.py
"""
from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "creopdm" / "static" / "icons"
CONSTANTS = ROOT / "src" / "creopdm" / "constants.py"

# GitHub raw + jsDelivr mirror of the same repo icons folder.
BASES = (
    "https://raw.githubusercontent.com/vscode-icons/vscode-icons/master/icons",
    "https://cdn.jsdelivr.net/gh/vscode-icons/vscode-icons@master/icons",
)

# Our filename → vscode-icons file_type_* name (without file_type_ / .svg).
# Prefer Office/Adobe branded lookalikes from the vscode-icons set.
ICONS: dict[str, tuple[str, ...]] = {
    # Microsoft Office family (word2/excel2/powerpoint2 = familiar Office look)
    "word.svg": ("word2", "word"),
    "rtf.svg": ("word2", "word", "text"),
    "excel.svg": ("excel2", "excel"),
    "csv.svg": ("excel2", "excel", "text"),
    "powerpoint.svg": ("powerpoint2", "powerpoint"),
    "visio.svg": ("drawio", "vector", "svg"),
    "project.svg": ("onenote", "document", "text"),  # no dedicated MPP icon in set
    "publisher.svg": ("publisher", "word2", "document"),
    "onenote.svg": ("onenote", "document"),
    "email.svg": ("outlook", "email", "mail"),
    # Adobe / documents
    "pdf.svg": ("pdf2", "pdf"),
    "xps.svg": ("pdf2", "pdf", "document"),
    "photoshop.svg": ("photoshop2", "photoshop", "image"),
    # Web / code
    "webpage.svg": ("html",),
    "css.svg": ("css",),
    "javascript.svg": ("js_official", "js"),
    "json.svg": ("json_official", "json"),
    "xml.svg": ("xml",),
    "markdown.svg": ("markdown",),
    "text.svg": ("text",),
    "log.svg": ("log", "text"),
    "ini.svg": ("ini", "config", "settings"),
    "exe.svg": ("binary",),
    # Media
    "image.svg": ("image",),
    "audio.svg": ("audio",),
    "video.svg": ("video",),
    "font.svg": ("font",),
    "archive.svg": ("zip2", "zip"),
    # CAD — pack has limited CAD art; blender/openscad are the closest recognizable 3D glyphs
    "sldprt.svg": ("openscad", "blender", "binary"),
    "sldasm.svg": ("openscad", "blender", "binary"),
    "slddrw.svg": ("openscad", "blender", "svg"),
    "model3d.svg": ("blender", "openscad", "obj"),
    "obj.svg": ("blender", "openscad"),
    "step.svg": ("openscad", "blender"),
    "stl.svg": ("openscad", "blender"),
    "dxf.svg": ("svg", "vector", "openscad"),
    "dwg.svg": ("svg", "vector", "openscad"),
    "file.svg": ("text", "document"),
}

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


def _candidate_urls(icon_key: str) -> list[str]:
    name = icon_key if icon_key.startswith("file_type_") else f"file_type_{icon_key}"
    return [f"{base}/{name}.svg" for base in BASES]


def fetch_svg(candidates: tuple[str, ...]) -> tuple[bytes, str] | None:
    for key in candidates:
        for url in _candidate_urls(key):
            try:
                with urllib.request.urlopen(url, timeout=45) as resp:
                    data = resp.read()
                text = data.lstrip()
                if text.startswith(b"<") or text.startswith(b"<?xml"):
                    return data, url
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                print(f"  miss {url}: {exc}")
    return None


def update_constants() -> None:
    text = CONSTANTS.read_text(encoding="utf-8")
    start = text.find("DEFAULT_TYPE_ICON_BY_LABEL")
    if start < 0:
        print("WARN: DEFAULT_TYPE_ICON_BY_LABEL not found")
        return
    brace = text.find("{", start)
    close = text.find("\n}", brace)
    if brace < 0 or close < 0:
        print("WARN: could not locate icon map block")
        return
    line_end = text.find("\n", close + 2)
    if line_end < 0:
        line_end = len(text)
    body = ["DEFAULT_TYPE_ICON_BY_LABEL: dict[str, str] = {"]
    for label, icon in LABEL_ICONS.items():
        body.append(f'    "{label}": "{icon}",')
    body.append("}")
    CONSTANTS.write_text(text[:start] + "\n".join(body) + text[line_end:], encoding="utf-8")
    print(f"Updated {CONSTANTS.relative_to(ROOT)}")


def remove_stale_material_pngs() -> None:
    keep = {"part.png", "assembly.png", "drawing.png"}
    for path in OUT.glob("*.png"):
        if path.name in keep:
            continue
        if f"{path.stem}.svg" in ICONS:
            path.unlink()
            print(f"Removed old {path.name}")


def patch_defaults_to_svg() -> None:
    for rel in (
        "src/creopdm/static/js/app.js",
        "src/creopdm/utils/classify.py",
    ):
        path = ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        new = text.replace('|| "file.png"', '|| "file.svg"').replace(
            'get("_default", "file.png")', 'get("_default", "file.svg")'
        )
        if new != text:
            path.write_text(new, encoding="utf-8")
            print(f"Updated {rel} default → file.svg")


def write_attribution() -> None:
    note = OUT / "ATTRIBUTION.txt"
    note.write_text(
        "Filetype icons (except Creo part/assembly/drawing.png) are from\n"
        "vscode-icons (https://github.com/vscode-icons/vscode-icons).\n"
        "Icons: Creative Commons Attribution-ShareAlike (CC BY-SA).\n"
        "Branded marks (Microsoft, Adobe, etc.) remain their respective owners.\n",
        encoding="utf-8",
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ok = 0
    failed: list[str] = []
    for dest_name, candidates in ICONS.items():
        got = fetch_svg(candidates)
        if not got:
            failed.append(dest_name)
            print(f"FAIL {dest_name}  tried {candidates}")
            continue
        data, url = got
        (OUT / dest_name).write_bytes(data)
        ok += 1
        print(f"OK   {dest_name:20} ← {url}")

    remove_stale_material_pngs()
    if ok:
        update_constants()
        patch_defaults_to_svg()
        write_attribution()
        # Optical size: pad SVG viewBoxes to match Creo PNG margins (~84% fill).
        import importlib.util

        norm = ROOT / "scripts" / "normalize_type_icons.py"
        spec = importlib.util.spec_from_file_location("normalize_type_icons", norm)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        padded = 0
        for path in OUT.glob("*.svg"):
            text = path.read_text(encoding="utf-8")
            updated, changed = mod.pad_viewbox(text)
            if changed and updated != text:
                path.write_text(updated, encoding="utf-8")
                padded += 1
        print(f"Padded {padded} SVG viewBox(es) to match Creo icon margins.")

    print(f"\nDone: {ok}/{len(ICONS)} icons → {OUT}")
    if failed:
        print("Failed (will fall back to file.svg in the UI if missing):")
        for name in failed:
            print(f"  - {name}")
        return 1 if ok == 0 else 0
    print("\nAttribution: vscode-icons (CC BY-SA). Not official Microsoft/Adobe assets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
