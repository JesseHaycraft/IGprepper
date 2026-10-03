"""Positioning a photo inside its frame by hand: turns, tilt, zoom and slide."""

import math

import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from igprep.core import geometry as g
from igprep.core import render
from igprep.core.preview import guide_lines, make_proxy, render_preview, with_guides

SIZES = [(6000, 4000), (4000, 6000), (3000, 3000), (1234, 987), (801, 1999)]
BLUE = (40, 90, 160)


def _plan(src, placement=None, *, ratio="3:4", mode="crop", border_pct=4.0, width=1080):
    return g.plan(
        src, ratio=g.ratio_for(ratio), width=width, border_pct=border_pct,
        mode=mode, placement=placement,
    )


def _framed(img, placement=None, **kwargs):
    layout = _plan(img.size, placement, **kwargs)
    return render.render(img, layout, sharpen=0), layout


def _scene(w=1200, h=900) -> Image.Image:
    """Smooth, and different in every corner, so a misplaced crop shows."""
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for x in range(0, w, 60):
        for y in range(0, h, 60):
            draw.rectangle(
                [x, y, x + 60, y + 60],
                fill=(x * 255 // w, y * 255 // h, (x + y) * 255 // (w + h)),
            )
    return img.filter(ImageFilter.GaussianBlur(12))


def _difference(a: Image.Image, b: Image.Image) -> float:
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


def _around(tilted: g.Tilted) -> tuple[float, float, float, float]:
    """The upright box around a tilted crop."""
    cos = abs(math.cos(math.radians(tilted.degrees)))
    sin = abs(math.sin(math.radians(tilted.degrees)))
    w, h = tilted.size
    half = ((w * cos + h * sin) / 2, (w * sin + h * cos) / 2)
    cx, cy = tilted.center
    return cx - half[0], cy - half[1], cx + half[0], cy + half[1]


# --- the angle -------------------------------------------------------------

@pytest.mark.parametrize("angle", range(-179, 181))
def test_every_angle_is_quarter_turns_plus_a_small_tilt(angle):
    p = g.Placement(angle=angle)
    assert 0 <= p.turns <= 3
    assert -45 <= p.tilt <= 45
    assert (p.turns * 90 + p.tilt - angle) % 360 == 0


@pytest.mark.parametrize("angle,turns", [(0, 0), (90, 1), (180, 2), (-90, 3)])
def test_right_angles_have_no_tilt_left_over(angle, turns):
    p = g.Placement(angle=angle)
    assert (p.turns, p.tilt) == (turns, 0)
    assert not p.positioned


def test_rotation_goes_round_indefinitely():
    p = g.Placement()
    seen = []
    for _ in range(720):
        p = p.rotated(1)
        seen.append(p.angle)
    assert p.angle == 0
    assert min(seen) == -179 and max(seen) == 180
    assert g.Placement(angle=90).rotated(90).angle == 180
    assert g.Placement(angle=-90).rotated(-90).angle == 180
    assert g.Placement(angle=180).rotated(1).angle == -179


def test_rotating_keeps_the_rest_of_the_placement():
    p = g.Placement(zoom=1.5, offset_x=0.25, offset_y=-0.5).rotated(7)
    assert (p.angle, p.zoom, p.offset_x, p.offset_y) == (7, 1.5, 0.25, -0.5)


# --- what must not change ---------------------------------------------------

@pytest.mark.parametrize("src", SIZES)
@pytest.mark.parametrize("ratio", [r.key for r in g.RATIOS])
@pytest.mark.parametrize("mode", ["crop", "fit"])
def test_an_untouched_placement_changes_nothing(src, ratio, mode):
    plain = _plan(src, ratio=ratio, mode=mode)
    assert _plan(src, g.Placement(), ratio=ratio, mode=mode) == plain
    assert plain.turns == 0 and plain.tilted is None


def test_an_untouched_placement_renders_the_same_pixels():
    img = _scene()
    plain, _ = _framed(img)
    placed, _ = _framed(img, g.Placement())
    assert plain.tobytes() == placed.tobytes()


# --- quarter turns ------------------------------------------------------------

@pytest.mark.parametrize("turns", [1, 2, 3])
@pytest.mark.parametrize("mode", ["crop", "fit"])
def test_quarter_turns_match_turning_the_photo_first(turns, mode):
    img = _scene()
    # The image library counts anticlockwise, hence the minus.
    turned_first = img.rotate(-90 * turns, expand=True)
    expected, _ = _framed(turned_first, mode=mode)
    got, layout = _framed(img, g.Placement(angle=90 * turns), mode=mode)
    assert layout.turns == turns
    assert got.tobytes() == expected.tobytes()


def test_a_quarter_turn_still_shows_the_whole_photo_in_fit_mode():
    layout = _plan((6000, 4000), g.Placement(angle=90), mode="fit")
    assert layout.crop is None and layout.tilted is None
    assert layout.scaled[1] > layout.scaled[0]  # now a tall photo
    assert layout.scaled[1] == layout.box[1] or layout.scaled[0] == layout.box[0]


def test_one_turn_to_the_right_moves_the_top_left_to_the_top_right():
    img = Image.new("RGB", (800, 600), BLUE)
    img.paste((230, 30, 30), (0, 0, 200, 150))
    out, layout = _framed(img, g.Placement(angle=90), ratio="1:1", mode="fit")
    x0, y0 = layout.origin
    w, h = layout.scaled
    assert out.getpixel((x0 + w - 20, y0 + 20))[0] > 200   # red arrived here
    assert out.getpixel((x0 + 20, y0 + 20))[0] < 100       # and left here


# --- tilt ---------------------------------------------------------------------

@pytest.mark.parametrize("src", SIZES)
@pytest.mark.parametrize("ratio", [r.key for r in g.RATIOS])
@pytest.mark.parametrize("angle", [1, -1, 7, -20, 33, 45, -45, 52, 100, -133, 179])
def test_a_tilted_crop_never_leaves_the_photo(src, ratio, angle):
    for zoom, ox, oy in [(1, 0, 0), (1, 1, -1), (2.5, 1, 1), (1.3, -1, 0.4)]:
        placement = g.Placement(angle=angle, zoom=zoom, offset_x=ox, offset_y=oy)
        layout = _plan(src, placement, ratio=ratio)
        w, h = g.turned_size(src, placement.turns)
        left, top, right, bottom = _around(layout.tilted)
        assert left >= -1e-6 and top >= -1e-6
        assert right <= w + 1e-6 and bottom <= h + 1e-6
        assert layout.crop is None and layout.scaled == layout.box


@pytest.mark.parametrize("src", SIZES)
@pytest.mark.parametrize("angle", [1, -9, 30, 45])
def test_an_unzoomed_tilted_crop_is_as_large_as_it_can_be(src, angle):
    layout = _plan(src, g.Placement(angle=angle))
    left, top, right, bottom = _around(layout.tilted)
    touches_sides = abs((right - left) - src[0]) < 1e-6
    touches_ends = abs((bottom - top) - src[1]) < 1e-6
    assert touches_sides or touches_ends
    w, h = layout.tilted.size
    assert abs(w / h - layout.box[0] / layout.box[1]) < 1e-9


def test_more_tilt_means_a_smaller_crop():
    # A square crop of a square photo. (A tall crop of a wide photo is not so
    # simple: turning it towards 90 degrees eventually suits it better.)
    widths = [
        _plan((4000, 4000), g.Placement(angle=a), ratio="1:1").tilted.size[0]
        for a in (1, 5, 15, 30, 45)
    ]
    assert widths == sorted(widths, reverse=True)
    assert widths[0] < 4000
    assert widths[-1] == pytest.approx(4000 / math.sqrt(2))


def test_a_one_degree_tilt_costs_very_little():
    untilted = _plan((6000, 4000))
    tilted = _plan((6000, 4000), g.Placement(angle=1))
    assert tilted.tilted.size[0] > 0.97 * (untilted.crop[2] - untilted.crop[0])


def test_tilting_fills_the_frame_even_when_fit_was_asked_for():
    layout = _plan((6000, 4000), g.Placement(angle=3), mode="fit")
    assert layout.tilted is not None
    assert layout.scaled == layout.box


@pytest.mark.parametrize("angle", [1, -1, 5, -13, 29, 45, -45, 61, -118, 177])
@pytest.mark.parametrize("ratio", ["1:1", "3:4", "1.91:1"])
def test_no_empty_corner_ever_shows(angle, ratio):
    # Anything fetched from outside the photo would come back black.
    white = Image.new("RGB", (900, 700), (255, 255, 255))
    for zoom, ox, oy in [(1, 0, 0), (1, 1, 1), (1, -1, -1), (1.7, 1, -1)]:
        placement = g.Placement(angle=angle, zoom=zoom, offset_x=ox, offset_y=oy)
        out, _ = _framed(white, placement, ratio=ratio, border_pct=0)
        assert out.getextrema() == ((255, 255), (255, 255), (255, 255))


@pytest.mark.parametrize("angle", [3, -8, 21, -40])
def test_tilt_matches_the_image_librarys_own_rotation(angle):
    img = _scene(1200, 900)
    out, layout = _framed(img, g.Placement(angle=angle), ratio="1:1", border_pct=0)

    # The long way round: rotate the whole photo, then take the middle.
    rotated = img.rotate(-angle, resample=Image.Resampling.BICUBIC)
    w, h = layout.tilted.size
    cx, cy = img.width / 2, img.height / 2
    box = tuple(round(v) for v in (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
    expected = rotated.crop(box).resize(layout.box, Image.Resampling.LANCZOS)
    assert _difference(out, expected) < 1.0


@pytest.mark.parametrize("angle", [10, -10, 25])
def test_a_positive_tilt_turns_the_photo_clockwise(angle):
    img = Image.new("RGB", (2000, 2000), (255, 255, 255))
    ImageDraw.Draw(img).line([(0, 1000), (2000, 1000)], fill=(0, 0, 0), width=9)
    out, _ = _framed(img, g.Placement(angle=angle), ratio="1:1", border_pct=0)

    def line_at(x: int) -> float:
        column = [out.getpixel((x, y))[0] for y in range(out.height)]
        dark = [y for y, v in enumerate(column) if v < 128]
        return sum(dark) / len(dark)

    reach = 300
    drop = reach * math.tan(math.radians(angle))
    centre = (out.height - 1) / 2
    assert abs(line_at(540 + reach) - (centre + drop)) < 2.5
    assert abs(line_at(540 - reach) - (centre - drop)) < 2.5


def test_passing_through_45_degrees_is_seamless():
    # 44 is a tilt of 44; 46 is a quarter turn and a tilt of -44. The two
    # routes have to agree where they meet.
    img = _scene(1200, 900)
    frames = [
        _framed(img, g.Placement(angle=a), ratio="1:1", border_pct=0)[0]
        for a in (43, 44, 45, 46, 47)
    ]
    steps = [_difference(a, b) for a, b in zip(frames, frames[1:])]
    assert max(steps) < 1.5 * min(steps) + 0.5


# --- zoom and slide -------------------------------------------------------------

def test_zooming_in_takes_a_smaller_piece_from_the_middle():
    plain = _plan((6000, 4000), ratio="1:1")
    zoomed = _plan((6000, 4000), g.Placement(zoom=2), ratio="1:1")
    assert plain.crop == (1000, 0, 5000, 4000)
    assert zoomed.crop == (2000, 1000, 4000, 3000)
    assert zoomed.scale == pytest.approx(2 * plain.scale)


def test_sliding_reaches_the_edges_and_stops_there():
    src = (6000, 4000)
    left = _plan(src, g.Placement(offset_x=-1), ratio="1:1").crop
    right = _plan(src, g.Placement(offset_x=1), ratio="1:1").crop
    beyond = _plan(src, g.Placement(offset_x=5), ratio="1:1").crop
    assert left == (0, 0, 4000, 4000)
    assert right == (2000, 0, 6000, 4000)
    assert beyond == right


def test_zoom_never_goes_below_filling_the_frame():
    assert _plan((6000, 4000), g.Placement(zoom=0.2)).crop == _plan((6000, 4000)).crop


def test_sliding_counts_as_positioning_and_fills_the_frame():
    layout = _plan((6000, 4000), g.Placement(offset_x=0.5), mode="fit")
    assert layout.crop is not None and layout.scaled == layout.box


def test_zoom_limit_is_one_photo_pixel_per_output_pixel():
    box = _plan((6000, 4000), ratio="1:1").box
    limit = g.max_zoom((6000, 4000), box, g.Placement())
    assert limit == pytest.approx(4000 / box[0])
    at_limit = _plan((6000, 4000), g.Placement(zoom=limit), ratio="1:1")
    assert at_limit.scale == pytest.approx(1.0, abs=0.001)
    assert not _plan((6000, 4000), g.Placement(zoom=limit * 0.99), ratio="1:1").upscaled


def test_zoom_limit_shrinks_with_tilt_and_never_drops_below_one():
    box = _plan((6000, 4000), ratio="1:1").box
    assert g.max_zoom((6000, 4000), box, g.Placement(angle=20)) < g.max_zoom(
        (6000, 4000), box, g.Placement()
    )
    assert g.max_zoom((300, 200), box, g.Placement()) == 1.0


def test_zoom_limit_follows_quarter_turns():
    box = _plan((6000, 4000), ratio="1.91:1").box
    flat = g.max_zoom((6000, 4000), box, g.Placement())
    on_its_side = g.max_zoom((6000, 4000), box, g.Placement(angle=90))
    assert flat == pytest.approx(6000 / box[0])
    assert on_its_side == pytest.approx(4000 / box[0])


# --- the preview ----------------------------------------------------------------

@pytest.mark.parametrize(
    "placement",
    [
        g.Placement(angle=4),
        g.Placement(angle=-97),
        g.Placement(angle=90),
        g.Placement(angle=12, zoom=1.6, offset_x=0.5, offset_y=-1),
    ],
)
def test_preview_shows_what_will_be_saved(placement):
    img = _scene(3000, 2000)
    final, _ = _framed(img, placement)
    preview = render_preview(
        make_proxy(img), ratio=g.ratio_for("3:4"), border_pct=4.0, mode="crop",
        frame_color="#FFFFFF", placement=placement,
    )
    shrunk = final.resize(preview.size, Image.Resampling.LANCZOS)
    assert _difference(preview, shrunk) < 1.5


# --- guide lines ------------------------------------------------------------------

@pytest.mark.parametrize("ratio", [r.key for r in g.RATIOS])
def test_guide_lines_cross_at_the_centre_and_stay_on_the_photo(ratio):
    canvas = g.canvas_size(g.ratio_for(ratio), 600)
    border = g.border_px(600, 4.0)
    xs, ys = guide_lines(canvas, border)
    assert round(canvas[0] / 2) in xs and round(canvas[1] / 2) in ys
    assert all(border < x < canvas[0] - border for x in xs)
    assert all(border < y < canvas[1] - border for y in ys)
    assert len(xs) >= 5 and len(ys) >= 5
    gaps = {b - a for a, b in zip(xs, xs[1:])} | {b - a for a, b in zip(ys, ys[1:])}
    assert max(gaps) - min(gaps) <= 1  # squares


@pytest.mark.parametrize("shade", [0, 128, 255])
def test_guide_lines_show_on_any_photo_and_leave_the_frame_alone(shade):
    img = Image.new("RGB", (1200, 1600), (shade,) * 3)
    plain = render_preview(
        img, ratio=g.ratio_for("3:4"), border_pct=4.0, mode="crop",
        frame_color="#FFFFFF",
    )
    guided = with_guides(plain, 4.0)
    assert guided.size == plain.size and guided.mode == "RGB"
    assert plain.getpixel((300, 400)) == (shade,) * 3  # the original is untouched

    changed = ImageChops.difference(plain, guided).convert("L")
    assert changed.getextrema()[1] > 40
    border = g.border_px(600, 4.0)
    frame_only = changed.copy()
    frame_only.paste(0, (border, border, 600 - border, 800 - border))
    assert frame_only.getextrema() == (0, 0)
