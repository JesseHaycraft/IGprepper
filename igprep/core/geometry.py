"""Canvas, border and crop geometry.

Pure arithmetic -- no Pillow, no Qt. Everything the renderer needs to know
about *where* pixels go is decided here and handed over as a `Layout`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
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
DEFAULT_BORDER_PCT = 3.0

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


def usable_width(width) -> int:
    """`width` if it is one the app offers, otherwise the default."""
    return width if width in OUTPUT_WIDTHS else DEFAULT_OUTPUT_WIDTH


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
class Placement:
    """Where one photo sits inside its frame, when positioned by hand.

    Nothing here is in pixels, so a placement means the same thing on a small
    preview as on the full-size output. The default is the plain centred
    photo, and must stay that way: every photo nobody has touched uses it.
    """

    angle: int = 0         # whole degrees, clockwise as seen on screen
    zoom: float = 1.0      # 1 just fills the frame; larger moves in
    offset_x: float = 0.0  # -1 to 1 of the room there is to slide; 0 is centred
    offset_y: float = 0.0

    @property
    def turns(self) -> int:
        """Quarter turns clockwise, 0 to 3. These only rearrange pixels."""
        return _iround(self.angle / 90) % 4

    @property
    def tilt(self) -> int:
        """What the quarter turns leave over, from -45 to 45 degrees."""
        return self.angle - 90 * _iround(self.angle / 90)

    @property
    def positioned(self) -> bool:
        """True when the photo has to fill the frame for this to mean anything.

        A quarter turn alone does not count: a photo turned on its side can
        still be shown whole.
        """
        return bool(
            self.tilt or self.zoom != 1.0 or self.offset_x or self.offset_y
        )

    def rotated(self, degrees: int) -> "Placement":
        """Turned further by `degrees`, kept between -179 and 180."""
        angle = (self.angle + degrees + 180) % 360 - 180
        return replace(self, angle=180 if angle == -180 else angle)


@dataclass(frozen=True)
class Tilted:
    """A crop rectangle that is not square to the photo's edges."""

    center: tuple[float, float]
    size: tuple[float, float]
    degrees: int  # how far the photo appears turned clockwise


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def turned_size(src: tuple[int, int], turns: int) -> tuple[int, int]:
    return src if turns % 2 == 0 else (src[1], src[0])


def widest_tilted_crop(
    src: tuple[int, int], target_ratio: float, degrees: float
) -> float:
    """Width of the largest rectangle of `target_ratio` that fits inside `src`
    when turned by `degrees`.

    A tilted rectangle fits when the upright box around it fits, and that box
    is w*cos + h*sin wide by w*sin + h*cos tall.
    """
    cos = abs(math.cos(math.radians(degrees)))
    sin = abs(math.sin(math.radians(degrees)))
    return min(
        src[0] / (cos + sin / target_ratio),
        src[1] / (sin + cos / target_ratio),
    )


def placed_crop(
    src: tuple[int, int], box: tuple[int, int], placement: Placement
) -> tuple[tuple[int, int, int, int] | None, Tilted | None, float]:
    """The part of an already-turned photo that a placement puts in the frame.

    Returns an upright crop box or a tilted one, never both, and the scale
    from photo pixels to output pixels.
    """
    sw, sh = src
    ratio = box[0] / box[1]
    zoom = max(1.0, placement.zoom)
    slide_x = _clamp(placement.offset_x, -1.0, 1.0)
    slide_y = _clamp(placement.offset_y, -1.0, 1.0)

    if placement.tilt == 0:
        left, top, right, bottom = center_crop_rect(src, ratio)
        cw = max(1, _iround((right - left) / zoom))
        ch = max(1, _iround((bottom - top) / zoom))
        # Floor, so that an untouched placement lands on exactly the pixels
        # center_crop_rect chooses.
        left = int(math.floor((sw - cw) * (1 + slide_x) / 2))
        top = int(math.floor((sh - ch) * (1 + slide_y) / 2))
        return (left, top, left + cw, top + ch), None, box[0] / cw

    w, reach = _reach(src, ratio, placement.tilt, zoom)
    center = (sw / 2 + slide_x * reach[0], sh / 2 + slide_y * reach[1])
    return None, Tilted(center, (w, w / ratio), placement.tilt), box[0] / w


