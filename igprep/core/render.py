"""Resize, sharpen, frame and encode.

The order of operations in `render` is deliberate; see SPEC.md section 2.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from . import color
from .geometry import Layout

RESAMPLE = Image.Resampling.LANCZOS

# Downscaling always softens. A small radius sharpens the detail the resample
# blurred without producing visible edge halos at 1080px.
SHARPEN_RADIUS = 0.8
SHARPEN_THRESHOLD = 2
DEFAULT_SHARPEN = 30
# At or below this scale factor the requested amount is applied in full.
SHARPEN_FULL_AT = 0.5

DEFAULT_QUALITY = 95
DEFAULT_FRAME_COLOR = "#FFFFFF"


def load(path: str | Path) -> Image.Image:
    """Open an image with its EXIF orientation already applied."""
    img = Image.open(path)
    img.load()
    # Must happen before any geometry is computed, or portrait shots planned
    # from a landscape-shaped buffer come out cropped along the wrong axis.
    return ImageOps.exif_transpose(img) or img


def sharpen_percent(amount: int, scale: float) -> int:
    """Scale the sharpening amount by how far the image was downscaled.

    A photo that barely shrank was barely softened and needs little help; one
    reduced 5x needs the full amount. No downscale means no sharpening at all.
    """
    if amount <= 0 or scale >= 1.0:
        return 0
    factor = min(1.0, (1.0 - scale) / (1.0 - SHARPEN_FULL_AT))
    return int(round(amount * factor))


def render(
    img: Image.Image,
    layout: Layout,
    *,
    frame_color: str = DEFAULT_FRAME_COLOR,
    sharpen: int = DEFAULT_SHARPEN,
) -> Image.Image:
    """Turn a loaded source image into the finished, framed canvas."""
    img = color.to_srgb(img)
    img = color.flatten(img, frame_color)

    if layout.crop is not None:
        img = img.crop(layout.crop)
    if img.size != layout.scaled:
        img = img.resize(layout.scaled, RESAMPLE)

    percent = sharpen_percent(sharpen, layout.scale)
    if percent:
        img = img.filter(
            ImageFilter.UnsharpMask(SHARPEN_RADIUS, percent, SHARPEN_THRESHOLD)
        )

    canvas = Image.new("RGB", layout.canvas, frame_color)
    canvas.paste(img, layout.origin)
    return canvas


def save_jpeg(
    img: Image.Image, path: str | Path, quality: int = DEFAULT_QUALITY
) -> None:
    """Write the finished canvas.

    4:4:4 chroma matters because Instagram recompresses on upload; handing it
    4:2:0 compounds colour-edge artifacts through a second generation of loss.
    """
    img.save(
        path, "JPEG",
        quality=quality,
        subsampling=0,        # 4:4:4
        optimize=True,
        progressive=False,
        icc_profile=color.SRGB_BYTES,
    )
