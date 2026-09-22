"""Canvas, border and crop geometry.

Pure arithmetic -- no Pillow, no Qt. Everything the renderer needs to know
about *where* pixels go is decided here and handed over as a `Layout`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Mode = Literal["crop", "fit"]


@dataclass(frozen=True)
class AspectRatio:
    key: str
    label: str
    rw: int
    rh: int
    note: str = ""

    @property
    def value(self) -> float:
        """Width divided by height."""
        return self.rw / self.rh


# Landscape is published as 1080x566, which is exactly 540:283. A clean 1.91:1
# would give 565, so we encode the published dimensions rather than the
# rounded-off ratio everyone quotes.
RATIOS: tuple[AspectRatio, ...] = (
    AspectRatio("1:1", "Square", 1, 1),
    AspectRatio("4:5", "Portrait", 4, 5, "Tallest the feed displays"),
    AspectRatio("3:4", "Portrait tall", 3, 4, "Uncropped in feed and grid"),
    AspectRatio("1.91:1", "Landscape", 540, 283, "Widest allowed"),
    AspectRatio("9:16", "Story / Reel", 9, 16, "Not a feed format"),
)

RATIOS_BY_KEY: dict[str, AspectRatio] = {r.key: r for r in RATIOS}

DEFAULT_RATIO = "3:4"
OUTPUT_WIDTHS = (1080, 1440)
DEFAULT_OUTPUT_WIDTH = 1080
DEFAULT_BORDER_PCT = 4.0

# Instagram's profile-grid thumbnail ratio.
GRID_RW, GRID_RH = 3, 4

# A photo box narrower than this is not a photo any more.
MIN_PHOTO_PX = 16


class GeometryError(ValueError):
    """Requested geometry cannot be satisfied."""


def _iround(x: float) -> int:
    """Round half away from zero, unlike round()'s banker's rounding."""
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def ratio_for(key: str) -> AspectRatio:
    try:
        return RATIOS_BY_KEY[key]
    except KeyError:
        raise GeometryError(f"unknown aspect ratio {key!r}") from None


def canvas_size(ratio: AspectRatio, width: int) -> tuple[int, int]:
    """Full output canvas, frame included."""
    if width <= 0:
        raise GeometryError(f"output width must be positive, got {width}")
    return width, _iround(width * ratio.rh / ratio.rw)


def border_px(canvas_w: int, border_pct: float) -> int:
    """Border thickness in pixels.

    Measured against canvas *width* so that every ratio gets an identical
    border at a given output width -- that visual consistency across the grid
    is the whole point of the tool.
    """
    if border_pct < 0:
        raise GeometryError(f"border must not be negative, got {border_pct}")
    return _iround(canvas_w * border_pct / 100.0)


def max_border_pct(ratio: AspectRatio, width: int) -> float:
    """Largest border percentage that still leaves a usable photo box.

    The short edge is the binding constraint, so wide ratios cap much lower
    than tall ones.
    """
    cw, ch = canvas_size(ratio, width)
    return ((min(cw, ch) - MIN_PHOTO_PX) / 2.0) / cw * 100.0


def photo_box(canvas: tuple[int, int], border: int) -> tuple[int, int]:
    """The area left for the photo once the frame is inset."""
    w = canvas[0] - 2 * border
    h = canvas[1] - 2 * border
    if w < MIN_PHOTO_PX or h < MIN_PHOTO_PX:
        raise GeometryError(
            f"border of {border}px leaves only {w}x{h} for the photo"
        )
    return w, h


def center_crop_rect(
    src: tuple[int, int], target_ratio: float
) -> tuple[int, int, int, int]:
    """Largest centered rect inside `src` with the given width/height ratio.

    Returns a PIL-style (left, top, right, bottom) box.
    """
    sw, sh = src
    if sw <= 0 or sh <= 0:
        raise GeometryError(f"invalid source size {src}")
    if target_ratio <= 0:
        raise GeometryError(f"invalid target ratio {target_ratio}")

    if sw / sh > target_ratio:
        cw, ch = _iround(sh * target_ratio), sh  # too wide: take from the sides
    else:
        cw, ch = sw, _iround(sw / target_ratio)  # too tall: take from top/bottom

    cw = max(1, min(cw, sw))
    ch = max(1, min(ch, sh))
    left = (sw - cw) // 2
    top = (sh - ch) // 2
    return left, top, left + cw, top + ch


def fit_size(src: tuple[int, int], box: tuple[int, int]) -> tuple[int, int]:
    """Largest size with `src`'s ratio that fits inside `box`."""
    scale = min(box[0] / src[0], box[1] / src[1])
    w = max(1, min(_iround(src[0] * scale), box[0]))
    h = max(1, min(_iround(src[1] * scale), box[1]))
    return w, h


def center_origin(
    outer: tuple[int, int], inner: tuple[int, int]
) -> tuple[int, int]:
    return (outer[0] - inner[0]) // 2, (outer[1] - inner[1]) // 2


def grid_crop_rect(canvas: tuple[int, int]) -> tuple[int, int, int, int]:
    """What Instagram's 3:4 profile-grid thumbnail keeps of a finished post.

    3:4 is taller than every feed ratio except 9:16, so this is a *side* crop
    for 1:1 and 4:5, a no-op for 3:4, and a top/bottom crop for 9:16.
    """
    return center_crop_rect(canvas, GRID_RW / GRID_RH)


@dataclass(frozen=True)
class Layout:
    """Everything the renderer needs, fully resolved."""

    canvas: tuple[int, int]
    border: int
    box: tuple[int, int]
    crop: tuple[int, int, int, int] | None  # None in fit mode
    scaled: tuple[int, int]
    origin: tuple[int, int]
    scale: float

    @property
    def upscaled(self) -> bool:
        """True when the source is too small to fill its box."""
        return self.scale > 1.0


def plan(
    src: tuple[int, int],
    *,
    ratio: AspectRatio,
    width: int = DEFAULT_OUTPUT_WIDTH,
    border_pct: float = DEFAULT_BORDER_PCT,
    mode: Mode = "crop",
) -> Layout:
    """Resolve a source size and settings into a concrete `Layout`."""
    if src[0] <= 0 or src[1] <= 0:
        raise GeometryError(f"invalid source size {src}")

    canvas = canvas_size(ratio, width)
    border = border_px(canvas[0], border_pct)
    box = photo_box(canvas, border)

    if mode == "crop":
        crop = center_crop_rect(src, box[0] / box[1])
        scaled = box
        scale = box[0] / (crop[2] - crop[0])
    elif mode == "fit":
        crop = None
        scaled = fit_size(src, box)
        scale = scaled[0] / src[0]
    else:
        raise GeometryError(f"unknown mode {mode!r}")

    return Layout(
        canvas=canvas,
        border=border,
        box=box,
        crop=crop,
        scaled=scaled,
        origin=center_origin(canvas, scaled),
        scale=scale,
    )
