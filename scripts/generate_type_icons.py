"""Generate simple 32×32 filetype SVG icons into static/icons.

Also used as a catalog of icon filenames referenced by DEFAULT_TYPE_ICON_BY_LABEL.
Run: python scripts/generate_type_icons.py
"""
from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "creopdm" / "static" / "icons"


def _doc(fill: str, fold: str, mark: str, mark_fill: str = "#fff") -> str:
    """Colored document glyph with a small badge mark (1–3 chars or path fragment)."""
    # mark may be plain text or a raw SVG snippet starting with '<'
    if mark.startswith("<"):
        badge = mark
    else:
        size = 9 if len(mark) <= 2 else 7
        badge = (
            f'<text x="16" y="23" text-anchor="middle" fill="{mark_fill}" '
            f'font-family="Segoe UI,Arial,sans-serif" font-size="{size}" '
            f'font-weight="700">{mark}</text>'
        )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <path fill="{fill}" d="M7 2h12l6 6v20a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z"/>
  <path fill="{fold}" d="M19 2v6h6z"/>
  {badge}
</svg>
'''


def _glyph(bg: str, body: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <rect width="32" height="32" rx="6" fill="{bg}"/>
  {body}
</svg>
'''


ICONS: dict[str, str] = {
    "pdf.svg": _doc("#E5252A", "#F48B8E", "PDF"),
    "word.svg": _doc("#2B579A", "#7BA3D4", "W"),
    "rtf.svg": _doc("#2B579A", "#7BA3D4", "RTF"),
    "excel.svg": _doc("#217346", "#6AAD84", "X"),
    "csv.svg": _doc("#217346", "#6AAD84", "CSV"),
    "powerpoint.svg": _doc("#B7472A", "#D88974", "P"),
    "visio.svg": _doc("#3955A3", "#7F93C8", "V"),
    "project.svg": _doc("#31752F", "#7AAD78", "MP"),
    "publisher.svg": _doc("#077568", "#5AA8A0", "Pub"),
    "onenote.svg": _doc("#7719AA", "#B07AD4", "One"),
    "webpage.svg": _doc("#E44D26", "#F39A80", "HTML"),
    "email.svg": _glyph(
        "#0078D4",
        '<path fill="#fff" d="M6 10h20v12H6zm0 0 10 7 10-7"/>',
    ),
    "photoshop.svg": _doc("#001E36", "#31A8FF", "Ps", "#31A8FF"),
    "xml.svg": _doc("#F16529", "#F7A87A", "XML"),
    "log.svg": _doc("#5C6BC0", "#9FA8DA", "LOG"),
    "text.svg": _doc("#607D8B", "#90A4AE", "TXT"),
    "css.svg": _doc("#1572B6", "#6AA9D8", "CSS"),
    "javascript.svg": _glyph(
        "#F7DF1E",
        '<text x="16" y="22" text-anchor="middle" fill="#323330" font-family="Segoe UI,Arial,sans-serif" font-size="12" font-weight="700">JS</text>',
    ),
    "markdown.svg": _doc("#42A5F5", "#90CAF9", "MD"),
    "json.svg": _doc("#FBC02D", "#FFE082", "{}"),
    "exe.svg": _glyph(
        "#455A64",
        '<rect x="8" y="8" width="16" height="16" rx="2" fill="#CFD8DC"/><rect x="11" y="14" width="10" height="2" fill="#455A64"/>',
    ),
    "ini.svg": _doc("#78909C", "#B0BEC5", "INI"),
    "audio.svg": _glyph(
        "#8E24AA",
        '<path fill="#fff" d="M10 12v8h4l6 4V8l-6 4zm-2 2h2v4H8z"/>',
    ),
    "video.svg": _glyph(
        "#C62828",
        '<path fill="#fff" d="M8 10h10v12H8zm12 2 4-2v12l-4-2z"/>',
    ),
    "font.svg": _glyph(
        "#6D4C41",
        '<text x="16" y="23" text-anchor="middle" fill="#fff" font-family="Georgia,serif" font-size="16" font-weight="700">A</text>',
    ),
    "xps.svg": _doc("#D83B01", "#F0A57F", "XPS"),
    "image.svg": _glyph(
        "#26A69A",
        '<rect x="6" y="8" width="20" height="16" rx="2" fill="#E0F2F1"/><circle cx="12" cy="14" r="2" fill="#00897B"/><path fill="#00897B" d="M8 22l5-6 3 4 3-3 5 5z"/>',
    ),
    "archive.svg": _glyph(
        "#F9A825",
        '<path fill="#fff" d="M10 6h12v4H10zm0 4h12v16H10zm4 2h4v2h-4zm0 4h4v2h-4z"/>',
    ),
    "model3d.svg": _glyph(
        "#00897B",
        '<path fill="#fff" d="M16 6l10 6v8l-10 6-10-6v-8zm0 2.3L8.5 13 16 17.2 23.5 13zm-8 6.2v5.3L15 26v-5.3zm10 5.3L24 19.5v-5.3L18 19.5z"/>',
    ),
    "sldprt.svg": _glyph(
        "#D50000",
        '<path fill="#fff" d="M8 22V10l8-4 8 4v12l-8 4zm8-14.2L11 10.2v9.6l5 2.5 5-2.5v-9.6z"/>'
        '<text x="16" y="19" text-anchor="middle" fill="#D50000" font-family="Segoe UI,Arial,sans-serif" font-size="6" font-weight="700">SW</text>',
    ),
    "sldasm.svg": _glyph(
        "#B71C1C",
        '<path fill="#fff" d="M7 20V11l4-2 5 2.5V20l-5 2.5zm9-8.5 4-2 5 2.5v9l-5 2.5-4-2.1z"/>'
        '<text x="16" y="18" text-anchor="middle" fill="#B71C1C" font-family="Segoe UI,Arial,sans-serif" font-size="5" font-weight="700">ASM</text>',
    ),
    "slddrw.svg": _glyph(
        "#E53935",
        '<rect x="7" y="6" width="18" height="20" rx="1" fill="#fff"/>'
        '<path stroke="#E53935" stroke-width="1.5" fill="none" d="M10 22 V12 h8 v10 M12 16h4"/>'
        '<text x="16" y="11" text-anchor="middle" fill="#E53935" font-family="Segoe UI,Arial,sans-serif" font-size="5" font-weight="700">DRW</text>',
    ),
    "file.svg": _doc("#90A4AE", "#CFD8DC", "…", "#546E7A"),
    "step.svg": _doc("#00838F", "#4DB6AC", "STP"),
    "dwg.svg": _doc("#E65100", "#FFB74D", "DWG"),
    "dxf.svg": _doc("#EF6C00", "#FFB74D", "DXF"),
    "stl.svg": _doc("#00695C", "#4DB6AC", "STL"),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, svg in ICONS.items():
        path = OUT / name
        path.write_text(svg.strip() + "\n", encoding="utf-8")
        print(f"wrote {path.name}")
    print(f"Done: {len(ICONS)} icons → {OUT}")


if __name__ == "__main__":
    main()
