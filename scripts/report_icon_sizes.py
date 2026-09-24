"""Report icon pixel / viewBox sizes for Creo PNGs vs filetype SVGs."""
from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path

ICONS = Path(__file__).resolve().parents[1] / "src" / "creopdm" / "static" / "icons"


def png_size(path: Path) -> tuple[int, int] | None:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    # IHDR width/height
    w, h = struct.unpack(">II", data[16:24])
    return int(w), int(h)


def svg_viewbox(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(r'viewBox="([^"]+)"', text)
    return m.group(1) if m else "(none)"


def main() -> None:
    print("Creo PNGs:")
    for name in ("part.png", "assembly.png", "drawing.png"):
        size = png_size(ICONS / name)
        print(f"  {name}: {size[0]}x{size[1]}" if size else f"  {name}: unreadable")
    print("\nFiletype SVGs (viewBox):")
    for path in sorted(ICONS.glob("*.svg")):
        print(f"  {path.name}: {svg_viewbox(path)}")


if __name__ == "__main__":
    main()
