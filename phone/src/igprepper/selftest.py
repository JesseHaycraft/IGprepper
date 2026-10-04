"""The build's own check of the app.

Run in an emulator each time a build is made, where nothing can be pressed
by hand: it works the app the way a person would, against the emulator's own
storage, and writes what it finds to the log. A build that logs a FAIL here
is not published.

None of this is reachable from the app's screens. It starts only when the
app is launched with a flag that the build passes.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import time
from datetime import datetime

from PIL import Image

from igprep.core import geometry as g

from . import androidimage, androidui, framing, imagetests, places, storage, touch
from .app import FIT_CHOICES, GUIDE_SECONDS
from .fixtures import FIXTURES

FOLDER = "Download/IGprepper"
LARGE_FILE_MB = 20
TRIAL_FOLDER = "CI test & trial"
MANY_FOLDER = "Many"
MANY = 150
SMALL_PHOTO = "igprepper-test-photo.jpg"
LARGE_PHOTO = "igprepper-test-photo-large.jpg"
TEXT_FILE = "igprepper-test-small.txt"


def verdict(app, ok: bool, text: str) -> None:
    app.log.write(f"{'PASS' if ok else 'FAIL'}  {text}")


async def hold(app, name: str, seconds: float = 10) -> None:
    """Stand still while the emulator run photographs the screen.

    Nothing else can show whether the app looks right before a build is
    published.
    """
    app.log.write(f"SCREENSHOT {name}")
    await asyncio.sleep(seconds)


async def until(condition, seconds: float = 15) -> bool:
    """Wait for something a press has set in motion."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.2)
    return bool(condition())


def shown_text(button) -> str:
    """A button's label as Android has it, icon placeholder removed."""
    return str(button._impl.native.getText()).replace("￼", "").strip()


def is_on(button) -> bool:
    """Asked of Android itself, not of this app's own record of it."""
    return bool(button._impl.native.isEnabled())


def choose(selection, choices: dict, wanted: str) -> None:
    selection.value = next(label for label, value in choices.items() if value == wanted)


def names(browser) -> list[str]:
    return [entry.name for entry in browser.entries]


def press_row(browser, name: str) -> None:
    """Press a row of a list the way a finger would."""
    position = names(browser).index(name)
    browser.files.list.performItemClick(None, position, position)


async def enter(app, browser, name: str) -> bool:
    press_row(browser, name)
    return await until(lambda: browser.trail[-1][1] == name and not app.busy)


async def run(app) -> None:
    log = app.log
    app.unattended = True
    log.section("Automated self-test")
    try:
        ok = await app.work(imagetests.run_all, log, androidimage.decode_to_srgb)
        log.write("")
        log.write("Image tests finished: " + ("all passed." if ok else "something FAILED."))

        if app.source.tree is None and app.target.tree is None:
            # The first thing asked for, and the emulator's camera may not be
            # ready yet.
            await hold(app, "home-first-run", 30)
        await app.target.choose(initial=storage.local_folder_uri(FOLDER))
        if app.target.tree is None:
            log.write("FAIL  No folder was granted, so nothing else can be tested.")
            return

        await output_side(app)
        await test_files(app)
        await input_side(app)
        await editor(app)
        await leaving(app)
        remembered(app)
        await starting_again(app)
    except Exception:
        log.exception("running the self-test")
    finally:
        log.write("=== Self-test finished ===")


# --- the output folder --------------------------------------------------------

async def output_side(app) -> None:
    log, target = app.log, app.target
    log.section("Self-test: the output folder")
    # Back to the granted folder, wherever an earlier run left things.
    while len(target.trail) > 1:
        await target.up()

    await target.create_folder(TRIAL_FOLDER)
    await target.create_folder(TRIAL_FOLDER)
    matching = names(target).count(TRIAL_FOLDER)
    verdict(
        app, matching == 1 and app.said.startswith("Already there"),
        f"Asked twice for the same folder name: {matching} exists, and the "
        "second request was turned down with a message.",
    )

    opened = await enter(app, target, TRIAL_FOLDER)
    verdict(
        app, opened and target.path_label.text.endswith(TRIAL_FOLDER)
        and is_on(target.up_btn),
        f"Pressing a folder opened it: the path ends {target.path_label.text[-24:]!r} "
        "and Up is available.",
    )

    # New folder, through the pop-up.
    await target.new_folder()
    dialog, field = target.name_dialog
    field.setText("Edits")
    await hold(app, "new-folder")
    androidui.press_confirm(dialog)
    made = await until(lambda: "Edits" in names(target) and not app.busy)
    verdict(app, made, "Typing a name and pressing Create made the folder.")

    await target.create_folder(MANY_FOLDER)
    await enter(app, target, "Edits")


