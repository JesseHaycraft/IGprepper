"""IGprepper phone app.

It works inside whichever folder is chosen in Android's folder picker, so it
is tied to no particular storage. Today that means Google Drive or the phone
itself; Proton Drive does not yet offer its folders to other apps.

Its purpose: choose photos, frame them with a live preview, position each
one by hand -- drag, pinch, turn, tilt -- and save the results into the
current folder and the phone's gallery. The diagnostic buttons from the
earlier builds remain.

The app never invents a folder name. Folders are created only when a name is
typed and the button pressed, exactly as typed.

The log records what the app did, including the names of folders it was asked
to create. It does not record what was already in the storage: existing
folders appear on screen but are never written to the log.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import platform
import sys
import time
from datetime import datetime

import toga
from PIL import Image
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from igprep.core import geometry as g
from igprep.core.preview import make_proxy
from igprep.core.settings import Framing

from . import androidimage, framing, gestures, imagetests, storage, touch
from .fixtures import FIXTURES
from .phonelog import PhoneLog

# Android draws a switched-off button almost exactly like a working one, so
# the two states are given colours of their own.
BUTTON_ON = {"color": "#FFFFFF", "background_color": "#56575C"}
BUTTON_OFF = {"color": "#6F7075", "background_color": "#232427"}
FIT_CHOICES = {"Fit the whole photo": "fit", "Crop to fill the frame": "crop"}
# The rotation buttons, left to right, either side of the angle itself.
TURN_LEFT = (("\u221290\u00b0", -90), ("\u22121\u00b0", -1))
TURN_RIGHT = (("+1\u00b0", 1), ("+90\u00b0", 90))
# How long the guide lines stay after the last press of a rotation button.
GUIDE_SECONDS = 3
LARGE_FILE_MB = 20
SELF_TEST_FOLDER = "Download/IGprepper"


class IGprepperTest(toga.App):
    def startup(self) -> None:
        self.log = PhoneLog()
        self.log.install_excepthook()

        self.tree = None
        # The path from the chosen folder down to where we are: (id, name).
        self.trail: list[tuple[str, str]] = []
        # Folders this app created, whose names may therefore be logged.
        self.created: set[str] = set()
        self.subfolders: list[storage.Entry] = []
        self.busy = False

        # The photos chosen for framing: (address, filename). Only a small
        # proxy of each is kept, and only once it has been looked at; holding
        # every photo at full size would exhaust the phone's memory.
        self.picked: list[tuple[object, str]] = []
        self.proxies: dict[int, Image.Image] = {}
        self.preview_index = 0
        self.sizes: dict[int, tuple[int, int]] = {}
        self.quick_proxies: dict[int, Image.Image] = {}
        # How each photo has been positioned by hand. Ratio, fit and border
        # are shared by the batch; this belongs to one photo.
        self.placements: dict[int, g.Placement] = {}
        self.tracker = gestures.Tracker()
        self.dragging = False
        self.redraw_pending = False
        self.quick_frames, self.quick_seconds = 0, 0.0
        self.preview_plain: Image.Image | None = None
        self.guides_showing = False
        self.guide_timer = None
        self.guide_seconds = GUIDE_SECONDS

        self.build_screen()
        self.build_framing_screen()
        self.output.value = "\n".join(self.log.lines)
        self.log.listeners.append(self.show_line)

        self.guard("describing the phone", self.report_environment)
        self.guard("darkening the system bars", self.darken_system_bars)
        self.refresh_controls()

    def build_screen(self) -> None:
        heading = toga.Label(f"IGprepper {self.version}")
        self.choose_btn = toga.Button(
            "Choose a folder", on_press=self.choose_folder, style=Pack(margin_top=6)
        )
        self.where_label = toga.Label("No folder chosen yet", style=Pack(margin_top=6))

        self.folder_select = toga.Selection(items=[], style=Pack(flex=1))
        self.open_btn = toga.Button("Open", on_press=self.open_selected)
        self.up_btn = toga.Button("Up", on_press=self.go_up)
        navigate = toga.Box(
            children=[self.folder_select, self.open_btn, self.up_btn],
            style=Pack(direction=ROW, margin_top=6),
        )

        self.name_input = toga.TextInput(
            placeholder="New folder name", style=Pack(flex=1)
        )
        self.create_btn = toga.Button("Create folder", on_press=self.create_folder)
        create = toga.Box(
            children=[self.name_input, self.create_btn],
            style=Pack(direction=ROW, margin_top=6),
        )

        self.files_btn = toga.Button(
            "Write test files here",
            on_press=self.write_test_files,
            style=Pack(margin_top=6),
        )
        self.images_btn = toga.Button(
            "Run image tests", on_press=self.run_image_tests, style=Pack(margin_top=6)
        )
        self.frame_btn = toga.Button(
            "Frame photos", on_press=self.frame_photos, style=Pack(margin_top=6)
        )
        self.output = toga.MultilineTextInput(
            readonly=True, style=Pack(flex=1, margin_top=8)
        )

        self.main_box = toga.Box(
            children=[
                heading, self.choose_btn, self.where_label, navigate, create,
                self.frame_btn, self.files_btn, self.images_btn, self.output,
            ],
            style=Pack(direction=COLUMN, margin=12),
        )
        self.main_window = toga.MainWindow(title=self.formal_name)
        self.main_window.content = self.main_box
        self.main_window.show()

    def build_framing_screen(self) -> None:
        """Preview on top, the framing controls beneath it."""
        self.batch_label = toga.Label("")
        self.preview_view = toga.ImageView(style=Pack(flex=1, margin_top=6))
        self.guard("listening for fingers on the photo", self.listen_for_fingers)

        def turner(degrees: int):
            return lambda widget: self.rotate(degrees)

        def turn_button(label: str, degrees: int) -> toga.Button:
            return toga.Button(label, on_press=turner(degrees), style=Pack(flex=1))

        # The middle button shows the angle; pressing it puts the photo back.
        self.angle_btn = toga.Button(
            framing.angle_label(0), on_press=self.recentre, style=Pack(flex=1)
        )
        self.turn_btns = (
            [turn_button(*spec) for spec in TURN_LEFT]
            + [self.angle_btn]
            + [turn_button(*spec) for spec in TURN_RIGHT]
        )
        for button in self.turn_btns:
            self.guard("narrowing a rotation button", lambda b=button: self.narrow(b))
        turning = toga.Box(
            children=self.turn_btns, style=Pack(direction=ROW, margin_top=6)
        )

        self.ratio_choices = {f"{r.key}  {r.label}": r.key for r in g.RATIOS}
        self.ratio_select = toga.Selection(
            items=list(self.ratio_choices), on_change=self.update_preview,
            style=Pack(flex=1),
        )
        self.ratio_select.value = next(
            label for label, key in self.ratio_choices.items()
            if key == g.DEFAULT_RATIO
        )
        self.fit_select = toga.Selection(
            items=list(FIT_CHOICES), on_change=self.update_preview,
            style=Pack(flex=1),
        )
        choices = toga.Box(
            children=[self.ratio_select, self.fit_select],
            style=Pack(direction=ROW, margin_top=6),
        )

        self.border_label = toga.Label("Border", style=Pack(width=96))
        self.border_slider = toga.Slider(
            min=0, max=15, value=g.DEFAULT_BORDER_PCT, tick_count=31,
            on_change=self.update_preview, style=Pack(flex=1),
        )
        border = toga.Box(
            children=[self.border_label, self.border_slider],
            style=Pack(direction=ROW, margin_top=6),
        )

        self.gallery_switch = toga.Switch(
            "Also save to the phone's gallery", value=True, style=Pack(margin_top=6)
        )
        self.back_btn = toga.Button("Back", on_press=self.leave_framing)
        self.next_btn = toga.Button("Next photo", on_press=self.next_photo)
        self.save_btn = toga.Button(
            "Save", on_press=self.save_framed, style=Pack(flex=1)
        )
        actions = toga.Box(
            children=[self.back_btn, self.next_btn, self.save_btn],
            style=Pack(direction=ROW, margin_top=6),
        )

        self.framing_box = toga.Box(
            children=[
                self.batch_label, self.preview_view, turning, choices, border,
                self.gallery_switch, actions,
            ],
            style=Pack(direction=COLUMN, margin=12),
        )

    async def on_running(self) -> None:
        """Once the screen is up: pick up last session's folder, if any."""
        await self.restore_folder()
        self.log.write("")
        self.log.write("=== Ready ===")
        if self.self_test_requested():
            await self.self_test()

    # --- plumbing ---------------------------------------------------------

    def show_line(self, line: str) -> None:
        # Log lines can arrive from a worker thread; the screen cannot be
        # touched from one.
        self.loop.call_soon_threadsafe(self._append_line, line)

    def _append_line(self, line: str) -> None:
        self.output.value = (self.output.value or "") + "\n" + line

    def guard(self, doing: str, function) -> None:
        try:
            function()
        except Exception:
            self.log.exception(doing)

    async def work(self, function, *args):
        """Run something slow off the screen's thread."""
        return await asyncio.get_running_loop().run_in_executor(None, function, *args)

    def darken_system_bars(self) -> None:
        """The strips above and below the app, which the theme leaves light."""
        from android.graphics import Color
        from org.beeware.android import MainActivity

        window = MainActivity.singletonThis.getWindow()
        window.setStatusBarColor(Color.BLACK)
        window.setNavigationBarColor(Color.BLACK)

    def narrow(self, button) -> None:
        """Let a button be as narrow as its label, so five fit in a row.

        Android gives every button a generous minimum width, and five of
        those are wider than the screen.
        """
        native = button._impl.native
        native.setMinWidth(0)
        native.setMinimumWidth(0)
        button.refresh()

    def switch(self, button, on: bool) -> None:
        """Enable or disable a button, and make the difference visible."""
        button.enabled = on
        button.style.update(**(BUTTON_ON if on else BUTTON_OFF))

    def refresh_controls(self) -> None:
        have_folder = self.tree is not None
        free = not self.busy
        self.switch(self.choose_btn, free)
        self.switch(self.images_btn, free)
        self.switch(self.frame_btn, free)
        self.switch(self.back_btn, free)
        self.switch(self.save_btn, free and bool(self.picked))
        self.switch(self.next_btn, free and len(self.picked) > 1)
        for button in self.turn_btns:
            self.switch(button, free and bool(self.picked))
        self.switch(self.open_btn, free and have_folder and bool(self.subfolders))
        self.switch(self.up_btn, free and len(self.trail) > 1)
        self.switch(self.create_btn, free and have_folder)
        self.switch(self.files_btn, free and have_folder)

    async def exclusively(self, doing: str, coroutine) -> None:
        """Run one action at a time, and never let it fail silently."""
        if self.busy:
            coroutine.close()
            return
        self.busy = True
        self.refresh_controls()
        try:
            await coroutine
        except Exception:
            self.log.exception(doing)
        finally:
            self.busy = False
            self.refresh_controls()

    @property
    def here(self) -> str:
        return self.trail[-1][0]

    # --- what the phone is --------------------------------------------------

    def report_environment(self) -> None:
        log = self.log
        log.section(f"IGprepper phone app, version {self.version}")
        log.write(f"Log file: {log.location}")

        from android.os import Build

        log.write(f"Android {Build.VERSION.RELEASE} (API {Build.VERSION.SDK_INT})")
        log.write(f"Model: {Build.MANUFACTURER} {Build.MODEL}")
        log.write(f"Python {sys.version.split()[0]} on {platform.machine()}")

    # --- choosing and moving around ---------------------------------------

    async def choose_folder(self, widget=None, initial=None) -> None:
        await self.exclusively("choosing a folder", self._choose_folder(initial))

    async def _choose_folder(self, initial) -> None:
        self.log.section("Choosing a folder")
        tree = await storage.pick_folder(self, initial)
        if tree is None:
            self.log.write("The picker was closed without a folder being chosen.")
            return
        await self.open_tree(tree, "granted through the picker")

    async def restore_folder(self) -> None:
        try:
            tree = storage.persisted_folder()
            if tree is None:
                return
            self.log.section("Folder access from an earlier session")
            await self.open_tree(tree, "still held, with no trip through the picker")
        except Exception:
            self.log.exception("restoring folder access")
        self.refresh_controls()

    async def open_tree(self, tree, how: str) -> None:
        root = await self.work(storage.describe, tree, storage.root_id(tree))
        self.tree = tree
        self.trail = [(root.doc_id, root.name)]
        self.created = set()
        self.log.write(f"PASS  Folder access {how}.")
        self.log.write(f"Storage app: {storage.provider_name(tree)}")
        self.report_capabilities(root)
        await self.refresh_listing()

    def report_capabilities(self, entry: storage.Entry) -> None:
        capabilities = entry.capabilities()
        allowed = [name for name, yes in capabilities.items() if yes]
        refused = [name for name, yes in capabilities.items() if not yes]
        kind = "this folder" if entry.is_dir else "a file created here"
        self.log.write(
            f"For {kind}, the storage app allows: " + (", ".join(allowed) or "nothing")
        )
        if refused:
            self.log.write("It does not allow: " + ", ".join(refused))

    async def refresh_listing(self) -> None:
        entries = await self.work(storage.children, self.tree, self.here)
        self.subfolders = sorted(
            (e for e in entries if e.is_dir), key=lambda e: e.name.lower()
        )
        files = sum(1 for e in entries if not e.is_dir)
        self.folder_select.items = [e.name for e in self.subfolders]
        self.where_label.text = " / ".join(name for _, name in self.trail)
        self.log.write(
            f"This folder holds {len(self.subfolders)} folder(s) and {files} "
            "file(s). Names are not logged."
        )
        self.refresh_controls()

    async def open_selected(self, widget=None) -> None:
        await self.exclusively("opening a folder", self._open_selected())

    async def _open_selected(self) -> None:
        chosen = self.folder_select.value
        entry = next((e for e in self.subfolders if e.name == chosen), None)
        if entry is None:
            self.log.write("There is no folder selected to open.")
            return
        self.trail.append((entry.doc_id, entry.name))
        if entry.doc_id in self.created:
            self.log.write(f"Opened {entry.name!r}, {len(self.trail) - 1} level(s) down.")
        else:
            self.log.write(
                f"Opened an existing folder, {len(self.trail) - 1} level(s) down. "
                "Its name is not logged."
            )
        await self.refresh_listing()

    async def go_up(self, widget=None) -> None:
        await self.exclusively("going up a folder", self._go_up())

    async def _go_up(self) -> None:
        if len(self.trail) <= 1:
            self.log.write("Already at the top of the chosen folder.")
            return
        self.trail.pop()
        self.log.write(f"Went up, now {len(self.trail) - 1} level(s) down.")
        await self.refresh_listing()

    # --- creating a folder --------------------------------------------------

    async def create_folder(self, widget=None) -> None:
        await self.exclusively("creating a folder", self._create_folder())

    async def _create_folder(self) -> None:
        name = (self.name_input.value or "").strip()
        if not name:
            self.log.write("Type a folder name first.")
            return
        self.log.section("Creating a folder")
        if any(e.name == name for e in self.subfolders):
            self.log.write(
                f"A folder called {name!r} is already here. Asking the storage "
                "app to create it anyway, to see what it does."
            )
        entry = await self.work(storage.create_folder, self.tree, self.here, name)
        self.created.add(entry.doc_id)
        if entry.name == name:
            self.log.write(f"PASS  Created {entry.name!r}, exactly as typed.")
        else:
            self.log.write(
                f"INFO  Asked for {name!r}; the storage app created {entry.name!r}."
            )
        self.name_input.value = ""
        await self.refresh_listing()
        try:
            self.folder_select.value = entry.name
        except Exception:
            pass  # purely a convenience; the folder is in the list either way

    # --- test files ---------------------------------------------------------

    async def write_test_files(self, widget=None) -> None:
        await self.exclusively("writing the test files", self._write_test_files())

    async def _write_test_files(self) -> None:
        await self.work(self.write_test_files_now, self.tree, self.here)
        await self.refresh_listing()

    def write_test_files_now(self, tree, parent: str) -> None:
        """Each file is its own attempt, so one failure does not hide the rest."""
        log = self.log
        log.section("Test files")
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
            self.report_capabilities(storage.describe(tree, entry.doc_id))
        except Exception:
            log.exception("writing the small test file")

        try:
            again = storage.create_file(tree, parent, name, "text/plain")
            storage.write_bytes(tree, again.doc_id, b"Second file, same name requested\n")
            log.write(
                f"INFO  Asked for {name!r} a second time; the storage app "
                f"called this one {again.name!r}"
            )
        except Exception:
            log.exception("writing a second file under the same name")

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

        log.write("Test files finished. Check in the storage app that they appear.")

    # --- framing photos -----------------------------------------------------

    def current_framing(self) -> Framing:
        return Framing(
            ratio=self.ratio_choices.get(self.ratio_select.value, g.DEFAULT_RATIO),
            mode=FIT_CHOICES.get(self.fit_select.value, "fit"),
            border_pct=round(float(self.border_slider.value) * 2) / 2,
        )

    async def frame_photos(self, widget=None, initial=None) -> None:
        await self.exclusively("choosing photos", self._frame_photos(initial))

    async def _frame_photos(self, initial) -> None:
        self.log.section("Framing photos")
        addresses = await storage.pick_photos(self, initial)
        if not addresses:
            self.log.write("No photos were chosen.")
            return
        self.picked = []
        for address in addresses:
            name = await self.work(storage.display_name, address)
            self.picked.append((address, name))
        self.proxies, self.sizes, self.quick_proxies = {}, {}, {}
        self.placements = {}
        self.preview_index = 0
        self.log.write(f"{len(self.picked)} photo(s) chosen. Names are not logged.")
        await self.show_photo()
        self.main_window.content = self.framing_box

    def load_proxy(self, address) -> tuple[Image.Image, tuple[int, int]]:
        data = storage.read_uri(address)
        image = framing.prepare(data, androidimage.decode_to_srgb)
        return make_proxy(image), image.size

    async def show_photo(self) -> None:
        index = self.preview_index
        if index not in self.proxies:
            started = time.perf_counter()
            proxy, size = await self.work(self.load_proxy, self.picked[index][0])
            self.proxies[index] = proxy
            self.sizes[index] = size
            self.log.write(
                f"Photo {index + 1}: opened at {size[0]} x {size[1]} in "
                f"{time.perf_counter() - started:.2f} s"
            )
        self.clear_guides()
        self.tracker.ended()
        self.dragging = False
        self.update_preview()

    def placement(self) -> g.Placement:
        return self.placements.get(self.preview_index, g.Placement())

    def place(self, placement: g.Placement) -> None:
        """Record where the photo on screen now sits. One left exactly as it
        was opened is not recorded at all."""
        if placement == g.Placement():
            self.placements.pop(self.preview_index, None)
        else:
            self.placements[self.preview_index] = placement

    def update_preview(self, widget=None) -> None:
        proxy = self.proxies.get(self.preview_index)
        if proxy is None:
            return
        try:
            chosen = self.current_framing()
            # A change of ratio or border moves the zoom limit.
            self.place(
                g.within_limits(
                    self.sizes[self.preview_index], framing.output_box(chosen),
                    self.placement(),
                )
            )
            placement = self.placement()
            self.border_label.text = f"Border {chosen.border_pct:g}%"
            self.angle_btn.text = framing.angle_label(placement.angle)
            note = ""
            if placement.positioned and chosen.mode == "fit":
                # A photo shown whole has no position to adjust.
                note = " - positioned by hand, so it fills the frame"
            self.batch_label.text = (
                f"Photo {self.preview_index + 1} of {len(self.picked)}{note}"
            )
            self.preview_plain = framing.preview(proxy, chosen, placement)
            self.draw_preview()
        except Exception:
            self.log.exception("drawing the preview")

    def draw_preview(self) -> None:
        image = self.preview_plain
        if image is None:
            return
        if self.guides_showing:
            image = framing.guided(image, self.current_framing())
        self.preview_view.image = toga.Image(image)

    # --- turning a photo ------------------------------------------------------

    def rotate(self, degrees: int) -> None:
        if self.busy or self.preview_index not in self.proxies:
            return
        self.place(
            g.turned_further(
                self.sizes[self.preview_index],
                framing.output_box(self.current_framing()),
                self.placement(), degrees,
            )
        )
        self.show_guides()
        self.update_preview()

    def recentre(self, widget=None) -> None:
        """Put the photo back as it was opened: level and centred."""
        if self.busy or not self.picked:
            return
        self.placements.pop(self.preview_index, None)
        self.clear_guides()
        self.update_preview()

    def show_guides(self) -> None:
        """Dashed lines to level against, until the buttons have been left
        alone for a few seconds."""
        self.guides_showing = True
        if self.guide_timer is not None:
            self.guide_timer.cancel()
        self.guide_timer = self.loop.call_later(self.guide_seconds, self.hide_guides)

    def clear_guides(self) -> None:
        self.guides_showing = False
        if self.guide_timer is not None:
            self.guide_timer.cancel()
            self.guide_timer = None

    def hide_guides(self) -> None:
        showing = self.guides_showing
        self.clear_guides()
        if showing:
            self.guard("hiding the guide lines", self.draw_preview)

    # --- dragging and pinching --------------------------------------------------

    def listen_for_fingers(self) -> None:
        # Kept on the app so it is not swept away while Android still holds it.
        self.finger_listener = touch.Listener(
            self.on_fingers, lambda: self.log.exception("following a finger")
        )
        self.preview_view._impl.native.setOnTouchListener(self.finger_listener)
        self.live = touch.Canvas()

    def on_fingers(self, kind: str, points) -> None:
        if self.busy or self.preview_index not in self.proxies:
            return
        if kind == touch.CHANGED:
            self.tracker.changed(points)
        elif kind == touch.MOVED:
            step = self.tracker.moved(points)
            if step is not None:
                self.drag(step)
        else:
            self.tracker.ended()
            if self.dragging:
                # The fingers have gone: draw it properly.
                self.dragging = False
                self.update_preview()

    def drag(self, step: gestures.Step) -> None:
        """Move the photo with the fingers."""
        centre_x, centre_y, shown_width = touch.shown_at(
            self.preview_view._impl.native
        )
        # Screen pixels to pixels of the finished picture, from its centre.
        scale = framing.OUTPUT_WIDTH / shown_width

        def on_output(point):
            return (point[0] - centre_x) * scale, (point[1] - centre_y) * scale

        self.place(
            g.moved(
                self.sizes[self.preview_index],
                framing.output_box(self.current_framing()),
                self.placement(),
                before=on_output(step.before),
                after=on_output(step.after),
                spread=step.spread,
            )
        )
        self.dragging = True
        # Fingers report faster than a picture can be drawn. Draw once for
        # however many reports arrive in the meantime.
        if not self.redraw_pending:
            self.redraw_pending = True
            self.loop.call_soon(self.redraw_quickly)

    def redraw_quickly(self) -> None:
        self.redraw_pending = False
        index = self.preview_index
        if not self.dragging or index not in self.proxies:
            return
        try:
            started = time.perf_counter()
            if index not in self.quick_proxies:
                self.quick_proxies[index] = framing.quick_proxy(self.proxies[index])
            chosen = self.current_framing()
            image = framing.quick_preview(
                self.quick_proxies[index], chosen, self.placement()
            )
            if self.guides_showing:
                image = framing.guided(image, chosen)
            self.live.show(self.preview_view._impl.native, image)
            self.quick_frames += 1
            self.quick_seconds += time.perf_counter() - started
        except Exception:
            self.log.exception("redrawing under a finger")

    async def next_photo(self, widget=None) -> None:
        await self.exclusively("showing the next photo", self._next_photo())

    async def _next_photo(self) -> None:
        self.preview_index = (self.preview_index + 1) % len(self.picked)
        await self.show_photo()

    def forget_photos(self) -> None:
        self.clear_guides()
        self.tracker.ended()
        self.dragging = False
        self.picked, self.proxies, self.placements = [], {}, {}
        self.sizes, self.quick_proxies = {}, {}
        self.preview_plain = None

    async def leave_framing(self, widget=None) -> None:
        self.forget_photos()
        self.main_window.content = self.main_box
        self.refresh_controls()

    async def save_framed(self, widget=None) -> None:
        await self.exclusively("saving the framed photos", self._save_framed())

    async def _save_framed(self) -> None:
        to_gallery = bool(self.gallery_switch.value)
        if self.tree is None and not to_gallery:
            self.log.write(
                "Nowhere to save: no folder is chosen and the gallery is off."
            )
            return
        here = self.here if self.tree is not None else None
        await self.work(
            self.save_framed_now, list(self.picked), self.current_framing(),
            dict(self.placements), to_gallery, self.tree, here,
        )
        self.forget_photos()
        self.main_window.content = self.main_box
        if self.tree is not None:
            await self.refresh_listing()

    def save_framed_now(
        self, picked, chosen: Framing, placements, to_gallery, tree, here
    ) -> None:
        """One photo at a time, start to finish, so memory stays flat."""
        log = self.log
        log.section("Saving framed photos")
        log.write(
            f"Framing: {chosen.ratio}, {chosen.mode}, {chosen.border_pct:g}% border. "
            f"To the folder: {'yes' if tree is not None else 'no'}. "
            f"To the gallery: {'yes' if to_gallery else 'no'}."
        )
        taken = set()
        if tree is not None:
            taken = {entry.name for entry in storage.children(tree, here)}

        for number, (address, name) in enumerate(picked, start=1):
            try:
                started = time.perf_counter()
                image = framing.prepare(
                    storage.read_uri(address), androidimage.decode_to_srgb
                )
                opened = time.perf_counter()
                placement = placements.get(number - 1, g.Placement())
                result = framing.frame(image, chosen, placement)
                framed = time.perf_counter()

                out = framing.output_name(name, taken)
                taken.add(out)
                if tree is not None:
                    entry = storage.create_file(tree, here, out, "image/jpeg")
                    storage.write_bytes(tree, entry.doc_id, result.jpeg)
                if to_gallery:
                    storage.save_to_gallery(out, result.jpeg)

                w, h = result.source_size
                note = ""
                if placement.angle:
                    note += f" Turned {placement.angle} degrees."
                if placement.zoom != 1.0 or placement.offset_x or placement.offset_y:
                    note += " Moved or zoomed by hand."
                if placement.positioned and chosen.mode == "fit":
                    note += " Positioned by hand, so it fills the frame."
                if result.upscaled:
                    note += " Enlarged: the photo is smaller than the frame."
                log.write(
                    f"PASS  Photo {number} of {len(picked)}: {w} x {h} -> "
                    f"{result.canvas[0]} x {result.canvas[1]}, {result.border} px "
                    f"border, {len(result.jpeg) / 1024:.0f} KB. Opened in "
                    f"{opened - started:.2f} s, framed in {framed - opened:.2f} s, "
                    f"saved in {time.perf_counter() - framed:.2f} s.{note}"
                )
            except Exception:
                log.exception(f"framing photo {number} of {len(picked)}")
        log.write("Framed photos finished.")

    # --- image tests ----------------------------------------------------------

    async def run_image_tests(self, widget=None) -> None:
        await self.exclusively("running the image tests", self._run_image_tests())

    async def _run_image_tests(self) -> None:
        ok = await self.work(imagetests.run_all, self.log, androidimage.decode_to_srgb)
        self.log.write("")
        self.log.write(
            "Image tests finished: " + ("all passed." if ok else "something FAILED.")
        )

    # --- automated run, for the build's own check -----------------------------

    def self_test_requested(self) -> bool:
        try:
            from org.beeware.android import MainActivity

            intent = MainActivity.singletonThis.getIntent()
            return bool(intent.getBooleanExtra("selftest", False))
        except Exception:
            return False

    async def self_test(self) -> None:
        """Exercise every button against the phone's own storage.

        Run by the build in an emulator, where nothing can be pressed by hand.
        It stands in for Proton Drive with local storage, which proves this
        app's side of the conversation; only a real phone can prove Proton's.
        """
        log = self.log
        log.section("Automated self-test")
        try:
            await self.run_image_tests()
            await self.choose_folder(initial=storage.local_folder_uri(SELF_TEST_FOLDER))
            if self.tree is None:
                log.write("FAIL  No folder was granted, so nothing else can be tested.")
                return

            for name in ("CI test & trial", "CI test & trial"):
                self.name_input.value = name
                await self.create_folder()
            self.folder_select.value = "CI test & trial"
            await self.open_selected()
            self.name_input.value = "Edits"
            await self.create_folder()
            await self.open_selected()
            await self.write_test_files()
            await self.hold_for_screenshot("main-screen")
            await self.self_test_framing()
            await self.go_up()

            held = storage.persisted_folder() is not None
            log.write(
                f"{'PASS' if held else 'FAIL'}  Folder access is recorded as "
                "lasting beyond this session."
            )
        except Exception:
            log.exception("running the self-test")
        finally:
            log.write("=== Self-test finished ===")


    async def hold_for_screenshot(self, name: str) -> None:
        """Stand still while the build's emulator run photographs the screen.

        Nothing else can show whether the app looks right -- dark, with
        unavailable buttons visibly greyed -- before a build is published.
        """
        self.log.write(f"SCREENSHOT {name}")
        await asyncio.sleep(10)

    async def self_test_framing(self) -> None:
        """Frame a photo as a person would, plus a check they could not see."""
        log = self.log
        log.section("Self-test: rotation and colour together")
        # A Display P3 image stored on its side, as a camera held upright
        # would store it. Android has to convert the colour, and this app has
        # to turn it the right way up.
        fixture = FIXTURES[0]
        source = Image.open(io.BytesIO(fixture["jpeg"]))
        exif = Image.Exif()
        exif[274] = 6
        stored = io.BytesIO()
        source.transpose(Image.Transpose.ROTATE_90).save(
            stored, "JPEG", quality=100, subsampling=0, exif=exif,
            icc_profile=source.info["icc_profile"],
        )
        image = await self.work(
            framing.prepare, stored.getvalue(), androidimage.decode_to_srgb
        )
        turned = image.size == source.size
        worst = 0
        if turned:
            for centre, _, expected in fixture["patches"]:
                got = image.getpixel(centre)
                worst = max(worst, max(abs(a - b) for a, b in zip(got, expected)))
        ok = turned and worst <= imagetests.COLOUR_TOLERANCE
        log.write(
            f"{'PASS' if ok else 'FAIL'}  A sideways Display P3 photo came out "
            f"{image.size[0]} x {image.size[1]}, colours within {worst} of the desktop"
        )

        log.section("Self-test: framing a photo from the folder")
        before = {
            e.name for e in await self.work(storage.children, self.tree, self.here)
        }
        await self.frame_photos(
            initial=storage.folder_address(self.tree, self.here)
        )
        if not self.picked:
            log.write("FAIL  No photo came back from the picker.")
            return
        shown = self.main_window.content is self.framing_box
        log.write(
            f"{'PASS' if shown else 'FAIL'}  The framing screen opened with a preview."
        )
        # Asked of Android itself, not of this app's own record of it.
        next_off = not bool(self.next_btn._impl.native.isEnabled())
        log.write(
            f"{'PASS' if next_off else 'FAIL'}  With one photo chosen, "
            "Next photo is switched off."
        )
        await self.hold_for_screenshot("framing-one-photo")
        await self.self_test_rotation()
        await self.self_test_fingers()

        self.ratio_select.value = next(
            label for label, key in self.ratio_choices.items() if key == "1:1"
        )
        self.fit_select.value = next(
            label for label, mode in FIT_CHOICES.items() if mode == "crop"
        )
        self.border_slider.value = 6
        self.rotate(90)
        self.rotate(1)
        self.rotate(1)
        self.clear_guides()
        await self.save_framed()

        after = await self.work(storage.children, self.tree, self.here)
        new = [e for e in after if e.name not in before]
        if len(new) != 1:
            log.write(f"FAIL  Expected one new file in the folder, found {len(new)}.")
            return
        data = await self.work(storage.read_bytes, self.tree, new[0].doc_id)
        with Image.open(io.BytesIO(data)) as saved:
            square = saved.size == (1080, 1080)
            log.write(
                f"{'PASS' if square else 'FAIL'}  Saved {new[0].name!r} as "
                f"{saved.size[0]} x {saved.size[1]}, following the settings chosen."
            )


    async def self_test_rotation(self) -> None:
        """Press the rotation buttons and see that the screen follows."""
        log = self.log
        log.section("Self-test: turning a photo")

        def verdict(ok: bool, text: str) -> None:
            log.write(f"{'PASS' if ok else 'FAIL'}  {text}")

        # Asked of Android: the row must fit across the screen it is on.
        last = self.turn_btns[-1]._impl.native
        across = last.getParent().getWidth()
        verdict(
            0 < last.getRight() <= across,
            f"The five rotation buttons fit: the last ends at {last.getRight()} "
            f"of {across} pixels.",
        )

        # Long enough for the screen to be photographed with the lines on it.
        self.guide_seconds = 14
        started = time.perf_counter()
        for _ in range(3):
            self.rotate(1)
        each = (time.perf_counter() - started) / 3
        shown = self.angle_btn.text
        verdict(
            shown == framing.angle_label(3) and self.guides_showing,
            f"Three presses of +1: the angle reads {shown}, the guide lines are "
            f"{'showing' if self.guides_showing else 'NOT showing'}, and each "
            f"press redrew the preview in {each:.2f} s.",
        )
        verdict(
            "fills the frame" in self.batch_label.text,
            "A tilted photo in fit mode is described as filling the frame.",
        )
        await self.hold_for_screenshot("framing-tilted")

        self.guide_seconds = GUIDE_SECONDS
        self.rotate(-90)
        appeared = self.guides_showing
        await asyncio.sleep(GUIDE_SECONDS - 1)
        stayed = self.guides_showing
        await asyncio.sleep(2)
        verdict(
            appeared and stayed and not self.guides_showing
            and self.angle_btn.text == framing.angle_label(-87),
            f"A press of -90: the angle reads {self.angle_btn.text}; the guide "
            f"lines appeared, were still there after {GUIDE_SECONDS - 1} s, and "
            f"had gone after {GUIDE_SECONDS + 1} s.",
        )

        self.recentre()
        verdict(
            self.angle_btn.text == framing.angle_label(0)
            and not self.placements and not self.guides_showing,
            f"A press of the angle put the photo back: it reads {self.angle_btn.text}.",
        )
        await self.hold_for_screenshot("framing-recentred")


    async def self_test_fingers(self) -> None:
        """Drag and pinch the photo with touches made the way Android makes
        them, and see that it follows."""
        log = self.log
        log.section("Self-test: dragging and pinching")
        from android.view import MotionEvent

        def verdict(ok: bool, text: str) -> None:
            log.write(f"{'PASS' if ok else 'FAIL'}  {text}")

        # A square frame on a tall photo: room to slide up and down.
        self.ratio_select.value = next(
            label for label, key in self.ratio_choices.items() if key == "1:1"
        )
        self.fit_select.value = next(
            label for label, mode in FIT_CHOICES.items() if mode == "crop"
        )
        await asyncio.sleep(1)

        view = self.preview_view._impl.native
        size = self.sizes[self.preview_index]
        box = framing.output_box(self.current_framing())
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
        self.quick_frames, self.quick_seconds = 0, 0.0
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
        got = self.placement()
        verdict(
            got.offset_y < 0 and abs(got.offset_y - expected.offset_y) < 0.01
            and got.offset_x == 0 and not self.dragging,
            f"One finger pulled down {pull} pixels slid the photo down by "
            f"{-got.offset_y:.3f} of the room it has; exact would be "
            f"{-expected.offset_y:.3f}.",
        )
        frames = self.quick_frames
        each = self.quick_seconds / frames * 1000 if frames else 0.0
        verdict(
            frames > 0,
            f"The photo was redrawn {frames} time(s) while the finger moved, "
            f"in {each:.0f} ms each.",
        )
        await self.hold_for_screenshot("framing-dragged")

        # Two fingers, spread far apart: zoom, up to the limit and no further.
        limit = g.max_zoom(size, box, self.placement())
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
        zoomed = self.placement().zoom
        verdict(
            limit > 1 and abs(zoomed - limit) < 1e-6,
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
            self.placement().zoom == 1.0,
            f"Pinched back together, the zoom returned to "
            f"{self.placement().zoom:.3f}: the photo still fills the frame.",
        )

        # A touch that goes nowhere.
        before = self.placement()
        await touches(
            (MotionEvent.ACTION_DOWN, [(centre_x + 20, centre_y - 20)]),
            (MotionEvent.ACTION_UP, [(centre_x + 20, centre_y - 20)]),
        )
        verdict(self.placement() == before, "A tap moved nothing.")

        self.recentre()
        verdict(
            not self.placements,
            "A press of the angle put the photo back in the middle.",
        )


def main() -> IGprepperTest:
    return IGprepperTest()
