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

from . import androidimage, androidui, framing, imagetests, storage, touch
from .app import FIT_CHOICES, GUIDE_SECONDS
from .fixtures import FIXTURES

FOLDER = "Download/IGprepper"
LARGE_FILE_MB = 20
TRIAL_FOLDER = "CI test & trial"


def verdict(app, ok: bool, text: str) -> None:
    app.log.write(f"{'PASS' if ok else 'FAIL'}  {text}")


async def hold(app, name: str) -> None:
    """Stand still while the emulator run photographs the screen.

    Nothing else can show whether the app looks right before a build is
    published.
    """
    app.log.write(f"SCREENSHOT {name}")
    await asyncio.sleep(10)


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


def choose(selection, choices: dict, wanted: str) -> None:
    selection.value = next(label for label, value in choices.items() if value == wanted)


async def run(app) -> None:
    log = app.log
    app.unattended = True
    log.section("Automated self-test")
    try:
        ok = await app.work(imagetests.run_all, log, androidimage.decode_to_srgb)
        log.write("")
        log.write("Image tests finished: " + ("all passed." if ok else "something FAILED."))

        if app.tree is None:
            await hold(app, "home-first-run")
        await app.choose_folder(initial=storage.local_folder_uri(FOLDER))
        if app.tree is None:
            log.write("FAIL  No folder was granted, so nothing else can be tested.")
            return

        await folders(app)
        await test_files(app)
        await editor(app)
        await leaving(app)

        await app.go_up()
        held = storage.persisted_folder() is not None
        verdict(app, held, "Folder access is recorded as lasting beyond this session.")
    except Exception:
        log.exception("running the self-test")
    finally:
        log.write("=== Self-test finished ===")


# --- the first screen -----------------------------------------------------------

async def folders(app) -> None:
    log = app.log
    log.section("Self-test: folders")

    await app.create_folder(TRIAL_FOLDER)
    await app.create_folder(TRIAL_FOLDER)
    matching = [e for e in app.subfolders if e.name == TRIAL_FOLDER]
    verdict(
        app, len(matching) == 1 and app.said.startswith("Already there"),
        f"Asked twice for the same folder name: {len(matching)} exists, and the "
        "second request was turned down with a message.",
    )

    labels = [shown_text(row) for row in app.folder_rows]
    verdict(
        app, len(labels) == len(app.subfolders) and TRIAL_FOLDER in labels,
        f"The list shows {len(labels)} folder(s), the new one among them.",
    )

    # Open it the way a finger would: by pressing its row.
    row = app.folder_rows[labels.index(TRIAL_FOLDER)]
    row._impl.native.performClick()
    opened = await until(lambda: app.trail[-1][1] == TRIAL_FOLDER and not app.busy)
    verdict(
        app, opened and app.folder_label.text == TRIAL_FOLDER
        and bool(app.up_btn._impl.native.isEnabled()),
        f"Pressing a folder opened it: the heading reads {app.folder_label.text!r} "
        "and Up is available.",
    )

    # New folder, through the pop-up.
    await app.new_folder()
    dialog, field = app.name_dialog
    field.setText("Edits")
    await hold(app, "new-folder")
    androidui.press_confirm(dialog)
    made = await until(
        lambda: any(e.name == "Edits" for e in app.subfolders) and not app.busy
    )
    verdict(app, made, "Typing a name and pressing Create made the folder.")
    await hold(app, "home")

    labels = [shown_text(row) for row in app.folder_rows]
    app.folder_rows[labels.index("Edits")]._impl.native.performClick()
    await until(lambda: app.trail[-1][1] == "Edits" and not app.busy)


def capabilities(log, entry: storage.Entry) -> None:
    found = entry.capabilities()
    allowed = [name for name, yes in found.items() if yes]
    refused = [name for name, yes in found.items() if not yes]
    kind = "this folder" if entry.is_dir else "a file created here"
    log.write(f"For {kind}, the storage app allows: " + (", ".join(allowed) or "nothing"))
    if refused:
        log.write("It does not allow: " + ", ".join(refused))


async def test_files(app) -> None:
    await app.work(write_test_files, app.log, app.tree, app.here)
    await app.refresh_listing()


def write_test_files(log, tree, parent: str) -> None:
    """Each file is its own attempt, so one failure does not hide the rest."""
    log.section("Self-test: writing files")
    capabilities(log, storage.describe(tree, parent))
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    name = "igprepper-test-small.txt"

    try:
        payload = f"IGprepper test file, written {stamp}\n".encode()
        entry = storage.create_file(tree, parent, name, "text/plain")
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

    try:
        jpeg = imagetests.framed_test_jpeg()
        entry = storage.create_file(tree, parent, "igprepper-test-photo.jpg", "image/jpeg")
        storage.write_bytes(tree, entry.doc_id, jpeg)
        reported = storage.describe(tree, entry.doc_id).size
        ok = reported in (None, len(jpeg))
        log.write(
            f"{'PASS' if ok else 'FAIL'}  Photo {entry.name!r}: wrote "
            f"{len(jpeg)} bytes; the storage app reports {reported}"
        )
    except Exception:
        log.exception("writing the test photo")

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


# --- the editor -------------------------------------------------------------------

