"""Preview composition, shared by the desktop and phone apps.

Full-size rendering is too slow to run on every slider movement, so previews
are composed from a small proxy of the photo at a reduced canvas width.
Because all the geometry is proportional, a preview laid out at 600px wide is
a faithful scale model of the 1080px output.

This lives in core, free of any UI toolkit, so that both apps draw the same
preview from the same code.
"""

from __future__ import annotations

from functools import lru_cache

from PIL import Image, ImageDraw

from . import geometry as g
from .render import RESAMPLE, place, place_quickly

PREVIEW_CANVAS_WIDTH = 600
PROXY_MAX = 1600
# A smaller copy still, for redrawing while a finger is on the photo.
QUICK_PROXY_MAX = 900

# Guide lines for levelling a photo: this many squares across the short side.
GUIDE_CELLS = 6
GUIDE_DASH = 6


def make_proxy(image: Image.Image, max_side: int = PROXY_MAX) -> Image.Image:
    """A copy of `image` no larger than `max_side` on its longest edge."""
    proxy = image.copy()
    proxy.thumbnail((max_side, max_side), RESAMPLE)
    return proxy


def render_preview(
    proxy: Image.Image,
    *,
    ratio: g.AspectRatio,
    border_pct: float,
    mode: str,
    frame_color: str,
    width: int = PREVIEW_CANVAS_WIDTH,
    placement: g.Placement | None = None,
    quick: bool = False,
) -> Image.Image:
    """Compose the proxy into a scale model of the finished canvas.

    `quick` gives up a little sharpness for speed: the same picture, in the
    same place, drawn fast enough to follow a finger.
    """
    layout = g.plan(
        proxy.size,
        ratio=ratio,
        width=width,
        border_pct=border_pct,
        mode=mode,
        placement=placement,
    )
    if quick:
        img = place_quickly(proxy, layout)
    else:
        img = place(proxy, layout)
        if img.size != layout.scaled:
            img = img.resize(layout.scaled, RESAMPLE)

    canvas = Image.new("RGB", layout.canvas, frame_color)
    canvas.paste(img, layout.origin)
    return canvas


def guide_lines(size: tuple[int, int], border: int) -> tuple[list[int], list[int]]:
    """Where the guide lines go: x positions, then y positions.

    Squares, counted out from the middle, so that one line of each kind runs
    through the exact centre whatever the shape of the frame.
    """
    left, top, right, bottom = border, border, size[0] - border, size[1] - border
    spacing = min(right - left, bottom - top) / GUIDE_CELLS

    def along(low: int, high: int) -> list[int]:
        middle = (low + high) / 2
        reach = int((high - low) / 2 / spacing)
        lines = (round(middle + n * spacing) for n in range(-reach, reach + 1))
        return [p for p in lines if low < p < high]

    return along(left, right), along(top, bottom)


@lru_cache(maxsize=8)
def _guides(size: tuple[int, int], border: int) -> Image.Image:
    """The guide lines alone, on nothing, for a preview of this size.

    They depend only on the shape of the frame, and are wanted again on every
    redraw while a photo is being turned, so they are kept once drawn.
    """
    left, top = border, border
    right, bottom = size[0] - border - 1, size[1] - border - 1
    xs, ys = guide_lines(size, border)

    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    dark, light = (0, 0, 0, 120), (255, 255, 255, 235)
    for x in xs:
        draw.line([(x, top), (x, bottom)], fill=dark)
        for y in range(top, bottom + 1, 2 * GUIDE_DASH):
            draw.line([(x, y), (x, min(y + GUIDE_DASH - 1, bottom))], fill=light)
    for y in ys:
        draw.line([(left, y), (right, y)], fill=dark)
        for x in range(left, right + 1, 2 * GUIDE_DASH):
            draw.line([(x, y), (min(x + GUIDE_DASH - 1, right), y)], fill=light)
    return overlay


def with_guides(preview: Image.Image, border_pct: float) -> Image.Image:
    """A copy of a preview with dashed guide lines over the photo.

    Each line is dark with light dashes on it, so it shows against sky and
    shadow alike.
    """
    overlay = _guides(preview.size, g.border_px(preview.width, border_pct))
    return Image.alpha_composite(preview.convert("RGBA"), overlay).convert("RGB")