def capabilities(log, entry) -> None:
    found = entry.capabilities()
    allowed = [name for name, yes in found.items() if yes]
    refused = [name for name, yes in found.items() if not yes]
    kind = "this folder" if entry.is_dir else "a file created here"
    log.write(f"For {kind}, the storage app allows: " + (", ".join(allowed) or "nothing"))
    if refused:
        log.write("It does not allow: " + ", ".join(refused))


async def test_files(app) -> None:
    target = app.target
    await app.work(write_test_files, app.log, target.tree, target.here)
    above = await app.work(storage.children, target.tree, target.trail[-2][0])
    many = next(e for e in above if e.name == MANY_FOLDER)
    await app.work(write_many, app.log, target.tree, many.doc_id)
    await target.reload()


def write_many(log, tree, parent: str) -> None:
    """A folder with a great many files in it, to see the list cope."""
    have = len(storage.children(tree, parent))
    started = time.perf_counter()
    for number in range(have, MANY):
        storage.create_file(tree, parent, f"photo-{number:03}.jpg", "image/jpeg")
    log.write(
        f"A folder of {MANY} empty files: {MANY - have} created in "
        f"{time.perf_counter() - started:.1f} s."
    )


def write_test_files(log, tree, parent: str) -> None:
    """Each file is its own attempt, so one failure does not hide the rest."""
    log.section("Self-test: writing files")
    capabilities(log, storage.describe(tree, parent))
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        payload = f"IGprepper test file, written {stamp}\n".encode()
        entry = storage.create_file(tree, parent, TEXT_FILE, "text/plain")
        storage.write_bytes(tree, entry.doc_id, payload)
        back = storage.read_bytes(tree, entry.doc_id)
        ok = back == payload
        log.write(
            f"{'PASS' if ok else 'FAIL'}  Small file {entry.name!r}: wrote "
            f"{len(payload)} bytes, read back {len(back)}, "
            f"contents {'match' if ok else 'DIFFER'}"
        )
        capabilities(log, storage.describe(tree, entry.doc_id))
    except Exception:
        log.exception("writing the small test file")

    large = io.BytesIO()
    imagetests.make_test_photo(3000, 2000).save(large, "JPEG", quality=90)
    for name, jpeg in (
        (SMALL_PHOTO, imagetests.framed_test_jpeg()),
        (LARGE_PHOTO, large.getvalue()),
    ):
        try:
            entry = storage.create_file(tree, parent, name, "image/jpeg")
            storage.write_bytes(tree, entry.doc_id, jpeg)
            reported = storage.describe(tree, entry.doc_id).size
            ok = reported in (None, len(jpeg))
            log.write(
                f"{'PASS' if ok else 'FAIL'}  Photo {entry.name!r}: wrote "
                f"{len(jpeg)} bytes; the storage app reports {reported}"
            )
            # The list puts the newest first; make sure one is newer.
            time.sleep(1.2)
        except Exception:
            log.exception("writing a test photo")

    try:
        blob = os.urandom(1 << 20) * LARGE_FILE_MB
        entry = storage.create_file(
            tree, parent, f"igprepper-test-{LARGE_FILE_MB}MB.bin",
            "application/octet-stream",
        )
        started = time.perf_counter()
        storage.write_bytes(tree, entry.doc_id, blob)
        written = time.perf_counter()
        back = storage.read_bytes(tree, entry.doc_id)
        finished = time.perf_counter()
        ok = hashlib.sha256(back).digest() == hashlib.sha256(blob).digest()
        log.write(
            f"{'PASS' if ok else 'FAIL'}  Large file {entry.name!r}: "
            f"{LARGE_FILE_MB} MB written in {written - started:.1f} s, read "
            f"back in {finished - written:.1f} s, "
            f"contents {'match' if ok else 'DIFFER'}"
        )
    except Exception:
        log.exception("writing the large test file")


# --- the input folder ---------------------------------------------------------

