import pytest
from PIL import Image, ImageCms

from igprep.core import color, geometry as g, render

WHITE = (255, 255, 255)
RED = (220, 40, 40)


def _framed(src, *, ratio="3:4", mode="crop", border_pct=4.0, sharpen=0,
            frame="#FFFFFF"):
    layout = g.plan(src.size, ratio=g.ratio_for(ratio), border_pct=border_pct,
                    mode=mode)
    return render.render(src, layout, frame_color=frame, sharpen=sharpen), layout


def test_output_is_exactly_the_canvas_size(solid):
    out, layout = _framed(solid())
    assert out.size == layout.canvas == (1080, 1440)
    assert out.mode == "RGB"


def test_border_is_the_planned_thickness_on_all_four_sides(solid):
    out, layout = _framed(solid())
    b = layout.border
    w, h = out.size
    mx, my = w // 2, h // 2
    # Just inside the border: frame colour. Just past it: photo.
    assert out.getpixel((b - 1, my)) == WHITE
    assert out.getpixel((mx, b - 1)) == WHITE
    assert out.getpixel((w - b, my)) == WHITE
    assert out.getpixel((mx, h - b)) == WHITE
    assert out.getpixel((b + 1, my)) != WHITE
    assert out.getpixel((mx, b + 1)) != WHITE


def test_border_is_identical_in_pixels_across_every_ratio(solid):
    """The consistency guarantee, checked on rendered pixels not just math."""
    widths = set()
    for ratio in ("1:1", "4:5", "3:4", "1.91:1", "9:16"):
        out, _ = _framed(solid(), ratio=ratio)
        row = out.size[1] // 2
        x = 0
        while out.getpixel((x, row)) == WHITE:
            x += 1
        widths.add(x)
    assert widths == {43}


def test_crop_mode_fills_the_box_leaving_no_extra_white(solid):
    out, layout = _framed(solid(), mode="crop")
    b = layout.border
    # Every pixel just inside the border is photo, on both axes.
    assert out.getpixel((b, out.size[1] // 2)) != WHITE
    assert out.getpixel((out.size[0] // 2, b)) != WHITE


def test_fit_mode_leaves_a_wider_mat_on_the_long_axis(solid):
    """A 3:2 photo in a 3:4 canvas keeps full width and gains white bands."""
    out, layout = _framed(solid(3000, 2000), mode="fit")
    b = layout.border
    mx = out.size[0] // 2
    assert out.getpixel((b, out.size[1] // 2)) != WHITE   # width is filled
    assert out.getpixel((mx, b)) == WHITE                 # top band is white
    assert out.getpixel((mx, out.size[1] // 2)) != WHITE  # photo in the middle


def test_fit_mode_never_crops(solid):
    layout = g.plan((3000, 2000), ratio=g.ratio_for("3:4"), mode="fit")
    assert layout.crop is None
    assert abs(layout.scaled[0] / layout.scaled[1] - 1.5) < 0.01


def test_frame_colour_is_honoured(solid):
    out, _ = _framed(solid(), frame="#FAFAFA")
    assert out.getpixel((0, 0)) == (250, 250, 250)


def test_zero_border_produces_no_frame(solid):
    out, layout = _framed(solid(), border_pct=0)
    assert layout.border == 0
    assert out.getpixel((0, 0)) != WHITE


def test_transparency_is_flattened_onto_the_frame_colour():
    src = Image.new("RGBA", (1200, 1200), (0, 0, 0, 0))
    out, _ = _framed(src, ratio="1:1", frame="#FFFFFF")
    assert out.mode == "RGB"
    assert out.getpixel((540, 540)) == WHITE


def test_sharpening_changes_pixels_only_when_enabled(gradient):
    src = gradient()
    plain, _ = _framed(src, ratio="1:1", sharpen=0)
    sharp, _ = _framed(src, ratio="1:1", sharpen=80)
    assert plain.tobytes() != sharp.tobytes()


def test_sharpening_is_skipped_when_not_downscaling():
    assert render.sharpen_percent(80, 1.0) == 0
    assert render.sharpen_percent(80, 1.4) == 0


def test_exif_orientation_is_applied_before_geometry(tmp_path, solid):
    """A rotated portrait must plan as a portrait, not as its stored landscape."""
    src = solid(3000, 2000)
    path = tmp_path / "rot.jpg"
    exif = Image.Exif()
    exif[274] = 6  # rotate 90 CW on display
    src.save(path, "JPEG", exif=exif)

    loaded = render.load(path)
    assert loaded.size == (2000, 3000)


def test_icc_profile_is_converted_to_srgb(tmp_path, warm_profile_bytes):
    src = Image.new("RGB", (600, 600), (180, 120, 90))
    path = tmp_path / "warm.jpg"
    src.save(path, "JPEG", quality=100, icc_profile=warm_profile_bytes)

    converted = color.to_srgb(render.load(path))
    assert converted.getpixel((300, 300)) != (180, 120, 90)


def test_untagged_images_are_left_alone(tmp_path):
    src = Image.new("RGB", (600, 600), (180, 120, 90))
    path = tmp_path / "plain.jpg"
    src.save(path, "JPEG", quality=100)

    converted = color.to_srgb(render.load(path))
    r, gg, b = converted.getpixel((300, 300))
    assert abs(r - 180) <= 2 and abs(gg - 120) <= 2 and abs(b - 90) <= 2


def test_a_corrupt_profile_does_not_fail_the_job(tmp_path):
    src = Image.new("RGB", (600, 600), (180, 120, 90))
    path = tmp_path / "bad.jpg"
    src.save(path, "JPEG", quality=100, icc_profile=b"not a profile")

    converted = color.to_srgb(render.load(path))
    assert converted.mode == "RGB"
    assert converted.size == (600, 600)


def test_profile_name_is_readable(warm_profile_bytes):
    img = Image.new("RGB", (10, 10))
    assert color.embedded_profile_name(img) is None
    img.info["icc_profile"] = warm_profile_bytes
    assert isinstance(color.embedded_profile_name(img), str)


def test_saved_jpeg_embeds_srgb_and_uses_444(tmp_path, gradient):
    out, _ = _framed(gradient(), ratio="1:1")
    path = tmp_path / "out.jpg"
    render.save_jpeg(out, path)

    from PIL import JpegImagePlugin

    with Image.open(path) as saved:
        assert saved.size == (1080, 1080)
        assert saved.info.get("icc_profile") == color.SRGB_BYTES
        assert JpegImagePlugin.get_sampling(saved) == 0  # 4:4:4


def test_fit_mode_mat_is_pure_white_not_grey(solid):
    """A portrait fitted into 1.91:1 leaves wide margins; they must be white.

    The preview dims these bands when the grid overlay is on, which reads as
    grey -- this pins that the written file never is.
    """
    out, layout = _framed(solid(3265, 4366), ratio="1.91:1", mode="fit")
    w, h = out.size
    row = [out.getpixel((x, h // 2)) for x in range(w)]
    photo = [x for x, px in enumerate(row) if px != WHITE]
    assert min(photo) > 300 and w - 1 - max(photo) > 300  # wide margins
    assert all(row[x] == WHITE for x in range(min(photo)))
    assert all(row[x] == WHITE for x in range(max(photo) + 1, w))
