"""Reading fingers on the photo, run on the desktop."""

import sys
from pathlib import Path

import pytest

PHONE_SRC = Path(__file__).resolve().parents[1] / "phone" / "src"
sys.path.insert(0, str(PHONE_SRC))

from igprep.core import geometry as g  # noqa: E402
from igprep.core.settings import Framing  # noqa: E402
from igprepper import framing  # noqa: E402
from igprepper.gestures import MIN_APART, Step, Tracker  # noqa: E402


def test_one_finger_drags():
    tracker = Tracker()
    tracker.changed([(100, 100)])
    assert tracker.moved([(110, 95)]) == Step((100, 100), (110, 95), 1.0)
    assert tracker.moved([(130, 95)]) == Step((110, 95), (130, 95), 1.0)


def test_two_fingers_pinch_about_the_point_between_them():
    tracker = Tracker()
    tracker.changed([(100, 200), (300, 200)])
    step = tracker.moved([(50, 200), (350, 200)])
    assert step == Step((200, 200), (200, 200), 1.5)


def test_two_fingers_moving_together_drag_without_zooming():
    tracker = Tracker()
    tracker.changed([(100, 200), (300, 200)])
    step = tracker.moved([(100, 260), (300, 260)])
    assert step == Step((200, 200), (200, 260), 1.0)


def test_a_second_finger_landing_does_not_make_the_photo_jump():
    tracker = Tracker()
    tracker.changed([(100, 100)])
    tracker.moved([(120, 100)])
    # The midpoint is suddenly far from where the one finger was.
    tracker.changed([(120, 100), (400, 500)])
    step = tracker.moved([(120, 100), (400, 500)])
    assert step is None


def test_lifting_one_of_two_fingers_carries_on_as_a_drag():
    tracker = Tracker()
    tracker.changed([(100, 100), (300, 100)])
    tracker.moved([(90, 100), (310, 100)])
    tracker.changed([(310, 100)])
    assert tracker.moved([(320, 110)]) == Step((310, 100), (320, 110), 1.0)


def test_a_finger_that_does_not_move_is_not_a_step():
    tracker = Tracker()
    tracker.changed([(100, 100)])
    assert tracker.moved([(100, 100)]) is None


def test_nothing_happens_without_a_touch_first_or_after_it_ends():
    tracker = Tracker()
    assert tracker.moved([(100, 100)]) is None
    tracker.changed([(100, 100)])
    tracker.ended()
    assert tracker.moved([(150, 100)]) is None


def test_a_change_in_fingers_that_was_never_announced_is_ignored():
    tracker = Tracker()
    tracker.changed([(100, 100)])
    assert tracker.moved([(100, 100), (300, 100)]) is None
    # ...and tracking picks up cleanly from there.
    assert tracker.moved([(90, 100), (310, 100)]).spread == pytest.approx(1.1)


def test_fingers_almost_touching_drag_but_do_not_zoom():
    tracker = Tracker()
    tracker.changed([(100, 100), (100 + MIN_APART / 2, 100)])
    step = tracker.moved([(100, 130), (100 + MIN_APART * 0.9, 130)])
    assert step.spread == 1.0
    assert step.after[1] == 130


def test_only_the_first_two_fingers_count():
    tracker = Tracker()
    tracker.changed([(0, 0), (100, 0), (900, 900)])
    step = tracker.moved([(0, 0), (200, 0), (10, 10)])
    assert step.spread == 2.0


# --- what the app does with a step ------------------------------------------

def test_output_box_is_the_photos_share_of_the_finished_picture():
    assert framing.output_box(Framing(ratio="3:4", border_pct=4.0)) == (994, 1354)
    assert framing.output_box(Framing(ratio="1:1", border_pct=0)) == (1080, 1080)


def test_frame_will_not_enlarge_a_photo_that_was_zoomed_too_far():
    from PIL import Image

    image = Image.new("RGB", (3000, 2000), (200, 90, 60))
    chosen = Framing(ratio="1:1", mode="crop")
    assert not framing.frame(image, chosen, g.Placement(zoom=50)).upscaled


def test_quick_preview_matches_the_careful_one():
    from PIL import Image, ImageChops, ImageStat

    image = Image.linear_gradient("L").resize((3000, 2000)).convert("RGB")
    chosen, placement = Framing(mode="crop"), g.Placement(angle=6, zoom=1.4, offset_y=0.5)
    careful = framing.preview(image, chosen, placement)
    quick = framing.quick_preview(framing.quick_proxy(image), chosen, placement)
    assert quick.size == careful.size
    assert sum(ImageStat.Stat(ImageChops.difference(quick, careful)).mean) / 3 < 2