async def input_side(app) -> None:
    log, source, target = app.log, app.source, app.target
    log.section("Self-test: the input folder")
    await source.choose(initial=storage.local_folder_uri(FOLDER))
    if source.tree is None:
        log.write("FAIL  No input folder was granted.")
        return
    while len(source.trail) > 1:
        await source.up()
    verdict(
        app, source.new_btn is None and not source.creates,
        "The input side has no New folder button, and asked for read access only.",
    )
    await enter(app, source, TRIAL_FOLDER)

    # A long folder: only the rows on screen should exist.
    started = time.perf_counter()
    await enter(app, source, MANY_FOLDER)
    took = time.perf_counter() - started
    view = source.files.list
    await asyncio.sleep(0.5)
    drawn = view.getChildCount()
    view.setSelection(MANY - 1)
    await asyncio.sleep(1)
    verdict(
        app, len(source.entries) == MANY and 0 < drawn < 30
        and view.getLastVisiblePosition() == MANY - 1,
        f"A folder of {len(source.entries)} files opened in {took:.2f} s with "
        f"{drawn} rows drawn, and scrolled to the last.",
    )
    await source.up()

    await enter(app, source, "Edits")
    listed = names(source)
    verdict(
        app, {SMALL_PHOTO, LARGE_PHOTO, TEXT_FILE} <= set(listed)
        and listed.index(LARGE_PHOTO) < listed.index(SMALL_PHOTO),
        f"The folder lists {len(listed)} files, the newer photo above the older.",
    )

    press_row(source, TEXT_FILE)
    verdict(
        app, not source.checked and "not a photo" in app.said
        and not is_on(app.process_btn),
        "Pressing a text file checked nothing, said why, and left Process "
        "switched off.",
    )

    press_row(source, SMALL_PHOTO)
    press_row(source, LARGE_PHOTO)
    counter = str(source.files.counter.getText())
    verdict(
        app, len(source.checked) == 2 and counter == "2 selected"
        and is_on(app.process_btn),
        f"Pressing two photos checked both: the corner reads {counter!r} and "
        "Process is available.",
    )

    photos = [e for e in source.entries if e.name in (SMALL_PHOTO, LARGE_PHOTO)]
    cache = source.files.thumbs.cache
    pictured = await until(
        lambda: all(hasattr(cache.get(e.doc_id), "getWidth") for e in photos), 20
    )
    verdict(
        app, pictured,
        "Both photos have thumbnails from the storage app"
        + (
            f", {cache[photos[0].doc_id].getWidth()} pixels square."
            if pictured else ": NOT loaded."
        ),
    )

    # The output side shows the same folder, and nothing there can be checked.
    press_row(target, SMALL_PHOTO)
    verdict(
        app, len(source.checked) == 2 and not target.checked,
        "Pressing a photo on the output side checked nothing.",
    )
    await hold(app, "home")

    # What is checked is always in view: leaving the folder lets it go.
    await source.up()
    verdict(
        app, not source.checked and not is_on(app.process_btn)
        and str(source.files.counter.getText()) == "",
        "Going up a folder cleared the checks and switched Process off.",
    )
    await enter(app, source, "Edits")
    press_row(source, SMALL_PHOTO)
    press_row(source, LARGE_PHOTO)


# --- the editor -------------------------------------------------------------------

