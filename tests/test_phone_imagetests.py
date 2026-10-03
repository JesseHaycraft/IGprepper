"""The phone app's image checks, run on the desktop.

The checks are sent to a phone to find out whether the phone is right, so
they had better be right themselves. Here they must pass against the desktop
pipeline, and must fail when handed something wrong.
"""

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

PHONE_SRC = Path(__file__).resolve().parents[1] / "phone" / "src"
sys.path.insert(0, str(PHONE_SRC))

from igprep.core import color  # noqa: E402
from igprepper import imagetests  # noqa: E402
from igprepper.fixtures import FIXTURES  # noqa: E402


class ListLog:
    def __init__(self):
        self.lines = []

    def write(self, message=""):
        self.lines.extend(str(message).splitlines() or [""])

    def section(self, title):
        self.lines.append(f"=== {title} ===")

    def exception(self, doing):
        import traceback

        self.lines.append(f"FAILED while {doing}:")
        self.lines.extend(traceback.format_exc().splitlines())

    def text(self):
        return "\n".join(self.lines)


@pytest.fixture
def log():
    return ListLog()


def test_the_whole_suite_passes_on_the_desktop(log):
    assert imagetests.run_all(log) is True, log.text()
    assert "FAIL" not in log.text()


def test_pipeline_check_measures_the_real_border(log):
    assert imagetests.check_pipeline(log)
    assert "(43, 43, 43, 43)" in log.text()


def test_framed_test_jpeg_is_a_real_instagram_sized_file():
    with Image.open(io.BytesIO(imagetests.framed_test_jpeg())) as image:
        assert image.size == (1080, 1440)
        assert image.format == "JPEG"


def test_test_photo_edges_are_never_frame_white():
    """Otherwise the border measurement would run on into the photo."""
    photo = imagetests.make_test_photo(600, 400)
    w, h = photo.size
    for point in ((0, h // 2), (w - 1, h // 2), (w // 2, 0), (w // 2, h - 1)):
        assert photo.getpixel(point) != (255, 255, 255)


# --- colour ----------------------------------------------------------------

def test_fixtures_really_need_converting():
    """A fixture whose colours do not move would prove nothing."""
    for fixture in FIXTURES:
        moved = max(
            abs(a - b)
            for _, stored, expected in fixture["patches"]
            for a, b in zip(stored, expected)
        )
        assert moved >= 10, fixture["name"]


def test_colour_check_passes_through_the_image_library(log):
    assert color.HAVE_ENGINE
    assert imagetests.check_colour(log)
    assert "via image library" in log.text()


def test_colour_check_accepts_a_second_route(log):
    def convert(data):
        return color.to_srgb(Image.open(io.BytesIO(data)))

    assert imagetests.check_colour(log, convert)
    assert "via Android" in log.text()


def test_colour_check_fails_a_route_that_ignores_the_profile(log):
    """What a decoder with no colour management would do."""
    def ignore_profile(data):
        return Image.open(io.BytesIO(data)).convert("RGB")

    assert imagetests.check_colour(log, ignore_profile) is False
    assert "FAIL" in log.text()


def test_colour_check_fails_when_nothing_can_convert(log, monkeypatch):
    monkeypatch.setattr(color, "HAVE_ENGINE", False)
    assert imagetests.check_colour(log) is False
    assert "no way to convert" in log.text()


def test_a_crashing_route_is_reported_not_raised(log):
    def broken(data):
        raise RuntimeError("decoder fell over")

    assert imagetests.check_colour(log, broken) is False
    assert "decoder fell over" in log.text()


def test_speed_check_reports_a_time(log):
    seconds = imagetests.check_speed(log, size=(1200, 900))
    assert seconds > 0
    assert "MP photo" in log.text()


# --- the pipeline without a colour engine -----------------------------------

def test_pipeline_still_runs_when_the_engine_is_missing(log, monkeypatch):
    """The situation on Android: the engine raises the moment it is touched."""
    from PIL import ImageCms

    def unavailable(*args, **kwargs):
        raise ImportError("colour engine not built")

    monkeypatch.setattr(ImageCms, "ImageCmsProfile", unavailable)
    monkeypatch.setattr(ImageCms, "profileToProfile", unavailable)
    monkeypatch.setattr(color, "HAVE_ENGINE", False)

    assert imagetests.check_pipeline(log), log.text()
