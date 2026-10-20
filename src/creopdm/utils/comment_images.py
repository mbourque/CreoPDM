"""Validate, normalise and thumbnail an image attached to a comment.

Only PNG, JPEG, GIF and WebP are accepted (never SVG: it can carry script). The bytes are decoded
and re-encoded here, which rejects corrupt files, strips metadata (EXIF / GPS) and fixes the
content type regardless of what the upload claimed.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES_PER_COMMENT = 4
MAX_LONG_SIDE = 2400
MAX_PIXELS = 40_000_000  # decompression-bomb guard, checked before decoding
THUMB_SIDE = 220

_FORMATS = {
    "PNG": ("image/png", "png"),
    "JPEG": ("image/jpeg", "jpg"),
    "GIF": ("image/gif", "gif"),
    "WEBP": ("image/webp", "webp"),
}


class CommentImageError(ValueError):
    """The upload is not an acceptable image (message is safe to show the user)."""


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    thumb: bytes
    content_type: str
    extension: str
    width: int
    height: int
    sha256: str


def _encode(image, fmt: str) -> bytes:
    buf = io.BytesIO()
    if fmt == "JPEG":
        image.convert("RGB").save(buf, "JPEG", quality=88, optimize=True)
    elif fmt == "PNG":
        image.save(buf, "PNG", optimize=True)
    elif fmt == "WEBP":
        image.save(buf, "WEBP", quality=88)
    else:
        image.save(buf, "GIF")
    return buf.getvalue()


def process_image(raw: bytes) -> ProcessedImage:
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as exc:  # the server still starts without Pillow; only images are off
        raise CommentImageError("Image upload is not available: Pillow is not installed on the server.") from exc
    if not raw:
        raise CommentImageError("The image is empty.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise CommentImageError("An image can be at most 5 MB.")
    try:
        probe = Image.open(io.BytesIO(raw))
        fmt = (probe.format or "").upper()
        if fmt not in _FORMATS:
            raise CommentImageError("Only PNG, JPEG, GIF and WebP images can be attached.")
        width, height = probe.size
        if width < 1 or height < 1 or width * height > MAX_PIXELS:
            raise CommentImageError("That image is too large.")
        probe.load()
        image = ImageOps.exif_transpose(probe) if fmt != "GIF" else probe
    except CommentImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise CommentImageError("That file is not a valid image.") from exc

    image = image.copy()
    if max(image.size) > MAX_LONG_SIDE:
        image.thumbnail((MAX_LONG_SIDE, MAX_LONG_SIDE))
    if fmt == "GIF":
        # A GIF is stored as one still frame: animation adds nothing to a review comment.
        image = image.convert("RGBA")
        fmt = "PNG"
    data = _encode(image, fmt)
    thumb_img = image.copy()
    thumb_img.thumbnail((THUMB_SIDE, THUMB_SIDE))
    thumb_fmt = "PNG" if fmt in {"PNG", "WEBP"} else "JPEG"
    thumb = _encode(thumb_img, thumb_fmt)
    content_type, extension = _FORMATS[fmt]
    return ProcessedImage(
        data=data,
        thumb=thumb,
        content_type=content_type,
        extension=extension,
        width=image.size[0],
        height=image.size[1],
        sha256=hashlib.sha256(data).hexdigest(),
    )


def thumb_content_type(content_type: str) -> str:
    return "image/png" if content_type in {"image/png", "image/webp"} else "image/jpeg"