async def editor(app) -> None:
    """Frame photos as a person would, plus a check they could not see."""
    log, target = app.log, app.target
    log.section("Self-test: rotation and colour together")
    # A Display P3 image stored on its side, as a camera held upright would
    # store it. Android has to convert the colour, and this app has to turn
    # it the right way up.
    fixture = FIXTURES[0]
    source = Image.open(io.BytesIO(fixture["jpeg"]))
    exif = Image.Exif()
    exif[274] = 6
    stored = io.BytesIO()
    source.transpose(Image.Transpose.ROTATE_90).save(
        stored, "JPEG", quality=100, subsampling=0, exif=exif,
        icc_profile=source.info["icc_profile"],
    )
    image = await app.work(
        framing.prepare, stored.getvalue(), androidimage.decode_to_srgb
    )
    turned = image.size == source.size
    worst = 0
    if turned:
        for centre, _, expected in fixture["patches"]:
            got = image.getpixel(centre)
            worst = max(worst, max(abs(a - b) for a, b in zip(got, expected)))
    verdict(
        app, turned and worst <= imagetests.COLOUR_TOLERANCE,
        f"A sideways Display P3 photo came out {image.size[0]} x {image.size[1]}, "
        f"colours within {worst} of the desktop",
    )

    log.section("Self-test: framing two photos")
    before = set(names(target))
    app.process_btn._impl.native.performClick()
    opened = await until(
        lambda: app.main_window.content is app.editor_box and not app.busy
    )
    if not opened:
        log.write("FAIL  Pressing Process did not open the editor.")
        return
    verdict(
        app, len(app.picked) == 2 and app.count_label.text == "1 of 2"
        and is_on(app.next_btn) and is_on(app.previous_btn)
        and shown_text(app.next_btn) == "Next photo"
        and shown_text(app.previous_btn) == "Previous photo"
        and shown_text(app.save_btn) == "Save photos",
        f"The editor opened on {app.count_label.text!r} with "
        f"{shown_text(app.previous_btn)!r} and {shown_text(app.next_btn)!r} "
        f"available, and the save button reads {shown_text(app.save_btn)!r}.",
    )
    last = app.next_btn._impl.native
    verdict(
        app, 0 < last.getRight() <= last.getParent().getWidth(),
        f"The row of photo buttons fits: it ends at {last.getRight()} of "
        f"{last.getParent().getWidth()} pixels.",
    )
    first = app.sizes[0]
    await app.next_photo()
    stepped = app.count_label.text
    await app.previous_photo()
    verdict(
        app, stepped == "2 of 2" and app.count_label.text == "1 of 2"
        and app.sizes.get(1) not in (None, first),
        f"Next showed {stepped!r}, a photo of {app.sizes.get(1)} after one of "
        f"{first}; Previous went back to {app.count_label.text!r}.",
    )
    verdict(
        app, app.hint_label.text.startswith("Drag to move"),
        f"Under the photo: {app.hint_label.text!r}",
    )
    await hold(app, "editor")
    await rotation(app)
    await fingers(app)

    choose(app.ratio_select, app.ratio_choices, "1:1")
    choose(app.fit_select, FIT_CHOICES, "crop")
    app.border_slider.value = 6
    app.rotate(90)
    app.rotate(1)
    app.rotate(1)
    app.clear_guides()
    await app.save_framed()

    verdict(
        app, app.main_window.content is app.home_box
        and app.said == "Saved 2 photos to “Edits” and the gallery",
        f"Saving returned to the first screen and said: {app.said!r}",
    )
    verdict(
        app, not app.source.checked and not is_on(app.process_btn),
        "The photos that were processed are no longer checked.",
    )
    new = [e for e in target.entries if e.name not in before]
    listed_first = [e.name for e in target.entries if not e.is_dir][: len(new)]
    verdict(
        app, len(new) == 2 and set(listed_first) == {e.name for e in new}
        and set(names(app.source)) == set(names(target)),
        f"{len(new)} new files head the output list, and the input list, "
        "looking at the same folder, shows them too.",
    )
    for entry in new:
        data = await app.work(storage.read_bytes, target.tree, entry.doc_id)
        with Image.open(io.BytesIO(data)) as saved:
            verdict(
                app, saved.size == (1080, 1080),
                f"Saved {entry.name!r} as {saved.size[0]} x {saved.size[1]}, "
                "following the settings chosen.",
            )


async def rotation(app) -> None:
    """Press the rotation buttons and see that the screen follows."""
    app.log.section("Self-test: turning a photo")

    # Asked of Android: the row must fit across the screen it is on.
    last = app.turn_btns[-1]._impl.native
    across = last.getParent().getWidth()
    verdict(
        app, 0 < last.getRight() <= across,
        f"The five rotation buttons fit: the last ends at {last.getRight()} "
        f"of {across} pixels.",
    )

    # Long enough for the screen to be photographed with the lines on it.
    app.guide_seconds = 14
    started = time.perf_counter()
    for _ in range(3):
        app.rotate(1)
    each = (time.perf_counter() - started) / 3
    shown = shown_text(app.angle_btn)
    verdict(
        app, shown == framing.angle_label(3) and app.guides_showing,
        f"Three presses of +1: the angle reads {shown}, the guide lines are "
        f"{'showing' if app.guides_showing else 'NOT showing'}, and each "
        f"press redrew the preview in {each:.2f} s.",
    )
    verdict(
        app, "fill the frame" in app.hint_label.text and "to reset" in app.hint_label.text,
        f"Under the tilted photo, in fit mode: {app.hint_label.text!r}",
    )
    await hold(app, "editor-tilted")

    app.guide_seconds = GUIDE_SECONDS
    app.rotate(-90)
    appeared = app.guides_showing
    await asyncio.sleep(GUIDE_SECONDS - 1)
    stayed = app.guides_showing
    await asyncio.sleep(2)
    verdict(
        app, appeared and stayed and not app.guides_showing
        and shown_text(app.angle_btn) == framing.angle_label(-87),
        f"A press of the left quarter turn: the angle reads "
        f"{shown_text(app.angle_btn)}; the guide lines appeared, were still "
        f"there after {GUIDE_SECONDS - 1} s, and had gone after "
        f"{GUIDE_SECONDS + 1} s.",
    )

    app.recentre()
    verdict(
        app, shown_text(app.angle_btn) == framing.angle_label(0)
        and not app.placements and not app.guides_showing,
        f"A press of the angle put the photo back: it reads "
        f"{shown_text(app.angle_btn)}.",
    )