async def editor(app) -> None:
    """Frame a photo as a person would, plus a check they could not see."""
    log = app.log
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

    log.section("Self-test: framing a photo from the folder")
    before = {e.name for e in await app.work(storage.children, app.tree, app.here)}
    await app.select_photos(initial=storage.folder_address(app.tree, app.here))
    if not app.picked:
        log.write("FAIL  No photo came back from the picker.")
        return
    verdict(
        app, app.main_window.content is app.editor_box,
        "The editor opened with a preview.",
    )
    # Asked of Android itself, not of this app's own record of it.
    stepping_off = not (
        bool(app.next_btn._impl.native.isEnabled())
        or bool(app.previous_btn._impl.native.isEnabled())
    )
    verdict(
        app, stepping_off and shown_text(app.save_btn) == "Save",
        "With one photo chosen, the next and previous buttons are switched off "
        f"and the save button reads {shown_text(app.save_btn)!r}.",
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
        and app.said == "Saved 1 photo to “Edits” and the gallery",
        f"Saving returned to the first screen and said: {app.said!r}",
    )
    after = await app.work(storage.children, app.tree, app.here)
    new = [e for e in after if e.name not in before]
    if len(new) != 1:
        log.write(f"FAIL  Expected one new file in the folder, found {len(new)}.")
        return
    data = await app.work(storage.read_bytes, app.tree, new[0].doc_id)
    with Image.open(io.BytesIO(data)) as saved:
        verdict(
            app, saved.size == (1080, 1080),
            f"Saved {new[0].name!r} as {saved.size[0]} x {saved.size[1]}, "
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

    # A square frame on a tall photo: room to slide up and down.
    choose(app.ratio_select, app.ratio_choices, "1:1")
    choose(app.fit_select, FIT_CHOICES, "crop")
    await asyncio.sleep(1)

    view = app.preview_view._impl.native
    size = app.sizes[app.preview_index]
    box = framing.output_box(app.current_framing())
    centre_x, centre_y, shown_width = touch.shown_at(view)
    log.write(
        f"The preview is drawn {shown_width:.0f} pixels wide, centred at "
        f"{centre_x:.0f}, {centre_y:.0f} in a view {view.getWidth()} x "
        f"{view.getHeight()}."
    )

    async def touches(*moments) -> None:
        began = touch.now()
        for action, points in moments:
            touch.send(view, action, points, began)
            await asyncio.sleep(0.05)

    # One finger, pulled straight down.
    pull = 60
    app.quick_frames, app.quick_seconds = 0, 0.0
    await touches(
        (MotionEvent.ACTION_DOWN, [(centre_x, centre_y)]),
        *[
            (MotionEvent.ACTION_MOVE, [(centre_x, centre_y + pull * n / 6)])
            for n in range(1, 7)
        ],
        (MotionEvent.ACTION_UP, [(centre_x, centre_y + pull)]),
    )
    expected = g.moved(
        size, box, g.Placement(), before=(0, 0),
        after=(0, pull * framing.OUTPUT_WIDTH / shown_width),
    )
    got = app.placement()
    verdict(
        app, got.offset_y < 0 and abs(got.offset_y - expected.offset_y) < 0.01
        and got.offset_x == 0 and not app.dragging,
        f"One finger pulled down {pull} pixels slid the photo down by "
        f"{-got.offset_y:.3f} of the room it has; exact would be "
        f"{-expected.offset_y:.3f}.",
    )
    frames = app.quick_frames
    each = app.quick_seconds / frames * 1000 if frames else 0.0
    verdict(
        app, frames > 0,
        f"The photo was redrawn {frames} time(s) while the finger moved, "
        f"in {each:.0f} ms each.",
    )
    await hold(app, "editor-dragged")

    # Two fingers, spread far apart: zoom, up to the limit and no further.
    limit = g.max_zoom(size, box, app.placement())
    second = touch.second_finger
    await touches(
        (MotionEvent.ACTION_DOWN, [(centre_x - 40, centre_y)]),
        (second(MotionEvent.ACTION_POINTER_DOWN),
         [(centre_x - 40, centre_y), (centre_x + 40, centre_y)]),
        *[
            (MotionEvent.ACTION_MOVE,
             [(centre_x - 40 - 30 * n, centre_y), (centre_x + 40 + 30 * n, centre_y)])
            for n in range(1, 5)
        ],
        (second(MotionEvent.ACTION_POINTER_UP),
         [(centre_x - 160, centre_y), (centre_x + 160, centre_y)]),
        (MotionEvent.ACTION_UP, [(centre_x - 160, centre_y)]),
    )
    zoomed = app.placement().zoom
    verdict(
        app, limit > 1 and abs(zoomed - limit) < 1e-6,
        f"Two fingers spread to four times apart zoomed to {zoomed:.3f} and "
        f"stopped: the limit for this photo is {limit:.3f}.",
    )

    # And pinched back together: out again, but never smaller than the frame.
    await touches(
        (MotionEvent.ACTION_DOWN, [(centre_x - 160, centre_y)]),
        (second(MotionEvent.ACTION_POINTER_DOWN),
         [(centre_x - 160, centre_y), (centre_x + 160, centre_y)]),
        *[
            (MotionEvent.ACTION_MOVE,
             [(centre_x - 160 + 30 * n, centre_y), (centre_x + 160 - 30 * n, centre_y)])
            for n in range(1, 5)
        ],
        (second(MotionEvent.ACTION_POINTER_UP),
         [(centre_x - 40, centre_y), (centre_x + 40, centre_y)]),
        (MotionEvent.ACTION_UP, [(centre_x - 40, centre_y)]),
    )
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
    """Back out of the editor without saving."""
    log = app.log
    log.section("Self-test: leaving the editor")
    await app.select_photos(initial=storage.folder_address(app.tree, app.here))
    if not app.picked:
        log.write("FAIL  No photo came back from the picker.")
        return
    app.rotate(1)
    app.clear_guides()
    listening = app.back.listening
    # What Android calls for the Back gesture, where it lets an app answer.
    app.on_back()
    left = await until(lambda: app.main_window.content is app.home_box)
    verdict(
        app, left and not app.picked and not app.back.listening,
        "Back from the editor returned to the first screen and dropped the "
        "photo, without closing the app.",
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
