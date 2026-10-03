"""Colour conversion by Android itself.

The image library's Android build has no colour engine, so a photo tagged
with Display P3 or AdobeRGB cannot be converted to sRGB in Python on a phone.
Android's own decoder can: asked for sRGB, it reads the embedded profile and
converts as it decodes. This hands the result to the pipeline as an ordinary
image that needs no further colour work.

This module only imports on Android.
"""

from __future__ import annotations

from java import jclass
from java.nio import ByteBuffer
from PIL import Image

BitmapFactory = jclass("android.graphics.BitmapFactory")
BitmapOptions = jclass("android.graphics.BitmapFactory$Options")
BitmapConfig = jclass("android.graphics.Bitmap$Config")
ColorSpace = jclass("android.graphics.ColorSpace")
ColorSpaceNamed = jclass("android.graphics.ColorSpace$Named")


def decode_to_srgb(data: bytes) -> Image.Image:
    """Decode image bytes into an sRGB image with no profile attached."""
    options = BitmapOptions()
    options.inPreferredConfig = BitmapConfig.ARGB_8888
    options.inPreferredColorSpace = ColorSpace.get(ColorSpaceNamed.SRGB)
    options.inPremultiplied = False

    bitmap = BitmapFactory.decodeByteArray(data, 0, len(data), options)
    if bitmap is None:
        raise ValueError("Android could not decode that image")
    try:
        width, height = bitmap.getWidth(), bitmap.getHeight()
        buffer = ByteBuffer.allocate(bitmap.getByteCount())
        bitmap.copyPixelsToBuffer(buffer)
        raw = bytes(buffer.array())
    finally:
        bitmap.recycle()

    # ARGB_8888 is stored as R, G, B, A in memory, despite the name.
    image = Image.frombuffer("RGBA", (width, height), raw, "raw", "RGBA", 0, 1)
    return image.convert("RGB")