def _reach(
    src: tuple[int, int], ratio: float, tilt: float, zoom: float
) -> tuple[float, tuple[float, float]]:
    """The crop's width at this zoom, and how far its centre may sit from the
    photo's centre, across and down, before a corner leaves the photo."""
    w = widest_tilted_crop(src, ratio, tilt) / zoom
    h = w / ratio
    cos = abs(math.cos(math.radians(tilt)))
    sin = abs(math.sin(math.radians(tilt)))
    return w, (
        max(0.0, (src[0] - (w * cos + h * sin)) / 2),
        max(0.0, (src[1] - (w * sin + h * cos)) / 2),
    )


def _slide(distance: float, reach: float) -> float:
    """A distance from the centre, as a share of the room there is."""
    return _clamp(distance / reach, -1.0, 1.0) if reach > 1e-9 else 0.0


def _crop_centre(
    turned: tuple[int, int], box: tuple[int, int], placement: Placement
) -> tuple[float, float]:
    _, reach = _reach(
        turned, box[0] / box[1], placement.tilt, max(1.0, placement.zoom)
    )
    return (
        turned[0] / 2 + _clamp(placement.offset_x, -1.0, 1.0) * reach[0],
        turned[1] / 2 + _clamp(placement.offset_y, -1.0, 1.0) * reach[1],
    )


def _centred_on(
    turned: tuple[int, int],
    box: tuple[int, int],
    placement: Placement,
    centre: tuple[float, float],
) -> Placement:
    """The placement, slid so its crop is centred on `centre` or as near as
    the photo's edges allow."""
    _, reach = _reach(
        turned, box[0] / box[1], placement.tilt, max(1.0, placement.zoom)
    )
    return replace(
        placement,
        offset_x=_slide(centre[0] - turned[0] / 2, reach[0]),
        offset_y=_slide(centre[1] - turned[1] / 2, reach[1]),
    )


def turn_point(
    src: tuple[int, int], turns: int, point: tuple[float, float]
) -> tuple[float, float]:
    """Where a point of the photo ends up after quarter turns clockwise."""
    x, y = point
    turns %= 4
    if turns == 1:
        return src[1] - y, x
    if turns == 2:
        return src[0] - x, src[1] - y
    if turns == 3:
        return y, src[0] - x
    return x, y


def unturn_point(
    src: tuple[int, int], turns: int, point: tuple[float, float]
) -> tuple[float, float]:
    """The reverse of `turn_point`: `src` is still the photo before turning."""
    return turn_point(turned_size(src, turns), -turns, point)


def within_limits(
    src: tuple[int, int], box: tuple[int, int], placement: Placement
) -> Placement:
    """The placement with its zoom brought inside what the photo allows.

    The limit moves when the ratio, the border or the tilt changes, so a zoom
    that was fine a moment ago may not be now.
    """
    zoom = _clamp(placement.zoom, 1.0, max_zoom(src, box, placement))
    return placement if zoom == placement.zoom else replace(placement, zoom=zoom)


