"""Match filetype SVG optical size to Creo part/assembly/drawing PNGs.

Creo icons are solid 3D glyphs; vscode-icons are often thin line art, so equal
geometry still looks smaller. Strategy:

1. Undo any prior viewBox padding from this script (content was ~84% of frame).
2. Leave SVGs at their native viewBox (full artwork).
3. UI CSS draws SVG type-icons slightly larger than PNG (see app.css).

Run:

  python scripts/normalize_type_icons.py
"""
from __future__ import annotations

import re
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "creopdm" / "static" / "icons"

# Previous normalize used this fill; undo it so artwork is full-bleed again.
PREV_FILL = 0.84
VIEWBOX_RE = re.compile(
    r'viewBox\s*=\s*"([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)"',
    re.IGNORECASE,
)


def restore_viewbox(text: str) -> tuple[str, bool]:
    """If viewBox looks padded (negative origin / non-integer side), shrink to content."""
    match = VIEWBOX_RE.search(text)
    if not match:
        return text, False
    x, y, w, h = (float(match.group(i)) for i in range(1, 5))
    if w <= 0 or h <= 0:
        return text, False
    # Only restore when we clearly padded (expanded past a round 16/24/32 box).
    side = max(w, h)
    # Padded 32→38.095, 24→28.571, etc.
    content_side = side * PREV_FILL
    # Round to nearest whole pixel frame if close (common vscode-icons sizes).
    for native in (16.0, 24.0, 32.0, 48.0, 64.0):
        if abs(content_side - native) < 0.05:
            content_side = native
            break
    if abs(content_side - side) < 0.01:
        return text, False
    cx = x + w / 2
    cy = y + h / 2
    nx = cx - content_side / 2
    ny = cy - content_side / 2
    # Prefer clean "0 0 N N" when centered on that box.
    if abs(nx) < 0.05 and abs(ny) < 0.05:
        replacement = f'viewBox="0 0 {content_side:.0f} {content_side:.0f}"'
    else:
        replacement = f'viewBox="{nx:.3f} {ny:.3f} {content_side:.3f} {content_side:.3f}"'
    return VIEWBOX_RE.sub(replacement, text, count=1), True


def main() -> int:
    count = 0
    for path in sorted(OUT.glob("*.svg")):
        original = path.read_text(encoding="utf-8")
        updated, changed = restore_viewbox(original)
        if not changed:
            print(f"OK   {path.name} (already native)")
            continue
        path.write_text(updated, encoding="utf-8")
        count += 1
        print(f"OK   {path.name} restored full viewBox")
    print(f"\nRestored {count} SVG(s). Hard-refresh the UI.")
    print("CSS sizes SVG type-icons a bit larger than Creo PNGs for optical match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
