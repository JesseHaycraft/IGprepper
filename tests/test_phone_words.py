"""The phone app's wording and icons, run on the desktop."""

import sys
from pathlib import Path

import pytest

PHONE_SRC = Path(__file__).resolve().parents[1] / "phone" / "src"
sys.path.insert(0, str(PHONE_SRC))

from igprepper import icons, words  # noqa: E402
from igprepper.phonelog import PhoneLog  # noqa: E402


# --- fitting names on a narrow screen ---------------------------------------

def test_short_text_is_left_alone():
    assert words.shorten("Edits", 20) == "Edits"
    assert words.shorten("exactly ten", 11) == "exactly ten"


def test_long_text_is_cut_to_the_limit_with_an_ellipsis():
    cut = words.shorten("A very long folder name indeed", 12)
    assert len(cut) <= 12
    assert cut.endswith("…") and cut.startswith("A very long")


def test_line_breaks_cannot_get_into_a_label():
    assert words.shorten("two\nlines\there", 40) == "two lines here"


def test_a_short_path_is_shown_whole():
    assert words.trail(["Drive", "Photos", "2026"], 40) == "Drive › Photos › 2026"


def test_a_long_path_keeps_its_end():
    names = ["My Drive", "Photography", "Finished work", "2026", "October shoot"]
    shown = words.trail(names, 30)
    assert len(shown) <= 30
    assert shown.startswith("…") and shown.endswith("October shoot")


def test_a_path_that_cannot_fit_even_one_name_is_still_cut_to_the_limit():
    shown = words.trail(["a" * 80], 20)
    assert len(shown) <= 20


@pytest.mark.parametrize("count,text", [(1, "1 photo"), (2, "2 photos"), (12, "12 photos")])
def test_photos_are_counted_in_plain_words(count, text):
    assert words.photos(count) == text


def test_saved_message_names_where_the_photos_went():
    assert words.saved(3, "Edits", True) == "Saved 3 photos to “Edits” and the gallery"
    assert words.saved(1, "Edits", False) == "Saved 1 photo to “Edits”"
    assert words.saved(1, None, True) == "Saved 1 photo to the gallery"


def test_hint_says_what_can_be_done_then_how_to_undo_it():
    assert "Drag" in words.hint(False, False, "0°")
    assert words.hint(True, False, "+3°") == "Tap +3° to reset"
    filled = words.hint(True, True, "−12°")
    assert "fill the frame" in filled and "Tap −12° to reset" in filled
    # Labels do not wrap: every hint has to fit across a phone.
    assert all(
        len(words.hint(c, f, "−179°")) <= 50
        for c, f in [(False, False), (True, False), (True, True)]
    )


# --- icons ------------------------------------------------------------------

@pytest.mark.parametrize("name", icons.NAMES)
def test_every_icon_draws_something_in_one_colour(name):
    image = icons.icon(name, 96, "#8AB4F8")
    assert image.size == (96, 96) and image.mode == "RGBA"
    alpha = image.getchannel("A")
    inked = sum(alpha.histogram()[129:])
    # Some ink, but nowhere near a filled square.
    assert 96 * 96 * 0.04 < inked < 96 * 96 * 0.7
    assert image.getpixel((48, 48))[:3] == (0x8A, 0xB4, 0xF8)
    # Nothing touches the edge: Android's icons keep a margin.
    assert alpha.crop((0, 0, 96, 3)).getextrema()[1] < 40
    assert alpha.crop((0, 0, 3, 96)).getextrema()[1] < 40


def test_left_and_right_icons_are_mirror_images():
    from PIL import ImageOps

    for left, right in [("rotate_left", "rotate_right"), ("previous", "next")]:
        assert ImageOps.mirror(icons.icon(left, 96)).tobytes() == icons.icon(right, 96).tobytes()
        assert icons.icon(left, 96).tobytes() != icons.icon(right, 96).tobytes()


def test_the_plus_is_cut_out_of_the_new_folder():
    plain = icons.icon("folder", 96).getchannel("A")
    plus = icons.icon("new_folder", 96).getchannel("A")
    # 15, 13.5 on the 24-unit grid is the middle of the plus.
    at = (15 * 4, int(13.5 * 4))
    assert plain.getpixel(at) > 200 and plus.getpixel(at) < 40


# --- old logs -----------------------------------------------------------------

def test_clearing_old_logs_does_nothing_off_a_phone():
    assert PhoneLog().prune(10) == 0
