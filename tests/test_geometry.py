import pytest

from igprep.core import geometry as g


def test_published_canvas_sizes():
    """The dimensions everyone quotes, at the default output width."""
    expected = {
        "1:1": (1080, 1080),
        "4:5": (1080, 1350),
        "3:4": (1080, 1440),
        "1.91:1": (1080, 566),
        "9:16": (1080, 1920),
    }
    for key, size in expected.items():
        assert g.canvas_size(g.ratio_for(key), 1080) == size


def test_border_is_identical_across_ratios():
    """The entire point of measuring the border against width."""
    borders = {
        g.border_px(g.canvas_size(r, 1080)[0], 4.0) for r in g.RATIOS
    }
    assert borders == {43}


def test_border_scales_with_output_width():
    assert g.border_px(1440, 4.0) == 58
    assert g.border_px(1080, 0.0) == 0


def test_photo_box_insets_all_four_sides():
    assert g.photo_box((1080, 1440), 43) == (994, 1354)


def test_photo_box_rejects_a_border_that_swallows_the_photo():
    with pytest.raises(g.GeometryError):
        g.photo_box((1080, 566), 280)


def test_max_border_is_bound_by_the_short_edge():
    """Landscape caps far lower than portrait, because 566px is the limit."""
    assert g.max_border_pct(g.ratio_for("1.91:1"), 1080) < 26
    assert g.max_border_pct(g.ratio_for("3:4"), 1080) > 49


@pytest.mark.parametrize(
    "key, expected",
    [
        ("3:4", (0, 0, 1080, 1440)),       # the grid ratio itself: untouched
        ("4:5", (33, 0, 1046, 1350)),      # sides trimmed, full height kept
        ("1:1", (135, 0, 945, 1080)),      # sides trimmed harder
        ("9:16", (0, 240, 1080, 1680)),    # taller than 3:4: top and bottom go
    ],
)
def test_grid_crop_direction(key, expected):
    """3:4 is taller than every feed ratio, so feed posts lose their sides."""
    canvas = g.canvas_size(g.ratio_for(key), 1080)
    assert g.grid_crop_rect(canvas) == expected


def test_crop_mode_fills_the_box_exactly():
    layout = g.plan((6000, 4000), ratio=g.ratio_for("3:4"), mode="crop")
    assert layout.canvas == (1080, 1440)
    assert layout.border == 43
    assert layout.box == (994, 1354)
    assert layout.scaled == layout.box
    assert layout.origin == (43, 43)


def test_crop_takes_from_the_long_axis_only():
    crop = g.center_crop_rect((6000, 4000), 1.0)
    assert crop == (1000, 0, 5000, 4000)  # square from a landscape frame


def test_center_crop_is_symmetric():
    left, top, right, bottom = g.center_crop_rect((1001, 400), 1.0)
    assert left == (1001 - 400) // 2
    assert right - left == 400


def test_fit_mode_preserves_source_ratio():
    layout = g.plan((6000, 4000), ratio=g.ratio_for("3:4"), mode="fit")
    assert layout.crop is None
    w, h = layout.scaled
    assert w <= layout.box[0] and h <= layout.box[1]
    assert abs(w / h - 6000 / 4000) < 0.01
    assert w == layout.box[0]  # wide photo is width-bound inside a tall box


def test_fit_mode_centers_the_photo_in_the_canvas():
    layout = g.plan((6000, 4000), ratio=g.ratio_for("3:4"), mode="fit")
    x, y = layout.origin
    assert x == (1080 - layout.scaled[0]) // 2
    assert y == (1440 - layout.scaled[1]) // 2
    assert y > layout.border  # uneven mat: more white above and below


def test_upscale_is_flagged():
    small = g.plan((400, 400), ratio=g.ratio_for("1:1"), mode="crop")
    assert small.upscaled
    big = g.plan((4000, 4000), ratio=g.ratio_for("1:1"), mode="crop")
    assert not big.upscaled


def test_zero_border_uses_the_whole_canvas():
    layout = g.plan((6000, 4000), ratio=g.ratio_for("1:1"), border_pct=0)
    assert layout.box == (1080, 1080)
    assert layout.origin == (0, 0)


@pytest.mark.parametrize("bad", [(0, 100), (100, 0), (-5, 5)])
def test_plan_rejects_degenerate_sources(bad):
    with pytest.raises(g.GeometryError):
        g.plan(bad, ratio=g.ratio_for("1:1"))


def test_plan_rejects_unknown_mode():
    with pytest.raises(g.GeometryError):
        g.plan((100, 100), ratio=g.ratio_for("1:1"), mode="stretch")
