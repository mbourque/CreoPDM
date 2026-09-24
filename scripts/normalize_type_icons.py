"""Normalize filetype SVG optical size to match Creo part/assembly/drawing PNGs.

Creo icons are 64×64 with ~15% margin. vscode-icons SVGs fill a 32×32 viewBox
edge-to-edge, so at 14px display they look larger. This pads every filetype SVG
viewBox so the artwork sits in the same relative frame as the Creo set.

Run (after fetch_type_icons.py):

  python scripts/normalize_type_icons.py
"""
from __future__ import annotations

import re
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "creopdm" / "static" / "icons"

# Match Creo cube fill (~54/64 ≈ 0.84). Pad SVG so content is ~84% of frame.
TARGET_FILL = 0.84
VIEWBOX_RE = re.compile(
    r'viewBox\s*=\s*"([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)"',
    re.IGNORECASE,
)


def pad_viewbox(text: str) -> tuple[str, bool]:
    match = VIEWBOX_RE.search(text)
    if not match:
        return text, False
    x, y, w, h = (float(match.group(i)) for i in range(1, 5))
    if w <= 0 or h <= 0:
        return text, False
    # Already padded (wider than content box) — still re-apply from numbers as-is
    side = max(w, h)
    new_side = side / TARGET_FILL
    pad = (new_side - side) / 2
    cx = x + w / 2
    cy = y + h / 2
    nx = cx - new_side / 2
    ny = cy - new_side / 2
    replacement = f'viewBox="{nx:.3f} {ny:.3f} {new_side:.3f} {new_side:.3f}"'
    return VIEWBOX_RE.sub(replacement, text, count=1), True


def main() -> int:
    count = 0
    for path in sorted(OUT.glob("*.svg")):
        original = path.read_text(encoding="utf-8")
        updated, ok = pad_viewbox(original)
        if not ok:
            print(f"SKIP {path.name} (no viewBox)")
            continue
        if updated == original:
            print(f"OK   {path.name} (unchanged)")
            continue
        path.write_text(updated, encoding="utf-8")
        count += 1
        print(f"OK   {path.name} padded to ~{int(TARGET_FILL * 100)}% fill")
    print(f"\nNormalized {count} SVG(s). Creo PNGs left as-is (already padded).")
    print("UI still draws all .type-icon at 14×14 — optical size should now match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