def moved(
    src: tuple[int, int],
    box: tuple[int, int],
    placement: Placement,
    *,
    before: tuple[float, float],
    after: tuple[float, float],
    spread: float = 1.0,
) -> Placement:
    """The placement after a drag or a pinch.

    A finger, or the midpoint between two, went from `before` to `after`.
    Both are measured from the centre of the frame, in pixels of `box`.
    `spread` is how much further apart two fingers ended than they began.
    Whatever part of the photo was under `before` is put under `after`, as
    nearly as the photo's edges and the zoom limit allow.
    """
    turned = turned_size(src, placement.turns)
    ratio = box[0] / box[1]
    theta = math.radians(placement.tilt)
    cos, sin = math.cos(theta), math.sin(theta)

    def on_photo(v: tuple[float, float], scale: float) -> tuple[float, float]:
        # The photo is shown turned clockwise, so turn the other way to get
        # from a distance on the output to a distance on the photo.
        return (v[0] * cos + v[1] * sin) / scale, (-v[0] * sin + v[1] * cos) / scale

    zoom = max(1.0, placement.zoom)
    w, _ = _reach(turned, ratio, placement.tilt, zoom)
    centre = _crop_centre(turned, box, placement)
    step = on_photo(before, box[0] / w)
    held = (centre[0] + step[0], centre[1] + step[1])

    zoom = _clamp(zoom * spread, 1.0, max_zoom(src, box, placement))
    w, _ = _reach(turned, ratio, placement.tilt, zoom)
    step = on_photo(after, box[0] / w)
    return _centred_on(
        turned, box, replace(placement, zoom=zoom),
        (held[0] - step[0], held[1] - step[1]),
    )


def turned_further(
    src: tuple[int, int], box: tuple[int, int], placement: Placement, degrees: int
) -> Placement:
    """Rotated by `degrees`, keeping the same part of the photo in the middle.

    Sliding is measured along the photo's sides, and which side is which
    changes with every quarter turn. Without this, a photo that had been
    moved off-centre would jump as it passed 45 degrees.
    """
    before = turned_size(src, placement.turns)
    spot = unturn_point(src, placement.turns, _crop_centre(before, box, placement))

    turned = within_limits(src, box, placement.rotated(degrees))
    if not (placement.offset_x or placement.offset_y):
        return turned  # centred stays exactly centred
    return _centred_on(
        turned_size(src, turned.turns), box, turned,
        turn_point(src, turned.turns, spot),
    )


def max_zoom(
    src: tuple[int, int], box: tuple[int, int], placement: Placement
) -> float:
    """How far in a photo can go before it would have to be enlarged.

    At this zoom one pixel of the photo becomes one pixel of the output. A
    photo too small to fill the frame at all gets 1: no zooming in.
    """
    turned = turned_size(src, placement.turns)
    widest = widest_tilted_crop(turned, box[0] / box[1], placement.tilt)
    return max(1.0, widest / box[0])


@dataclass(frozen=True)
class Layout:
    """Everything the renderer needs, fully resolved."""

    canvas: tuple[int, int]
    border: int
    box: tuple[int, int]
    crop: tuple[int, int, int, int] | None  # None in fit mode, and when tilted
    scaled: tuple[int, int]
    origin: tuple[int, int]
    scale: float
    turns: int = 0                # quarter turns to make before anything else
    tilted: Tilted | None = None  # the crop, when it is not square to the photo

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
    placement: Placement | None = None,
) -> Layout:
    """Resolve a source size and settings into a concrete `Layout`.

    `src` is the photo as loaded. Any quarter turns in `placement` are taken
    into account here, and recorded in the layout for the renderer to make.
    """
    if src[0] <= 0 or src[1] <= 0:
        raise GeometryError(f"invalid source size {src}")
    if mode not in ("crop", "fit"):
        raise GeometryError(f"unknown mode {mode!r}")

    placement = placement or Placement()
    src = turned_size(src, placement.turns)
    canvas = canvas_size(ratio, width)
    border = border_px(canvas[0], border_pct)
    box = photo_box(canvas, border)

    tilted = None
    # A photo shown whole has no position to adjust, so one that has been
    # tilted, zoomed or slid fills the frame whatever was asked for.
    if mode == "crop" or placement.positioned:
        crop, tilted, scale = placed_crop(src, box, placement)
        scaled = box
    else:
        crop = None
        scaled = fit_size(src, box)
        scale = scaled[0] / src[0]

    return Layout(
        canvas=canvas,
        border=border,
        box=box,
        crop=crop,
        scaled=scaled,
        origin=center_origin(canvas, scaled),
        scale=scale,
        turns=placement.turns,
        tilted=tilted,
    )