async def fingers(app) -> None:
    """Drag and pinch the photo with touches made the way Android makes
    them, and see that it follows."""
    log = app.log
    log.section("Self-test: dragging and pinching")
    from android.view import MotionEvent

    # A square frame: whichever way the photo lies, it has room to slide.
    choose(app.ratio_select, app.ratio_choices, "1:1")
    choose(app.fit_select, FIT_CHOICES, "crop")
    await asyncio.sleep(1)

    view = app.preview_view._impl.native
    size = app.sizes[app.preview_index]
    box = framing.output_box(app.current_framing())
    centre_x, centre_y, shown_width = touch.shown_at(view)
    scale = framing.OUTPUT_WIDTH / shown_width
    log.write(
        f"The photo is {size[0]} x {size[1]}. The preview is drawn "
        f"{shown_width:.0f} pixels wide, centred at {centre_x:.0f}, "
        f"{centre_y:.0f} in a view {view.getWidth()} x {view.getHeight()}."
    )

    async def touches(*moments) -> None:
        began = touch.now()
        for action, points in moments:
            touch.send(view, action, points, began)
            await asyncio.sleep(0.05)

    def pinch(start: float, end: float):
        """Two fingers either side of the centre, from `start` apart to `end`."""
        second = touch.second_finger

        def pair(apart: float):
            return [(centre_x - apart / 2, centre_y), (centre_x + apart / 2, centre_y)]

        return (
            (MotionEvent.ACTION_DOWN, pair(start)[:1]),
            (second(MotionEvent.ACTION_POINTER_DOWN), pair(start)),
            *[
                (MotionEvent.ACTION_MOVE, pair(start + (end - start) * n / 4))
                for n in range(1, 5)
            ],
            (second(MotionEvent.ACTION_POINTER_UP), pair(end)),
            (MotionEvent.ACTION_UP, pair(end)[:1]),
        )

    # One finger, pulled down and to the right.
    pull = (40, 60)
    app.quick_frames, app.quick_seconds = 0, 0.0
    await touches(
        (MotionEvent.ACTION_DOWN, [(centre_x, centre_y)]),
        *[
            (MotionEvent.ACTION_MOVE,
             [(centre_x + pull[0] * n / 6, centre_y + pull[1] * n / 6)])
            for n in range(1, 7)
        ],
        (MotionEvent.ACTION_UP, [(centre_x + pull[0], centre_y + pull[1])]),
    )
    expected = g.moved(
        size, box, g.Placement(), before=(0, 0),
        after=(pull[0] * scale, pull[1] * scale),
    )
    got = app.placement()
    verdict(
        app, (got.offset_x, got.offset_y) != (0, 0)
        and abs(got.offset_x - expected.offset_x) < 0.01
        and abs(got.offset_y - expected.offset_y) < 0.01 and not app.dragging,
        f"One finger pulled {pull[0]} across and {pull[1]} down slid the photo "
        f"to {got.offset_x:.3f}, {got.offset_y:.3f} of the room it has; exact "
        f"would be {expected.offset_x:.3f}, {expected.offset_y:.3f}.",
    )
    frames = app.quick_frames
    each = app.quick_seconds / frames * 1000 if frames else 0.0
    verdict(
        app, frames > 0,
        f"The photo was redrawn {frames} time(s) while the finger moved, "
        f"in {each:.0f} ms each.",
    )
    await hold(app, "editor-dragged")
    app.recentre()

    limit = g.max_zoom(size, box, app.placement())
    if limit >= 1.5:
        # Room to zoom: a modest pinch should zoom by exactly that much.
        await touches(*pinch(80, 112))
        zoomed = app.placement().zoom
        verdict(
            app, abs(zoomed - 1.4) < 0.01,
            f"Two fingers spread from 80 to 112 pixels apart zoomed to "
            f"{zoomed:.3f}; exact would be 1.400.",
        )
        app.recentre()

    # Spread far apart: zoom, up to the limit and no further.
    await touches(*pinch(80, 400))
    zoomed = app.placement().zoom
    verdict(
        app, limit > 1 and abs(zoomed - limit) < 1e-6,
        f"Two fingers spread to five times apart zoomed to {zoomed:.3f} and "
        f"stopped: the limit for this photo is {limit:.3f}.",
    )

    # And pinched back together: out again, but never smaller than the frame.
    await touches(*pinch(400, 60))
    verdict(
        app, app.placement().zoom == 1.0,
        f"Pinched back together, the zoom returned to "
        f"{app.placement().zoom:.3f}: the photo still fills the frame.",
    )

    # A touch that goes nowhere.
    before = app.placement()
    await touches(
        (MotionEvent.ACTION_DOWN, [(centre_x + 20, centre_y - 20)]),
        (MotionEvent.ACTION_UP, [(centre_x + 20, centre_y - 20)]),
    )
    verdict(app, app.placement() == before, "A tap moved nothing.")

    app.recentre()
    verdict(
        app, not app.placements,
        "A press of the angle put the photo back in the middle.",
    )


