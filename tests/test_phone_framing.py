"""The phone app's framing step, run on the desktop."""

import io
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageOps, JpegImagePlugin

PHONE_SRC = Path(__file__).resolve().parents[1] / "phone" / "src"
sys.path.insert(0, str(PHONE_SRC))

from igprep.core import color  # noqa: E402
from igprep.core import geometry as g  # noqa: E402
from igprep.core.settings import Framing  # noqa: E402
from igprep.core.srgb_profile import SRGB_BYTES  # noqa: E402
from igprepper import framing  # noqa: E402


def _desktop_convert(data: bytes) -> Image.Image:
    """Stands in for Android's decoder: colour-converts, ignores rotation."""
    image = Image.open(io.BytesIO(data))
    image.load()
    return color.to_srgb(image)


def _marked(orientation: int | None = None) -> bytes:
    """A landscape photo with a red patch in its upright top-left corner."""
    upright = Image.new("RGB", (400, 200), (40, 90, 160))
    upright.paste((230, 30, 30), (0, 0, 100, 60))
    stored, exif = upright, Image.Exif()
    if orientation:
        # Store it the way a camera held at that orientation would.
        undo = {v: k for k, v in {
            Image.Transpose.FLIP_LEFT_RIGHT: Image.Transpose.FLIP_LEFT_RIGHT,
            Image.Transpose.ROTATE_180: Image.Transpose.ROTATE_180,
            Image.Transpose.FLIP_TOP_BOTTOM: Image.Transpose.FLIP_TOP_BOTTOM,
            Image.Transpose.TRANSPOSE: Image.Transpose.TRANSPOSE,
            Image.Transpose.ROTATE_270: Image.Transpose.ROTATE_90,
            Image.Transpose.TRANSVERSE: Image.Transpose.TRANSVERSE,
            Image.Transpose.ROTATE_90: Image.Transpose.ROTATE_270,
        }.items()}
        stored = upright.transpose(undo[framing._UPRIGHT[orientation]])
        exif[274] = orientation
    buffer = io.BytesIO()
    stored.save(buffer, "JPEG", quality=100, subsampling=0, exif=exif)
    return buffer.getvalue()


# --- rotation --------------------------------------------------------------

@pytest.mark.parametrize("orientation", [2, 3, 4, 5, 6, 7, 8])
def test_every_rotation_flag_comes_out_upright(orientation):
    data = _marked(orientation)
    image = framing.prepare(data, _desktop_convert)

    assert image.size == (400, 200)
    r, g_, b = image.getpixel((30, 20))
    assert r > 180 and g_ < 90, "the red patch should be back in the top-left"


@pytest.mark.parametrize("orientation", [2, 3, 4, 5, 6, 7, 8])
def test_rotation_matches_the_image_librarys_own(orientation):
    """Pillow's exif_transpose is the reference the desktop app uses."""
    data = _marked(orientation)
    ours = framing.prepare(data, _desktop_convert)
    reference = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    assert ours.size == reference.size
    assert ours.tobytes() == reference.tobytes()


def test_no_flag_means_no_rotation():
    assert framing.orientation_of(_marked()) == 1
    assert framing.prepare(_marked(), _desktop_convert).size == (400, 200)


def test_unreadable_data_is_treated_as_upright():
    assert framing.orientation_of(b"not an image") == 1


# --- framing ---------------------------------------------------------------

def test_frame_produces_an_instagram_file():
    image = Image.new("RGB", (3000, 2000), (200, 90, 60))
    result = framing.frame(image, Framing())

    assert result.canvas == (1080, 1440)
    assert result.border == 43
    assert result.source_size == (3000, 2000)
    with Image.open(io.BytesIO(result.jpeg)) as saved:
        assert saved.size == (1080, 1440)
        assert saved.info.get("icc_profile") == SRGB_BYTES
        assert JpegImagePlugin.get_sampling(saved) == 0


def test_frame_follows_the_framing_it_is_given():
    image = Image.new("RGB", (3000, 2000), (200, 90, 60))
    result = framing.frame(image, Framing(ratio="1:1", mode="crop", border_pct=0))
    assert result.canvas == (1080, 1080) and result.border == 0


def test_small_photos_are_flagged_as_enlarged():
    image = Image.new("RGB", (300, 200), (200, 90, 60))
    assert framing.frame(image, Framing(mode="crop")).upscaled


