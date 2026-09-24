"""Download Material Icon Theme SVGs into static/icons (MIT).

Run: python scripts/fetch_type_icons.py
Source: https://github.com/material-extensions/vscode-material-icon-theme
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "creopdm" / "static" / "icons"
CDN = "https://cdn.jsdelivr.net/npm/material-icon-theme@5.28.2/icons"
# Fallback raw GitHub if CDN path differs
GH = "https://raw.githubusercontent.com/material-extensions/vscode-material-icon-theme/main/icons"

# Our filename → upstream material-icon-theme icon name (without .svg)
ICONS: dict[str, str] = {
    "pdf.svg": "pdf",
    "word.svg": "word",
    "excel.svg": "table",
    "csv.svg": "table",
    "powerpoint.svg": "powerpoint",
    "visio.svg": "visio",
    "project.svg": "microsoft-project",  # may 404 → fallback below
    "publisher.svg": "document",
    "onenote.svg": "document",
    "webpage.svg": "html",
    "email.svg": "email",
    "photoshop.svg": "photoshop",
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
    "cad-3d.svg": "3d",
    "xps.svg": "pdf",
    "rtf.svg": "word",
    "image.svg": "image",
    "archive.svg": "zip",
    "file.svg": "file",
}

# Alternate upstream names if primary 404s
ALIASES: dict[str, tuple[str, ...]] = {
    "microsoft-project": ("document",),
    "visio": ("drawio", "document"),
    "photoshop": ("image",),
    "log": ("console", "document"),
    "3d": ("cube", "file"),
}


def fetch(name: str) -> bytes | None:
    for base in (CDN, GH):
        url = f"{base}/{name}.svg"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()
                if data.startswith(b"<") or data.startswith(b"<?xml"):
                    return data
        except Exception as exc:  # noqa: BLE001
            print(f"  miss {url}: {exc}")
    return None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ok = 0
    for dest_name, upstream in ICONS.items():
        dest = OUT / dest_name
        candidates = (upstream, *ALIASES.get(upstream, ()))
        data = None
        used = None
        for cand in candidates:
            data = fetch(cand)
            if data:
                used = cand
                break
        if not data:
            print(f"FAIL {dest_name}")
            continue
        dest.write_bytes(data)
        ok += 1
        print(f"OK   {dest_name} <- {used}.svg ({len(data)} bytes)")
    print(f"Done: {ok}/{len(ICONS)}")


if __name__ == "__main__":
    main()
