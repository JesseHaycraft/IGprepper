"""Preview composition, shared by the desktop and phone apps.

Full-size rendering is too slow to run on every slider movement, so previews
are composed from a small proxy of the photo at a reduced canvas width.
Because all the geometry is proportional, a preview laid out at 600px wide is
a faithful scale model of the 1080px output.

This lives in core, free of any UI toolkit, so that both apps draw the same
preview from the same code.
"""

from __future__ import annotations

from PIL import Image

from . import geometry as g

PREVIEW_CANVAS_WIDTH = 600
PROXY_MAX = 1600


def make_proxy(image: Image.Image, max_side: int = PROXY_MAX) -> Image.Image:
    """A copy of `image` no larger than `max_side` on its longest edge."""
    proxy = image.copy()
    proxy.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return proxy


def render_preview(
    proxy: Image.Image,
    *,
    ratio: g.AspectRatio,
    border_pct: float,
    mode: str,
    frame_color: str,
    width: int = PREVIEW_CANVAS_WIDTH,
) -> Image.Image:
    """Compose the proxy into a scale model of the finished canvas."""
    layout = g.plan(
        proxy.size,
        ratio=ratio,
        width=width,
        border_pct=border_pct,
        mode=mode,
    )
    img = proxy
    if layout.crop is not None:
        img = img.crop(layout.crop)
    if img.size != layout.scaled:
        img = img.resize(layout.scaled, Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", layout.canvas, frame_color)
    canvas.paste(img, layout.origin)
    return canvas