def test_preview_is_a_scale_model():
    image = Image.new("RGB", (3000, 2000), (200, 90, 60))
    preview = framing.preview(image, Framing(ratio="4:5"))
    assert preview.width == 600
    assert abs(preview.width / preview.height - 0.8) < 0.01
    assert preview.getpixel((0, 0)) == (255, 255, 255)


# --- names -----------------------------------------------------------------

def test_output_name_matches_the_desktop_default():
    assert framing.output_name("PXL_20261003_170000.jpg", []) == "PXL_20261003_170000_ig.jpg"


def test_output_name_avoids_what_is_already_there():
    """Google Drive would accept the duplicate; the app must not offer one."""
    taken = ["shot_ig.jpg", "shot_ig_2.jpg"]
    assert framing.output_name("shot.jpg", taken) == "shot_ig_3.jpg"


def test_output_name_compares_without_case():
    assert framing.output_name("Shot.JPG", ["SHOT_IG.JPG"]) == "Shot_ig_2.jpg"


def test_output_name_survives_odd_source_names():
    assert framing.output_name("no-extension", []) == "no-extension_ig.jpg"
    assert framing.output_name(".jpg", []) == "photo_ig.jpg"
    assert framing.output_name("a/b:c.jpeg", []) == "a-b-c_ig.jpg"


# --- turning and tilting ---------------------------------------------------

def test_frame_turns_a_photo_on_its_side():
    image = Image.new("RGB", (3000, 2000), (40, 90, 160))
    image.paste((230, 30, 30), (0, 0, 750, 500))
    result = framing.frame(
        image, Framing(ratio="1:1", mode="fit", border_pct=0), g.Placement(angle=90)
    )
    with Image.open(io.BytesIO(result.jpeg)) as saved:
        # Now a tall photo, centred in the square, red corner at the top right.
        assert saved.getpixel((880, 20))[0] > 200
        assert saved.getpixel((200, 20))[0] < 100
        assert saved.getpixel((20, 540)) == (255, 255, 255)


def test_frame_without_a_placement_is_unchanged_by_one_left_alone():
    image = Image.new("RGB", (3000, 2000), (200, 90, 60))
    assert framing.frame(image, Framing()).jpeg == framing.frame(
        image, Framing(), g.Placement()
    ).jpeg


def test_a_tilted_photo_fills_the_frame_in_fit_mode():
    image = Image.new("RGB", (3000, 2000), (200, 90, 60))
    result = framing.frame(image, Framing(mode="fit"), g.Placement(angle=5))
    with Image.open(io.BytesIO(result.jpeg)) as saved:
        # Fit mode would leave white above and below a wide photo.
        assert saved.getpixel((540, 60))[0] < 230
        assert saved.getpixel((540, 20)) == (255, 255, 255)  # the frame itself


def test_preview_follows_the_placement():
    image = Image.new("RGB", (3000, 2000), (40, 90, 160))
    image.paste((230, 30, 30), (0, 0, 750, 500))
    chosen = Framing(ratio="1:1", mode="fit", border_pct=0)
    turned = framing.preview(image, chosen, g.Placement(angle=180))
    assert turned.getpixel((580, 480))[0] > 200  # the red corner, now bottom right


def test_guided_preview_keeps_its_size_and_leaves_the_original_alone():
    image = Image.new("RGB", (3000, 2000), (40, 90, 160))
    plain = framing.preview(image, Framing(mode="crop"))
    before = plain.tobytes()
    guided = framing.guided(plain, Framing(mode="crop"))
    assert guided.size == plain.size
    assert guided.tobytes() != before and plain.tobytes() == before


@pytest.mark.parametrize(
    "angle,label",
    [(0, "0°"), (1, "+1°"), (-1, "−1°"), (90, "+90°"), (-137, "−137°"), (180, "+180°")],
)
def test_angle_label(angle, label):
    assert framing.angle_label(angle) == label


def test_small_copy_of_a_saved_photo_is_small_and_whole():
    image = Image.new("RGB", (3000, 2000), (200, 90, 60))
    jpeg = framing.frame(image, Framing()).jpeg
    small = framing.small_copy(jpeg)
    assert max(small.size) <= 320 and small.mode == "RGB"
    assert abs(small.width / small.height - 0.75) < 0.02
    assert small.getpixel((2, 2))[0] > 240  # the frame is still round it
