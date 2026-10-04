"""Resize, sharpen, frame and encode.

The order of operations in `render` is deliberate; see SPEC.md section 2.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

from . import color
from .geometry import Layout, Tilted

RESAMPLE = Image.Resampling.LANCZOS

# Quarter turns clockwise. The image library counts the other way round.
_TURN = {
    1: Image.Transpose.ROTATE_270,
    2: Image.Transpose.ROTATE_180,
    3: Image.Transpose.ROTATE_90,
}

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
    # In place: a photo already upright is then left alone, not copied.
    ImageOps.exif_transpose(img, in_place=True)
    return img


def sharpen_percent(amount: int, scale: float) -> int:
    """Scale the sharpening amount by how far the image was downscaled.

    A photo that barely shrank was barely softened and needs little help; one
    reduced 5x needs the full amount. No downscale means no sharpening at all.
    """
    if amount <= 0 or scale >= 1.0:
        return 0
    factor = min(1.0, (1.0 - scale) / (1.0 - SHARPEN_FULL_AT))
    return int(round(amount * factor))


def _cut_tilted(
    img: Image.Image,
    tilted: Tilted,
    size: tuple[int, int] | None = None,
    resample: Image.Resampling = Image.Resampling.BICUBIC,
) -> Image.Image:
    """Lift a tilted rectangle out of the photo, upright.

    Left to itself this works at the photo's own resolution. That is the only
    resampling a tilt costs, and it happens before the downscale rather than
    after, so the softening it causes is shrunk away with everything else.

    Given a `size`, it goes straight there in one step: quicker and rougher.
    """
    w, h = tilted.size
    out = size or (max(1, round(w)), max(1, round(h)))
    # Photo pixels per output pixel: at full size, 1 but for the rounding.
    step_x, step_y = w / out[0], h / out[1]
    theta = math.radians(tilted.degrees)
    cos, sin = math.cos(theta), math.sin(theta)

    # Where each output point comes from in the photo. The photo is to appear
    # turned clockwise, so the rectangle is turned the other way to fetch it.
    a, b = cos * step_x, sin * step_y
    d, e = -sin * step_x, cos * step_y
    c = tilted.center[0] - a * out[0] / 2 - b * out[1] / 2
    f = tilted.center[1] - d * out[0] / 2 - e * out[1] / 2
    return img.transform(
        out, Image.Transform.AFFINE, (a, b, c, d, e, f), resample=resample
    )


def place(img: Image.Image, layout: Layout) -> Image.Image:
    """Turn the photo and cut out the part of it the layout calls for."""
    if layout.turns:
        img = img.transpose(_TURN[layout.turns])
    if layout.tilted is not None:
        return _cut_tilted(img, layout.tilted)
    if layout.crop is not None:
        return img.crop(layout.crop)
    return img


def place_quickly(img: Image.Image, layout: Layout) -> Image.Image:
    """The same part of the photo as `place`, at its final size, in one step.

    For drawing while a finger is moving, where keeping up matters more than
    the last of the sharpness.
    """
    if layout.turns:
        img = img.transpose(_TURN[layout.turns])
    tilted = layout.tilted
    if tilted is None and layout.crop is not None:
        left, top, right, bottom = layout.crop
        tilted = Tilted(
            ((left + right) / 2, (top + bottom) / 2), (right - left, bottom - top), 0
        )
    if tilted is None:
        return img.resize(layout.scaled, Image.Resampling.BILINEAR)
    return _cut_tilted(img, tilted, layout.scaled, Image.Resampling.BILINEAR)


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

    img = place(img, layout)
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
