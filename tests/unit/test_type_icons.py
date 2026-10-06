"""Type icon mapping from settings labels / extensions."""

from pathlib import Path

from creopdm.utils.classify import resolve_type_icon, type_icon_client_payload


def test_resolve_type_icon_by_label_and_extension():
    assert resolve_type_icon(type_label="PDF Document") == "pdf.svg"
    assert resolve_type_icon(extension=".docx") == "word.svg"
    assert resolve_type_icon(extension=".sldprt") == "sldprt.svg"
    assert resolve_type_icon(type_label="Image File") == "image.svg"
    assert resolve_type_icon(extension=".json") == "json.svg"
    assert resolve_type_icon(object_type="CREO_PART") == "part.png"
    assert resolve_type_icon(filename="notes.txt") == "text.svg"
    assert resolve_type_icon(type_label="Audio", extension=".mp3") == "audio.svg"


def test_type_icon_client_payload_includes_settings_extensions():
    payload = type_icon_client_payload()
    assert payload["by_ext"][".pdf"] == "pdf.svg"
    assert payload["by_label"]["Word Document"] == "word.svg"
    assert payload["by_label"]["Image File"] == "image.svg"
    assert payload["by_object_type"]["CREO_DRAWING"] == "drawing.png"


def test_default_type_icons_cover_office_and_creo():
    from creopdm.constants import DEFAULT_TYPE_ICON_BY_LABEL

    assert DEFAULT_TYPE_ICON_BY_LABEL["Part"] == "part.png"
    assert DEFAULT_TYPE_ICON_BY_LABEL["Assembly"] == "assembly.png"
    assert DEFAULT_TYPE_ICON_BY_LABEL["Drawing"] == "drawing.png"
    assert DEFAULT_TYPE_ICON_BY_LABEL["SKELETON"] == "skeleton.png"
    assert DEFAULT_TYPE_ICON_BY_LABEL["PDF Document"].endswith(".svg")
    assert DEFAULT_TYPE_ICON_BY_LABEL["Word Document"].endswith(".svg")
    assert DEFAULT_TYPE_ICON_BY_LABEL["Excel Document"].endswith(".svg")


def test_skeleton_icon_matches_part_canvas_size():
    """Skeleton wireframe must share part.png canvas so Files list icons align."""
    from PIL import Image

    icons = Path("src/creopdm/static/icons")
    part = Image.open(icons / "part.png")
    skel = Image.open(icons / "skeleton.png")
    assert skel.size == part.size, f"skeleton {skel.size} != part {part.size}"
    # Content should fill most of the canvas (not a tiny glyph in a corner).
    rgba = skel.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a < 12 or (r >= 248 and g >= 248 and b >= 248):
                continue
            minx, miny = min(minx, x), min(miny, y)
            maxx, maxy = max(maxx, x), max(maxy, y)
    assert maxx >= 0, "skeleton.png has no visible ink"
    cw, ch = (maxx - minx + 1), (maxy - miny + 1)
    assert cw >= int(w * 0.7) and ch >= int(h * 0.7), (
        f"skeleton content {cw}x{ch} too small for canvas {w}x{h}"
    )
    # Roughly centered (not stuck in a corner).
    assert minx <= w * 0.2 and miny <= h * 0.2
    assert (w - 1 - maxx) <= w * 0.2 and (h - 1 - maxy) <= h * 0.2


def test_filetype_icon_attribution_present():
    path = Path("src/creopdm/static/icons/ATTRIBUTION.txt")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "vscode-icons" in text
