"""Decoding a photo, with the image library's own colour engine."""

from __future__ import annotations

import io

from PIL import Image

from igprep.core import color


def decode_to_srgb(data: bytes) -> Image.Image:
    """Image bytes in, an sRGB image out. Rotation is left to the caller, as
    it is on Android."""
    picture = Image.open(io.BytesIO(data))
    picture.load()
    return color.to_srgb(picture).convert("RGB")
