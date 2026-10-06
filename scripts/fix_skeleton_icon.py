"""Trim and recenter skeleton.png so it fills like part.png (same canvas size)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / "src" / "creopdm" / "static" / "icons"
PART = ROOT / "part.png"
SKEL = ROOT / "skeleton.png"


def content_bbox(im: Image.Image, thr: int = 248) -> tuple[int, int, int, int]:
    """Bounding box of non-transparent, non-near-white pixels."""
    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 12:
                continue
            if r >= thr and g >= thr and b >= thr:
                continue
            minx, miny = min(minx, x), min(miny, y)
            maxx, maxy = max(maxx, x), max(maxy, y)
    if maxx < 0:
        box = rgba.getbbox()
        if not box:
            raise SystemExit("skeleton.png has no visible content")
        return box
    return (minx, miny, maxx + 1, maxy + 1)


def main() -> None:
    part = Image.open(PART).convert("RGBA")
    skel = Image.open(SKEL).convert("RGBA")
    target = part.size
    cropped = skel.crop(content_bbox(skel))

    # Match part.png visual weight: fill almost the full canvas (1px margin).
    margin = 1 if min(target) >= 12 else 0
    inner_w = max(1, target[0] - 2 * margin)
    inner_h = max(1, target[1] - 2 * margin)
    cw, ch = cropped.size
    scale = min(inner_w / cw, inner_h / ch)
    nw = max(1, int(round(cw * scale)))
    nh = max(1, int(round(ch * scale)))
    # NEAREST keeps Creo wireframe crisp at tiny sizes.
    scaled = cropped.resize((nw, nh), Image.Resampling.NEAREST)

    # Opaque white like the other Creo PNGs.
    out = Image.new("RGBA", target, (255, 255, 255, 255))
    ox = (target[0] - nw) // 2
    oy = (target[1] - nh) // 2
    out.paste(scaled, (ox, oy), scaled)
    out.save(SKEL, optimize=True)
    print(f"Wrote {SKEL} size={out.size} (from crop {cropped.size} -> scale {nw}x{nh})")


if __name__ == "__main__":
    main()