async def leaving(app) -> None:
    """One photo, and backing out of the editor without saving."""
    log, source = app.log, app.source
    log.section("Self-test: one photo, and leaving the editor")
    press_row(source, SMALL_PHOTO)
    app.process_btn._impl.native.performClick()
    opened = await until(
        lambda: app.main_window.content is app.editor_box and not app.busy
    )
    if not opened:
        log.write("FAIL  Pressing Process did not open the editor.")
        return
    verdict(
        app, app.count_label.text == "1 of 1"
        and not is_on(app.next_btn) and not is_on(app.previous_btn)
        and shown_text(app.save_btn) == "Save photo",
        "With one photo loaded, the next and previous buttons are switched off "
        f"and the save button reads {shown_text(app.save_btn)!r}.",
    )
    await hold(app, "editor-one-photo")

    app.rotate(1)
    app.clear_guides()
    listening = app.back.listening
    # What Android calls for the Back gesture, where it lets an app answer.
    app.on_back()
    left = await until(lambda: app.main_window.content is app.home_box)
    verdict(
        app, left and not app.picked and not app.back.listening
        and len(source.checked) == 1 and is_on(app.process_btn),
        "Back from the editor returned to the first screen without closing "
        "the app, with the photo still checked.",
    )
    log.write(
        "The Back gesture itself: "
        + (
            "the app was listening for it while the editor was open."
            if listening
            else "cannot be intercepted on this version of Android, so this "
            "checked only what the app does when told."
        )
    )


def remembered(app) -> None:
    """Both folders, and where each was looking, are on record for next time."""
    app.log.section("Self-test: remembering the folders")
    noted = places.load(app.places_file())
    ok = all(
        noted[b.side].tree == storage.address(b.tree)
        and noted[b.side].trail == b.trail and len(b.trail) == 3
        for b in app.browsers
    )
    verdict(
        app, ok,
        "Both folders are on record, each two levels down from the folder granted.",
    )
    held = all(
        storage.held(noted[b.side].tree, write=b.creates) is not None
        for b in app.browsers
    )
    verdict(app, held, "Access to both is recorded as lasting beyond this session.")


async def starting_again(app) -> None:
    """What the next launch will find, tried without waiting for one."""
    log = app.log
    log.section("Self-test: starting again")
    was = {b.side: (storage.address(b.tree), list(b.trail)) for b in app.browsers}

    def forget() -> None:
        for browser in app.browsers:
            browser.tree, browser.trail, browser.entries = None, [], []
            browser.checked = set()
            # A fresh launch starts with empty screens; so must this.
            browser.show_path()
            browser.show_rows(fresh=True)

    # As after closing the app: nothing in memory, the record on disk.
    forget()
    await app.restore_places()
    verdict(
        app,
        all(
            b.tree is not None and (storage.address(b.tree), b.trail) == was[b.side]
            and b.entries
            for b in app.browsers
        ),
        "From the record alone, both sides came back in the folders they were "
        "in, with their files listed.",
    )

    # As an earlier version of the app left things: one folder it could write
    # to, and no record. That folder was where framed photos went.
    forget()
    app.places_file().unlink()
    await app.restore_places()
    target, source = app.target, app.source
    verdict(
        app,
        target.tree is not None and storage.address(target.tree) == was["output"][0]
        and len(target.trail) == 1 and source.tree is None
        and source.path_label.text == "No folder chosen",
        "With no record, the one folder an earlier version held became the "
        "output folder, and the input side asks for one.",
    )
