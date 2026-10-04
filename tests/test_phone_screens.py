"""The phone app's two screens, run on a desk.

The app is started for real, on the toolkit's own stand-in for a screen and
on a pretend phone (`igprepper/native/fake`): storage is a folder in the
temporary directory, lists only remember what they were told to show. Each
test then does what a person would, and looks at what the app did.

This is the quick counterpart of the emulator run. It cannot say how the app
looks, or whether Android does as asked; it can say whether the app asks for
the right things.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from PIL import Image

os.environ.setdefault("TOGA_BACKEND", "toga_dummy")
PHONE_SRC = Path(__file__).resolve().parents[1] / "phone" / "src"
sys.path.insert(0, str(PHONE_SRC))

from igprep.core import geometry as g  # noqa: E402
from igprepper import browser as browser_module  # noqa: E402
from igprepper import places  # noqa: E402
from igprepper.app import FIT_CHOICES, IGprepper  # noqa: E402
from igprepper.native import storage, touch, ui  # noqa: E402


class Phone:
    """An app, the folders it can see, and a way to press things."""

    def __init__(self, tmp_path: Path) -> None:
        self.private = tmp_path / "private"
        self.shots = tmp_path / "phone" / "Camera"
        self.out = tmp_path / "phone" / "Framed"
        self.shots.mkdir(parents=True)
        self.out.mkdir(parents=True)
        self.app = self.launch()

    def launch(self) -> IGprepper:
        private = self.private

        class Desk(IGprepper):
            def data_dir(self):
                return private

        app = Desk("IGprepper", "org.igprepper.igprepper")
        app.unattended = True
        self.app = app
        # The toolkit calls this itself once a real screen is up.
        self.do(IGprepper.on_running(app))
        return app

    # --- making things happen --------------------------------------------------

    def do(self, coroutine=None, *, press=None):
        """Run something to its end, and whatever it set in motion."""

        async def through():
            if press is not None:
                press()
            if coroutine is not None:
                await coroutine
            mine = asyncio.current_task()
            for _ in range(1000):
                await asyncio.sleep(0.01)
                # Settled means nothing in hand and nothing started on the
                # side: some things the app does, such as re-reading a folder
                # on being returned to, are set going and not waited for.
                others = [t for t in asyncio.all_tasks() if t is not mine and not t.done()]
                if not self.app.busy and not self.loading() and not others:
                    return
            raise AssertionError("the app did not settle")

        return self.app.loop.run_until_complete(through())

    def loading(self) -> bool:
        return any(b.rechecking or b.still_loading for b in self.app.browsers)

    def photo(self, name="a.jpg", size=(1200, 900), folder=None, colour=(40, 90, 160)):
        path = (folder or self.shots) / name
        Image.new("RGB", size, colour).save(path, quality=90)
        return path

    def choose(self, side, folder):
        storage.picks.append(folder)
        self.do(side.choose())

    def ready(self, *names):
        """Both folders chosen, and these photos waiting in the input one."""
        for name in names or ("a.jpg",):
            self.photo(name)
        self.choose(self.app.target, self.out)
        self.choose(self.app.source, self.shots)
        return self.app

    def check(self, *names):
        for name in names:
            self.app.source.files.press(name)

    def edit(self, *names):
        self.check(*names)
        self.do(self.app.process_selected())

    def out_names(self):
        return sorted(p.name for p in self.out.iterdir())


@pytest.fixture
def phone(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(browser_module, "RECHECK_SECONDS", 0.02)
    storage.reset()
    ui.reset()
    made = Phone(tmp_path)
    yield made
    made.app.loop.close()


# --- the first screen -------------------------------------------------------------

def test_a_first_launch_asks_for_both_folders(phone):
    app = phone.app
    assert app.main_window.content is app.home_box
    for side in app.browsers:
        assert side.tree is None and side.path == "No folder chosen"
        assert side.path_view.text == "No folder chosen"
        assert ui.said(side.choose_btn) == "Choose folder"
        assert not side.up_btn.enabled
    assert "photos are in" in app.source.files.note
    assert "should go to" in app.target.files.note
    assert not app.target.new_btn.enabled and app.source.new_btn is None
    assert not app.process_btn.enabled
    assert ui.said(app.process_btn) == "Frame selected photos"
    assert ui.bars_darkened


def test_the_picker_being_closed_changes_nothing(phone):
    phone.do(phone.app.target.choose())  # nothing queued: the picker hands back nothing
    assert phone.app.target.tree is None


def test_choosing_folders_lists_them_and_asks_only_for_what_is_needed(phone):
    phone.photo("a.jpg")
    (phone.shots / "notes.txt").write_text("x")
    (phone.shots / "Older").mkdir()
    app = phone.ready()

    assert storage.granted[str(phone.out)] is True       # may write
    assert storage.granted[str(phone.shots)] is False    # asked only to read
    assert app.source.files.names() == ["Older", "a.jpg", "notes.txt"] or (
        app.source.files.names()[0] == "Older"
        and set(app.source.files.names()[1:]) == {"a.jpg", "notes.txt"}
    )
    assert app.source.files.selectable and not app.target.files.selectable
    assert app.target.files.note == "This folder is empty"
    assert ui.said(app.source.choose_btn) == "Change"
    assert app.target.new_btn.enabled
    assert app.source.path_view.text.endswith("Camera")


def test_pressing_a_folder_opens_it_and_up_comes_back(phone):
    (phone.shots / "Trip").mkdir()
    phone.photo("inside.jpg", folder=phone.shots / "Trip")
    app = phone.ready()
    source = app.source
    assert not source.up_btn.enabled

    phone.do(press=lambda: source.files.press("Trip"))
    assert [name for _, name in source.trail] == ["Camera", "Trip"]
    assert source.files.names() == ["inside.jpg"]
    assert source.path_view.text.endswith("Camera/Trip")
    assert source.up_btn.enabled

    phone.do(source.up())
    assert len(source.trail) == 1 and not source.up_btn.enabled


def test_photos_are_checked_counted_and_let_go_on_leaving(phone):
    (phone.shots / "Trip").mkdir()
    (phone.shots / "notes.txt").write_text("x")
    app = phone.ready("a.jpg", "b.jpg")
    source = app.source

    phone.check("a.jpg")
    assert source.files.counter == "1 selected" and app.process_btn.enabled
    phone.check("b.jpg")
    assert source.files.counter == "2 selected"
    phone.check("a.jpg")
    assert source.files.counter == "1 selected"
    assert [e.name for e in source.chosen()] == ["b.jpg"]

    phone.check("notes.txt")
    assert len(source.checked) == 1 and "not a photo" in ui.toasts[-1]

    phone.do(press=lambda: source.files.press("Trip"))
    assert not source.checked and source.files.counter is None
    assert not app.process_btn.enabled


def test_nothing_on_the_output_side_can_be_checked(phone):
    phone.photo("there.jpg", folder=phone.out)
    app = phone.ready()
    app.target.files.press("there.jpg")
    assert not app.target.checked and not app.process_btn.enabled


def test_tiles_are_remembered_for_the_folder_they_were_chosen_in(phone):
    (phone.shots / "Trip").mkdir()
    app = phone.ready()
    source = app.source
    assert not source.files.tiles

    source.toggle_view()
    assert source.files.tiles and source.tiled
    phone.do(press=lambda: source.files.press("Trip"))
    assert not source.files.tiles, "a different folder is still a list"
    phone.do(source.up())
    assert source.files.tiles

    again = phone.launch()
    assert again.source.files.tiles and not again.target.files.tiles


def test_checks_survive_a_change_of_view(phone):
    app = phone.ready("a.jpg")
    phone.check("a.jpg")
    app.source.toggle_view()
    assert app.source.checked and app.source.files.counter == "1 selected"


# --- making a folder -----------------------------------------------------------------

def test_a_new_folder_is_named_exactly_as_typed(phone):
    app = phone.ready()
    phone.do(app.target.new_folder())
    assert ui.asking[0] == "New folder"
    phone.do(press=lambda: ui.answer("  2026 - Lisbon & Porto  "))
    assert (phone.out / "2026 - Lisbon & Porto").is_dir()
    assert app.target.files.names() == ["2026 - Lisbon & Porto"]
    assert ui.toasts[-1] == "Created “2026 - Lisbon & Porto”"


def test_a_name_already_in_the_folder_is_turned_down(phone):
    (phone.out / "Edits").mkdir()
    app = phone.ready()
    phone.do(app.target.create_folder("edits"))
    assert [p.name for p in phone.out.iterdir()] == ["Edits"]
    assert app.said.startswith("Already there")


def test_no_name_means_no_folder(phone):
    app = phone.ready()
    phone.do(app.target.create_folder("   "))
    assert list(phone.out.iterdir()) == []


def test_a_new_folder_is_checked_against_the_whole_folder_not_what_has_arrived(phone):
    """Cloud storage delivers a large folder in parts. The folder being asked
    for may be in a part not yet delivered."""
    for name in ("Alpha", "Edits", "Zulu", "Yankee"):
        (phone.out / name).mkdir()
    app = phone.ready()
    storage.slow[str(phone.out)] = 3   # the next three listings come back half done
    phone.do(app.target.create_folder("Zulu"))
    assert app.said.startswith("Already there")
    assert len(list(phone.out.iterdir())) == 4


def test_a_folder_that_never_finishes_loading_refuses_new_folders(phone, monkeypatch):
    (phone.out / "Alpha").mkdir()
    app = phone.ready()
    monkeypatch.setattr(browser_module, "WHOLE_SECONDS", 0.05)
    storage.slow[str(phone.out)] = 10_000
    phone.app.loop.run_until_complete(app.target.create_folder("Brand new"))
    assert app.said.startswith("Still loading")
    assert not (phone.out / "Brand new").exists()
    storage.slow.clear()


# --- a folder that arrives in parts -----------------------------------------------------

def test_a_folder_still_arriving_is_read_again_until_it_is_whole(phone):
    storage.slow[str(phone.shots)] = 2
    app = phone.ready(*(f"p{n}.jpg" for n in range(6)))
    assert len(app.source.files.rows) == 6
    assert not app.source.still_loading and app.source.files.counter is None


def test_a_re_read_that_comes_back_part_done_is_also_followed_up(phone):
    """After saving, or on coming back to the app, the folder is read again.
    That reading can be partial too, and used to be left that way."""
    app = phone.ready(*(f"p{n}.jpg" for n in range(6)))
    phone.check("p1.jpg")
    storage.slow[str(phone.shots)] = 2
    phone.do(app.source.reload())
    assert len(app.source.files.rows) == 6 and not app.source.still_loading
    assert len(app.source.checked) == 1, "what was checked is kept"


def test_coming_back_to_the_app_reads_both_folders_again(phone):
    app = phone.ready()
    phone.photo("late.jpg")
    (phone.out / "arrived.txt").write_text("x")
    app.reread_at = 0.0
    phone.do(press=ui.returns[-1].action)
    assert "late.jpg" in app.source.files.names()
    assert "arrived.txt" in app.target.files.names()


def drawn(phone, files, name):
    """Draw one row as the screen does, again and again until its picture
    has arrived and nothing more is on its way."""

    async def until_settled():
        for _ in range(500):
            picture = files.picture(name)
            thumbs = files.thumbs
            if picture is not None and not thumbs.waiting and not thumbs.fetching:
                return picture
            await asyncio.sleep(0.01)
        raise AssertionError("no picture arrived")

    return phone.app.loop.run_until_complete(until_settled())


def roughly(pixel, colour) -> bool:
    return all(abs(a - b) <= 12 for a, b in zip(pixel, colour))


def test_a_photo_replaced_while_its_folder_is_open_gets_a_new_picture(phone):
    app = phone.ready("a.jpg")
    files = app.source.files
    assert roughly(drawn(phone, files, "a.jpg").getpixel((10, 10)), (40, 90, 160))

    # Another app puts a different photo in its place, under the same name.
    phone.photo("a.jpg", size=(1000, 800), colour=(200, 60, 30))
    app.reread_at = 0.0
    phone.do(press=ui.returns[-1].action)
    assert roughly(drawn(phone, files, "a.jpg").getpixel((10, 10)), (200, 60, 30))


def test_a_photo_left_alone_keeps_its_picture_across_a_re_read(phone):
    app = phone.ready("a.jpg")
    files = app.source.files
    before = drawn(phone, files, "a.jpg")
    app.reread_at = 0.0
    phone.do(press=ui.returns[-1].action)
    assert files.picture("a.jpg") is before, "not fetched a second time"


# --- remembering -----------------------------------------------------------------------

def test_both_folders_are_where_they_were_left_at_the_next_launch(phone):
    (phone.shots / "Trip").mkdir()
    (phone.out / "Edits").mkdir()
    app = phone.ready()
    phone.do(press=lambda: app.source.files.press("Trip"))
    phone.do(press=lambda: app.target.files.press("Edits"))

    again = phone.launch()
    assert [n for _, n in again.source.trail] == ["Camera", "Trip"]
    assert [n for _, n in again.target.trail] == ["Framed", "Edits"]
    assert storage.picks == [], "and nobody was sent back to the picker"


def test_a_folder_deleted_since_last_time_falls_back_to_the_one_above(phone):
    (phone.out / "Edits").mkdir()
    app = phone.ready()
    phone.do(press=lambda: app.target.files.press("Edits"))
    (phone.out / "Edits").rmdir()
    again = phone.launch()
    assert [n for _, n in again.target.trail] == ["Framed"]


def test_access_that_was_taken_away_means_choosing_again(phone):
    phone.ready()
    storage.granted.clear()
    again = phone.launch()
    assert again.source.tree is None and again.target.tree is None


def test_changing_a_folder_gives_up_the_old_one_unless_the_other_side_uses_it(phone):
    app = phone.ready()
    elsewhere = phone.out.parent / "Elsewhere"
    elsewhere.mkdir()
    phone.choose(app.target, elsewhere)
    assert str(phone.out) not in storage.granted
    assert places.load(app.places_file())["output"].tree == str(elsewhere)

    phone.choose(app.source, elsewhere)      # both sides now on one folder
    phone.choose(app.source, phone.shots)    # input moves away again
    assert str(elsewhere) in storage.granted, "the output side still needs it"


# --- the divider ---------------------------------------------------------------------------

def test_the_divider_moves_stops_short_of_either_end_and_is_remembered(phone):
    app = phone.ready()
    handle = ui.handles[-1]
    least = ui.dp(28)

    phone.do(press=lambda: handle.drag(60))
    assert app.views.split == pytest.approx(360 / 600)
    phone.do(press=lambda: handle.drag(9000))
    assert app.views.split == pytest.approx((600 - least) / 600)
    phone.do(press=lambda: handle.drag(-9000))
    assert app.views.split == pytest.approx(least / 600)

    again = phone.launch()
    assert again.views.split == pytest.approx(least / 600)
    assert again.source.holder.style.flex < again.target.holder.style.flex


# --- the editor ----------------------------------------------------------------------------

def test_one_photo_in_the_editor(phone):
    app = phone.ready("a.jpg")
    phone.edit("a.jpg")
    assert app.main_window.content is app.editor_box
    assert app.count_label.text == "1 of 1"
    assert ui.said(app.save_btn) == "Save photo"
    assert not app.next_btn.enabled and not app.previous_btn.enabled
    assert app.border_slider.value == g.DEFAULT_BORDER_PCT == 3.0
    assert app.hint_label.text.startswith("Drag to move")
    assert app.preview_view.image is not None
    assert app.back.listening


def test_several_photos_step_round_and_keep_their_own_positions(phone):
    app = phone.ready("a.jpg", "b.jpg", "c.jpg")
    phone.edit("a.jpg", "b.jpg", "c.jpg")
    assert ui.said(app.save_btn) == "Save photos" and app.next_btn.enabled
    assert app.count_label.text == "1 of 3"

    app.rotate(1)
    app.rotate(1)
    assert ui.said(app.angle_btn) == "+2°" and app.guides_showing
    assert "to reset" in app.hint_label.text

    phone.do(app.next_photo())
    assert app.count_label.text == "2 of 3" and ui.said(app.angle_btn) == "0°"
    assert not app.guides_showing
    app.rotate(-90)

    phone.do(app.previous_photo())
    assert ui.said(app.angle_btn) == "+2°"
    phone.do(app.previous_photo())
    assert app.count_label.text == "3 of 3"

    assert {i: p.angle for i, p in app.placements.items()} == {0: 2, 1: -90}
    app.recentre()
    phone.do(app.next_photo())
    app.recentre()
    assert app.placements == {1: g.Placement(angle=-90)}


def test_a_photo_that_will_not_open_leaves_the_editor_on_the_one_before(phone):
    app = phone.ready("a.jpg", "b.jpg")
    phone.edit("a.jpg", "b.jpg")
    showing = app.picked[0][1]
    Path(app.picked[1][0]).write_bytes(b"not a photo")
    phone.do(app.next_photo())
    assert app.count_label.text == "1 of 2" and app.picked[app.preview_index][1] == showing
    app.rotate(1)
    assert ui.said(app.angle_btn) == "+1°", "and the buttons still work on it"


def test_fingers_slide_and_zoom_the_photo(phone):
    app = phone.ready("a.jpg")
    phone.photo("a.jpg", size=(6000, 4000))   # large enough to have room to zoom
    phone.do(app.source.reload())
    phone.edit("a.jpg")
    app.fit_select.value = next(k for k, v in FIT_CHOICES.items() if v == "crop")
    fingers = app.finger_listener.handler
    cx, cy, _ = touch.SHOWN_AT

    def down_and_across():
        fingers(touch.CHANGED, [(cx, cy)])
        fingers(touch.MOVED, [(cx + 40, cy)])
        fingers(touch.MOVED, [(cx + 80, cy)])

    phone.do(press=down_and_across)
    assert app.dragging and app.live.frames, "it is redrawn as the finger moves"
    phone.do(press=lambda: fingers(touch.ENDED, []))
    moved = app.placement()
    assert moved.offset_x < 0 and moved.zoom == 1.0 and not app.dragging
    assert "to reset" in app.hint_label.text

    def pinch():
        fingers(touch.CHANGED, [(cx - 40, cy)])
        fingers(touch.CHANGED, [(cx - 40, cy), (cx + 40, cy)])
        fingers(touch.MOVED, [(cx - 60, cy), (cx + 60, cy)])
        fingers(touch.CHANGED, [(cx - 60, cy)])
        fingers(touch.ENDED, [])

    phone.do(press=pinch)
    assert app.placement().zoom == pytest.approx(1.5)

    app.recentre()
    assert app.placements == {} and app.hint_label.text.startswith("Drag to move")


def test_nothing_that_changes_the_framing_can_be_touched_while_busy(phone):
    app = phone.ready("a.jpg")
    phone.edit("a.jpg")
    controls = (app.ratio_select, app.fit_select, app.border_slider, app.gallery_switch)
    assert all(c.enabled for c in controls)

    app.busy = True
    app.refresh_controls()
    assert not any(c.enabled for c in controls)
    assert not app.save_btn.enabled and not app.cancel_btn.enabled

    app.busy = False
    app.refresh_controls()
    assert all(c.enabled for c in controls)


# --- leaving the editor ------------------------------------------------------------------------

def test_cancel_goes_back_with_the_photos_still_checked(phone):
    app = phone.ready("a.jpg")
    phone.edit("a.jpg")
    phone.do(app.cancel_editing())
    assert app.main_window.content is app.home_box
    assert not app.picked and not app.back.listening
    assert len(app.source.checked) == 1 and app.process_btn.enabled


def test_the_back_gesture_does_what_cancel_does(phone):
    app = phone.ready("a.jpg")
    phone.edit("a.jpg")
    phone.do(press=app.back.action)
    assert app.main_window.content is app.home_box


def test_leaving_with_changes_asks_once_however_often_it_is_pressed(phone):
    app = phone.ready("a.jpg")
    phone.edit("a.jpg")
    app.rotate(3)
    asked, answer = [], asyncio.Event()

    async def ask(title, message):
        asked.append(title)
        await answer.wait()
        return False  # "No": stay in the editor

    app.ask = ask

    async def press_twice_then_answer():
        first = asyncio.ensure_future(app.cancel_editing())
        await asyncio.sleep(0.02)
        app.back.action()                 # the Back gesture, while it is asking
        await app.cancel_editing()        # and Cancel again
        await asyncio.sleep(0.02)
        answer.set()
        await first

    phone.do(press_twice_then_answer())
    assert asked == ["Discard changes?"]
    assert app.main_window.content is app.editor_box, "the answer was No"
    assert app.placements, "and the changes are still there"


# --- saving ---------------------------------------------------------------------------------------

def test_saving_writes_each_photo_to_the_folder_and_the_gallery(phone):
    app = phone.ready("a.jpg", "b.jpg")
    phone.edit("a.jpg", "b.jpg")
    app.rotate(90)
    phone.do(app.save_framed())

    assert phone.out_names() == ["a_ig.jpg", "b_ig.jpg"]
    assert sorted(storage.gallery) == ["a_ig.jpg", "b_ig.jpg"]
    with Image.open(phone.out / "b_ig.jpg") as saved:
        assert saved.size == (1080, 1440)
    assert ui.toasts[-1] == "Saved 2 photos to “Framed” and the gallery"
    assert app.main_window.content is app.home_box
    assert not app.source.checked and not app.process_btn.enabled

    listed = app.target.files.names()
    assert set(listed) == {"a_ig.jpg", "b_ig.jpg"}
    cache = app.target.files.thumbs.cache
    assert all(isinstance(cache.get(n), Image.Image) for n in listed), (
        "the new files show their pictures at once"
    )
    assert Image.open(phone.shots / "a.jpg").size == (1200, 900), "the originals are untouched"


def test_saving_only_to_the_gallery_and_only_to_the_folder(phone):
    phone.photo("a.jpg")
    app = phone.app
    phone.choose(app.source, phone.shots)
    phone.edit("a.jpg")
    phone.do(app.save_framed())
    assert list(storage.gallery) == ["a_ig.jpg"] and phone.out_names() == []
    assert ui.toasts[-1] == "Saved 1 photo to the gallery"

    phone.choose(app.target, phone.out)
    app.gallery_switch.value = False
    phone.edit("a.jpg")
    phone.do(app.save_framed())
    assert phone.out_names() == ["a_ig.jpg"] and list(storage.gallery) == ["a_ig.jpg"]
    assert ui.toasts[-1] == "Saved 1 photo to “Framed”"


def test_with_nowhere_to_save_nothing_is_attempted(phone):
    phone.photo("a.jpg")
    app = phone.app
    phone.choose(app.source, phone.shots)
    app.gallery_switch.value = False
    phone.edit("a.jpg")
    phone.do(app.save_framed())
    assert app.said.startswith("Nowhere to save")
    assert app.main_window.content is app.editor_box


def test_a_name_already_in_the_output_folder_is_stepped_past(phone):
    phone.photo("a_ig.jpg", folder=phone.out)
    app = phone.ready("a.jpg")
    phone.edit("a.jpg")
    phone.do(app.save_framed())
    assert phone.out_names() == ["a_ig.jpg", "a_ig_2.jpg"]


def test_names_are_checked_against_the_whole_folder_not_what_has_arrived(phone):
    """The file whose name would clash is in the half of the folder that
    cloud storage has not delivered yet."""
    for name in ("a_ig.jpg", "m.txt", "n.txt", "z_ig.jpg"):
        (phone.out / name).write_text("x")
    app = phone.ready("z.jpg")
    phone.edit("z.jpg")
    storage.slow[str(phone.out)] = 3
    phone.do(app.save_framed())
    assert "z_ig_2.jpg" in phone.out_names()
    assert not any("(" in name for name in phone.out_names()), (
        "the storage app was never handed a name it already had"
    )


def test_when_the_folder_never_finishes_loading_names_carry_the_time(phone, monkeypatch):
    (phone.out / "a_ig.jpg").write_text("x")
    (phone.out / "b.txt").write_text("x")
    app = phone.ready("a.jpg")
    phone.edit("a.jpg")
    monkeypatch.setattr(browser_module, "WHOLE_SECONDS", 0.05)
    storage.slow[str(phone.out)] = 10_000
    phone.app.loop.run_until_complete(app.save_framed())
    storage.slow.clear()

    new = [n for n in phone.out_names() if n not in ("a_ig.jpg", "b.txt")]
    assert len(new) == 1
    assert new[0].startswith("a_ig_") and len(new[0]) == len("a_ig_153045.jpg")
    assert new[0][5:11].isdigit()


def test_a_save_that_fails_part_way_leaves_no_empty_file(phone):
    app = phone.ready("a.jpg", "b.jpg")
    phone.edit("a.jpg", "b.jpg")
    storage.fail_writes.add("b_ig.jpg")
    phone.do(app.save_framed())

    assert phone.out_names() == ["a_ig.jpg"], "the unfinished file was taken away"
    assert list(storage.gallery) == ["a_ig.jpg"]
    assert app.said.startswith("Not everything was saved: 1 of 2 photos saved.")
    assert "unfinished file" not in app.said
    assert any("unfinished file was removed" in line for line in app.log.lines)


def test_an_unfinished_file_that_cannot_be_removed_is_owned_up_to(phone):
    app = phone.ready("a.jpg")
    phone.edit("a.jpg")
    storage.fail_writes.add("a_ig.jpg")
    storage.fail_deletes.add("a_ig.jpg")
    phone.do(app.save_framed())
    assert phone.out_names() == ["a_ig.jpg"]
    assert "0 of 1 photo saved." in app.said and "unfinished file was left" in app.said


def test_a_gallery_that_refuses_a_photo_is_reported(phone):
    app = phone.ready("a.jpg")
    phone.edit("a.jpg")
    storage.fail_gallery.add("a_ig.jpg")
    phone.do(app.save_framed())
    assert storage.gallery == {} and app.said.startswith("Not everything was saved")


def test_a_folder_that_cannot_be_read_again_does_not_make_the_save_look_failed(phone, monkeypatch):
    app = phone.ready("a.jpg")
    phone.edit("a.jpg")
    real = storage.listing
    calls = {"n": 0}

    def flaky(tree, parent):
        calls["n"] += 1
        if calls["n"] > 1:      # the check before saving works; the re-read after does not
            raise storage.StorageError("offline")
        return real(tree, parent)

    monkeypatch.setattr(storage, "listing", flaky)
    phone.do(app.save_framed())
    assert phone.out_names() == ["a_ig.jpg"]
    assert ui.toasts[-1].startswith("Saved 1 photo")


def test_the_log_never_names_what_was_already_there(phone):
    (phone.shots / "Private trip").mkdir()
    phone.photo("secret-name.jpg", folder=phone.shots / "Private trip")
    app = phone.ready()
    phone.do(press=lambda: app.source.files.press("Private trip"))
    phone.edit("secret-name.jpg")
    phone.do(app.save_framed())
    phone.do(app.target.create_folder("Made here"))
    text = "\n".join(app.log.lines)
    assert "Private trip" not in text and "secret-name" not in text
    assert "Camera" not in text
    assert not any(quoted in text for quoted in ("'Framed'", "“Framed”", "Framed/"))
    assert "Made here" in text, "a folder the app was asked to make may be named"
