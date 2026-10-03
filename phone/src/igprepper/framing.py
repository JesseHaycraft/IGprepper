"""Framing a photo on the phone.

The work itself is the desktop pipeline's, unchanged. What differs is the
first step: a phone's build of the image library cannot convert colour, so
the photo is decoded by a `convert` function supplied by the caller -- on
Android, the system decoder, which converts to sRGB as it decodes. That
decoder ignores the camera's rotation flag, so the rotation is applied here.

Nothing in this module is Android-specific; the desktop test suite runs it.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

from igprep.core import geometry as g
from igprep.core import naming, render
from igprep.core.preview import make_proxy, render_preview
from igprep.core.settings import Framing

OUTPUT_WIDTH = 1080
SHARPEN = 30
QUALITY = 95
_ORIENTATION_TAG = 274

# What to do for each value of the EXIF orientation flag. 1 means upright.
_UPRIGHT = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


def orientation_of(data: bytes) -> int:
    """The rotation flag stored in the file, read without decoding the pixels."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            return int(image.getexif().get(_ORIENTATION_TAG, 1))
    except Exception:
        return 1


def upright(image: Image.Image, orientation: int) -> Image.Image:
    operation = _UPRIGHT.get(orientation)
    return image.transpose(operation) if operation is not None else image


def prepare(data: bytes, convert) -> Image.Image:
    """Image bytes in, an upright sRGB image out."""
    image = convert(data)
    image = upright(image, orientation_of(data))
    return image if image.mode == "RGB" else image.convert("RGB")


@dataclass
class Framed:
    jpeg: bytes
    source_size: tuple[int, int]
    canvas: tuple[int, int]
    border: int
    upscaled: bool


def frame(image: Image.Image, framing: Framing, width: int = OUTPUT_WIDTH) -> Framed:
    """Run a prepared image through the pipeline and encode the result."""
    layout = g.plan(
        image.size,
        ratio=framing.aspect(),
        width=width,
        border_pct=framing.border_pct,
        mode=framing.mode,
    )
    canvas = render.render(
        image, layout, frame_color=framing.frame_color, sharpen=SHARPEN
    )
    buffer = io.BytesIO()
    render.save_jpeg(canvas, buffer, quality=QUALITY)
    return Framed(
        jpeg=buffer.getvalue(),
        source_size=image.size,
        canvas=layout.canvas,
        border=layout.border,
        upscaled=layout.upscaled,
    )


def preview(image: Image.Image, framing: Framing) -> Image.Image:
    """A small scale model of the framed result, for the screen."""
    return render_preview(
        make_proxy(image),
        ratio=framing.aspect(),
        border_pct=framing.border_pct,
        mode=framing.mode,
        frame_color=framing.frame_color,
    )


def output_name(source_name: str, taken) -> str:
    """The desktop's default name for a framed photo, kept clear of `taken`.

    Checked here rather than left to the storage: Google Drive will happily
    hold two files with the same name in one folder.
    """
    stem = source_name.rsplit(".", 1)[0] if "." in source_name else source_name
    base = naming.render(naming.DEFAULT_TEMPLATE, name=stem or "photo")
    taken = {name.lower() for name in taken}
    candidate, number = f"{base}.jpg", 1
    while candidate.lower() in taken:
        number += 1
        candidate = f"{base}_{number}.jpg"
    return candidate
