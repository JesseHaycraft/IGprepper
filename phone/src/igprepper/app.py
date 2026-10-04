"""IGprepper for Android.

Two screens. The first is where framed photos will be saved: a folder,
browsed the way a file manager browses one, and optionally the phone's
gallery. The second is the editor: the chosen photos one at a time, each
positioned by hand inside a frame whose shape and border the batch shares.

The app works inside whichever folder is chosen in Android's folder picker,
so it is tied to no particular storage. It never invents a folder name:
folders are created only when a name is typed, exactly as typed.

A log of what the app did is kept in Download/IGprepper for when something
goes wrong. It records the names of folders the app was asked to create, and
nothing about what was already in the storage: existing folders and the
photos chosen appear on screen but are never written down.
"""

from __future__ import annotations

import asyncio
import platform
import sys
import time
from dataclasses import dataclass

import toga
from PIL import Image
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW

from igprep.core import geometry as g
from igprep.core.preview import make_proxy
from igprep.core.settings import Framing

from . import (
    androidimage,
    androidui,
    framing,
    gestures,
    icons,
    storage,
    touch,
    words,
)
from .phonelog import PhoneLog

ACCENT = "#8AB4F8"
DIM = "#9AA0A6"
# Android draws a switched-off button almost exactly like a working one, so
# each kind of button, and "off", is given colours of its own.
BUTTON_LOOKS = {
    "primary": {"color": "#0B1B33", "background_color": ACCENT},
    "plain": {"color": "#FFFFFF", "background_color": "#3C4043"},
    "row": {"color": "#E8EAED", "background_color": "#2A2B2E"},
    "off": {"color": "#6F7378", "background_color": "#232427"},
}
ICON_DP = 20

FIT_CHOICES = {
    "Fit – show the whole photo": "fit",
    "Fill – crop to the frame": "crop",
}
# How long the guide lines stay after the last press of a rotation button.
GUIDE_SECONDS = 3
KEPT_LOGS = 10


@dataclass
class Look:
    """What a button says and how it is drawn."""

    kind: str
    text: str
    icon: str | None
    shown: tuple | None = None


class IGprepper(toga.App):
    def startup(self) -> None:
        self.log = PhoneLog()
        self.log.install_excepthook()

        self.tree = None
        # The path from the chosen folder down to where we are: (id, name).
        self.trail: list[tuple[str, str]] = []
        # Folders this app created, whose names may therefore be logged.
        self.created: set[str] = set()
        self.subfolders: list[storage.Entry] = []
        self.folder_rows: list[toga.Button] = []
        self.busy = False
        # Set by the build's own check, which has nobody to answer a pop-up.
        self.unattended = False
        self.said = ""

        # The photos chosen for framing: (address, filename). Only a small
        # proxy of each is kept, and only once it has been looked at; holding
        # every photo at full size would exhaust the phone's memory.
        self.picked: list[tuple[object, str]] = []
        self.proxies: dict[int, Image.Image] = {}
        self.sizes: dict[int, tuple[int, int]] = {}
        self.quick_proxies: dict[int, Image.Image] = {}
        self.preview_index = 0
        # How each photo has been positioned by hand. Shape, fit and border
        # are shared by the batch; this belongs to one photo.
        self.placements: dict[int, g.Placement] = {}
        self.preview_plain: Image.Image | None = None
        self.tracker = gestures.Tracker()
        self.dragging = False
        self.redraw_pending = False
        self.quick_frames, self.quick_seconds = 0, 0.0
        self.guides_showing = False
        self.guide_timer = None
        self.guide_seconds = GUIDE_SECONDS

        self.looks: dict[toga.Button, Look] = {}
        self.drawn_icons: dict[tuple[str, str], object] = {}
        self.name_dialog = None
        self.back = androidui.BackButton(self.on_back)

        self.build_home()
        self.build_editor()
        self.main_window = toga.MainWindow(title=self.formal_name)
        self.main_window.content = self.home_box
        self.main_window.show()

        self.guard("describing the phone", self.report_environment)
        self.guard("darkening the system bars", self.darken_system_bars)
        self.show_location()
        self.refresh_controls()

    # --- the two screens ------------------------------------------------------

    def build_home(self) -> None:
        """Where framed photos go, and the way in to choosing some."""
        caption = toga.Label(
            "Save framed photos to", style=Pack(color=DIM, font_size=9)
        )
        self.folder_label = toga.Label(
            "", style=Pack(font_size=15, font_weight="bold", margin_top=2)
        )
        self.trail_label = toga.Label(
            "", style=Pack(color=DIM, font_size=9, margin_top=2)
        )

        self.up_btn = self.button("Up", self.go_up, icon="up", flex=1)
        self.new_btn = self.button(
            "New folder", self.new_folder, icon="new_folder", flex=1, margin_left=6
        )
        self.choose_btn = self.button(
            "Change", self.choose_folder, icon="folder", flex=1, margin_left=6
        )
        tools = toga.Box(
            children=[self.up_btn, self.new_btn, self.choose_btn],
            style=Pack(direction=ROW, margin_top=10),
        )

        self.folder_list = toga.Box(style=Pack(direction=COLUMN))
        self.folder_scroll = toga.ScrollContainer(
            content=self.folder_list, horizontal=False,
            style=Pack(flex=1, margin_top=10),
        )

        self.gallery_switch = toga.Switch(
            "Also save to this phone’s gallery", value=True,
            style=Pack(margin_top=10),
        )
        self.select_btn = self.button(
            "Select photos", self.select_photos, icon="photo", kind="primary",
            margin_top=10, height=56,
        )

        self.home_box = toga.Box(
            children=[
                caption, self.folder_label, self.trail_label, tools,
                self.folder_scroll, self.gallery_switch, self.select_btn,
            ],
            style=Pack(direction=COLUMN, margin=12),
        )

    def build_editor(self) -> None:
        """The photo on top, everything that changes it beneath."""
        self.previous_btn = self.button(
            "", self.previous_photo, icon="previous", width=56
        )
        self.count_label = toga.Label(
            "", style=Pack(flex=1, text_align=CENTER, font_size=12)
        )
        self.next_btn = self.button("", self.next_photo, icon="next", width=56)
        stepping = toga.Box(
            children=[self.previous_btn, self.count_label, self.next_btn],
            style=Pack(direction=ROW, align_items=CENTER),
        )

        self.preview_view = toga.ImageView(style=Pack(flex=1, margin_top=6))
        self.guard("listening for fingers on the photo", self.listen_for_fingers)
        self.hint_label = toga.Label(
            "", style=Pack(color=DIM, font_size=9, text_align=CENTER, margin_top=4)
        )

        def turner(degrees: int):
            return lambda widget: self.rotate(degrees)

        # Quarter turns either end, single degrees inside them, and in the
        # middle the angle itself, which puts the photo back when pressed.
        self.angle_btn = self.button(framing.angle_label(0), self.recentre, flex=1)
        self.turn_btns = [
            self.button("90°", turner(-90), icon="rotate_left", flex=1),
            self.button("−1°", turner(-1), flex=1),
            self.angle_btn,
            self.button("+1°", turner(1), flex=1),
            self.button("90°", turner(90), icon="rotate_right", flex=1),
        ]
        for spare in self.turn_btns[1:]:
            spare.style.update(margin_left=6)
        turning = toga.Box(
            children=self.turn_btns, style=Pack(direction=ROW, margin_top=6)
        )

        def captioned(caption: str, *widgets) -> toga.Box:
            label = toga.Label(caption, style=Pack(width=64, color=DIM))
            return toga.Box(
                children=[label, *widgets],
                style=Pack(direction=ROW, align_items=CENTER, margin_top=6),
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
        self.border_value = toga.Label("", style=Pack(width=44))
        self.border_slider = toga.Slider(
            min=0, max=15, value=g.DEFAULT_BORDER_PCT, tick_count=31,
            on_change=self.update_preview, style=Pack(flex=1),
        )

        self.cancel_btn = self.button(
            "Cancel", self.cancel_editing, icon="close", flex=1, height=52
        )
        self.save_btn = self.button(
            "Save", self.save_framed, icon="check", kind="primary",
            flex=2, height=52, margin_left=6,
        )
        actions = toga.Box(
            children=[self.cancel_btn, self.save_btn],
            style=Pack(direction=ROW, margin_top=10),
        )

        self.editor_box = toga.Box(
            children=[
                stepping, self.preview_view, self.hint_label, turning,
                captioned("Shape", self.ratio_select),
                captioned("Photo", self.fit_select),
                captioned("Border", self.border_value, self.border_slider),
                actions,
            ],
            style=Pack(direction=COLUMN, margin=12),
        )

    def show_home(self) -> None:
        self.forget_photos()
        self.main_window.content = self.home_box
        self.guard("handing Back to the phone", lambda: self.back.listen(False))
        self.refresh_controls()

    def show_editor(self) -> None:
        self.main_window.content = self.editor_box
        # From here Back means "leave the editor", not "close the app".
        self.guard("taking over Back", lambda: self.back.listen(True))
        self.refresh_controls()

    async def on_running(self) -> None:
        """Once the screen is up: pick up last session's folder, if any."""
        await self.restore_folder()
        self.guard("clearing out old logs", lambda: self.log.prune(KEPT_LOGS))
        self.log.write("")
        self.log.write("=== Ready ===")
        if self.self_test_requested():
            from . import selftest

            await selftest.run(self)

    # --- plumbing ---------------------------------------------------------

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

        window = androidui.activity().getWindow()
        window.setStatusBarColor(Color.BLACK)
        window.setNavigationBarColor(Color.BLACK)

    async def exclusively(self, doing: str, coroutine) -> None:
        """Run one action at a time, and never let it fail silently."""
        if self.busy:
            coroutine.close()
            return
        self.busy = True
        self.refresh_controls()
        failed = False
        try:
            await coroutine
        except Exception:
            self.log.exception(doing)
            failed = True
        finally:
            self.busy = False
            self.refresh_controls()
        if failed:
            await self.tell(
                "Something went wrong",
                f"That did not work ({doing}). The details are in the log in "
                "Download/IGprepper.",
            )

    @property
    def here(self) -> str:
        return self.trail[-1][0]

    def self_test_requested(self) -> bool:
        try:
            intent = androidui.activity().getIntent()
            return bool(intent.getBooleanExtra("selftest", False))
        except Exception:
            return False

    def report_environment(self) -> None:
        log = self.log
        log.section(f"IGprepper phone app, version {self.version}")
        log.write(f"Log file: {log.location}")

        from android.os import Build

        log.write(f"Android {Build.VERSION.RELEASE} (API {Build.VERSION.SDK_INT})")
        log.write(f"Model: {Build.MANUFACTURER} {Build.MODEL}")
        log.write(f"Python {sys.version.split()[0]} on {platform.machine()}")
        log.write(
            "The Back gesture inside the editor: "
            + ("handled by the app" if self.back.available else "left to Android")
        )

    # --- saying things ----------------------------------------------------------

    def announce(self, text: str, logged: str | None = None) -> None:
        """A brief message that needs no answer.

        `logged` is what the log records instead, for a message that names
        something already in the storage.
        """
        self.said = text
        self.log.write(f"Shown briefly: {logged or text}")
        self.guard("showing a brief message", lambda: androidui.toast(text))

    async def tell(self, title: str, message: str, logged: str | None = None) -> None:
        """A message that has to be acknowledged."""
        self.said = f"{title}: {message}"
        self.log.write(f"Shown: {title}: {logged or message}")
        if not self.unattended:
            await self.main_window.dialog(toga.InfoDialog(title, message))

    async def ask(self, title: str, message: str) -> bool:
        if self.unattended:
            return True
        return bool(
            await self.main_window.dialog(toga.QuestionDialog(title, message))
        )

    # --- buttons ----------------------------------------------------------------

    def button(
        self, text: str, on_press, *, icon: str | None = None,
        kind: str = "plain", **style,
    ) -> toga.Button:
        """A button with an icon before its label, in one of the app's looks."""
        made = toga.Button(text, on_press=on_press, style=Pack(**style))
        self.looks[made] = Look(kind, text, icon)
        self.guard(
            "shaping a button", lambda: androidui.plain_button(made._impl.native)
        )
        self.dress(made, True)
        return made

    def drawn_icon(self, name: str, colour: str):
        # Not called `icon`: the toolkit keeps the app's own icon under that
        # name, and would quietly replace this.
        key = (name, colour)
        if key not in self.drawn_icons:
            self.drawn_icons[key] = androidui.drawable(
                icons.icon(name, 96, colour), ICON_DP
            )
        return self.drawn_icons[key]

    def dress(self, button: toga.Button, on: bool) -> None:
        look = self.looks[button]
        state = (on, look.text)
        if look.shown == state:
            return
        look.shown = state
        colours = BUTTON_LOOKS[look.kind if on else "off"]
        button.style.update(**colours)

        def label() -> None:
            icon = (
                self.drawn_icon(look.icon, colours["color"]) if look.icon else None
            )
            androidui.label(button._impl.native, look.text, icon)

        self.guard("labelling a button", label)
        button.refresh()

    def relabel(self, button: toga.Button, text: str) -> None:
        self.looks[button].text = text
        self.dress(button, bool(button.enabled))

    def switch(self, button: toga.Button, on: bool) -> None:
        """Enable or disable a button, and make the difference visible."""
        button.enabled = on
        self.dress(button, on)

    def refresh_controls(self) -> None:
        free = not self.busy
        have_folder = self.tree is not None
        editing = bool(self.picked)
        several = len(self.picked) > 1

        self.switch(self.choose_btn, free)
        self.switch(self.up_btn, free and len(self.trail) > 1)
        self.switch(self.new_btn, free and have_folder)
        self.switch(self.select_btn, free)
        for row in self.folder_rows:
            self.switch(row, free)

        self.switch(self.previous_btn, free and several)
        self.switch(self.next_btn, free and several)
        for turn in self.turn_btns:
            self.switch(turn, free and editing)
        self.switch(self.cancel_btn, free)
        self.switch(self.save_btn, free and editing)

    # --- where photos are saved ---------------------------------------------------

    def show_location(self) -> None:
        """The folder's name, the way to it, and the folders inside it."""
        if self.tree is None:
            self.folder_label.text = "Gallery only"
            self.trail_label.text = "No folder chosen"
        else:
            names = [name for _, name in self.trail]
            self.folder_label.text = words.shorten(names[-1], 26)
            self.trail_label.text = (
                "In " + words.trail(names[:-1], 44) if names[:-1] else "Chosen folder"
            )
        self.relabel(
            self.choose_btn, "Change" if self.tree is not None else "Choose folder"
        )

        for row in self.folder_rows:
            self.looks.pop(row, None)
        self.folder_rows = []
        self.folder_list.clear()

        def note(text: str) -> None:
            self.folder_list.add(
                toga.Label(text, style=Pack(color=DIM, margin_top=4))
            )

        if self.tree is None:
            note("Framed photos will go to the gallery only.")
            note("Choose a folder to save them there as well.")
        elif not self.subfolders:
            note("No folders in here.")
        for entry in self.subfolders:
            row = self.button(
                words.shorten(entry.name, 32), self.opener(entry),
                icon="folder", kind="row", margin_bottom=4,
            )
            self.guard(
                "lining up a folder", lambda r=row: androidui.align_start(r._impl.native)
            )
            self.folder_rows.append(row)
            self.folder_list.add(row)

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
        await self.refresh_listing()

    async def refresh_listing(self) -> None:
        entries = await self.work(storage.children, self.tree, self.here)
        self.subfolders = sorted(
            (e for e in entries if e.is_dir), key=lambda e: e.name.lower()
        )
        files = sum(1 for e in entries if not e.is_dir)
        self.log.write(
            f"This folder holds {len(self.subfolders)} folder(s) and {files} "
            "file(s). Names are not logged."
        )
        self.show_location()
        self.refresh_controls()

    def opener(self, entry: storage.Entry):
        async def open_it(widget=None) -> None:
            await self.open_folder(entry)

        return open_it

    async def open_folder(self, entry: storage.Entry) -> None:
        await self.exclusively("opening a folder", self._open_folder(entry))

    async def _open_folder(self, entry: storage.Entry) -> None:
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
            return
        self.trail.pop()
        self.log.write(f"Went up, now {len(self.trail) - 1} level(s) down.")
        await self.refresh_listing()

    async def new_folder(self, widget=None) -> None:
        """Ask for a name, as a file manager does."""
        if self.busy or self.tree is None:
            return
        self.name_dialog = androidui.ask_for_text(
            "New folder", "Folder name", "Create", self.name_given
        )

    def name_given(self, name: str) -> None:
        # Called by Android when Create is pressed; the work is done in turn.
        asyncio.ensure_future(self.create_folder(name))

    async def create_folder(self, name: str) -> None:
        await self.exclusively("creating a folder", self._create_folder(name))

    async def _create_folder(self, name: str) -> None:
        name = name.strip()
        if not name:
            self.announce("No name was typed, so no folder was created")
            return
        self.log.section("Creating a folder")
        # Some storage will happily hold two folders of one name. Nobody
        # wants that, so it is settled here.
        if any(e.name.lower() == name.lower() for e in self.subfolders):
            self.log.write("A folder of that name is already here; none created.")
            await self.tell(
                "Already there",
                "This folder already has one called "
                f"“{words.shorten(name, 40)}”.",
                logged="a folder of that name is already here.",
            )
            return
        entry = await self.work(storage.create_folder, self.tree, self.here, name)
        self.created.add(entry.doc_id)
        if entry.name == name:
            self.log.write(f"PASS  Created {entry.name!r}, exactly as typed.")
        else:
            self.log.write(
                f"INFO  Asked for {name!r}; the storage app created {entry.name!r}."
            )
        await self.refresh_listing()
        self.announce(f"Created “{words.shorten(entry.name, 30)}”")

    # --- choosing photos ------------------------------------------------------------

    def current_framing(self) -> Framing:
        return Framing(
            ratio=self.ratio_choices.get(self.ratio_select.value, g.DEFAULT_RATIO),
            mode=FIT_CHOICES.get(self.fit_select.value, "fit"),
            border_pct=round(float(self.border_slider.value) * 2) / 2,
        )

    async def select_photos(self, widget=None, initial=None) -> None:
        await self.exclusively("choosing photos", self._select_photos(initial))

    async def _select_photos(self, initial) -> None:
        self.log.section("Framing photos")
        addresses = await storage.pick_photos(self, initial)
        if not addresses:
            self.log.write("No photos were chosen.")
            return
        self.forget_photos()
        for address in addresses:
            name = await self.work(storage.display_name, address)
            self.picked.append((address, name))
        self.log.write(f"{len(self.picked)} photo(s) chosen. Names are not logged.")
        await self.show_photo()
        self.show_editor()

    def forget_photos(self) -> None:
        self.clear_guides()
        self.tracker.ended()
        self.dragging = False
        self.picked, self.proxies, self.placements = [], {}, {}
        self.sizes, self.quick_proxies = {}, {}
        self.preview_plain = None
        self.preview_index = 0

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

    async def next_photo(self, widget=None) -> None:
        await self.exclusively("showing the next photo", self._step(1))

    async def previous_photo(self, widget=None) -> None:
        await self.exclusively("showing the previous photo", self._step(-1))

    async def _step(self, by: int) -> None:
        self.preview_index = (self.preview_index + by) % len(self.picked)
        await self.show_photo()

    # --- the preview ------------------------------------------------------------------

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
            # A change of shape or border moves the zoom limit.
            self.place(
                g.within_limits(
                    self.sizes[self.preview_index], framing.output_box(chosen),
                    self.placement(),
                )
            )
            self.describe(chosen)
            self.preview_plain = framing.preview(proxy, chosen, self.placement())
            self.draw_preview()
        except Exception:
            self.log.exception("drawing the preview")

    def describe(self, chosen: Framing) -> None:
        """Everything on the editor that is words rather than picture."""
        placement = self.placement()
        count = len(self.picked)
        angle = framing.angle_label(placement.angle)
        self.count_label.text = f"Photo {self.preview_index + 1} of {count}"
        self.border_value.text = f"{chosen.border_pct:g}%"
        self.relabel(self.angle_btn, angle)
        self.hint_label.text = words.hint(
            changed=placement != g.Placement(),
            forced_to_fill=placement.positioned and chosen.mode == "fit",
            angle=angle,
        )
        self.relabel(
            self.save_btn, "Save" if count == 1 else f"Save all {count} photos"
        )

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
        """Put the photo back as it was opened: level, centred, not zoomed."""
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

    # --- leaving the editor ---------------------------------------------------------

    def on_back(self) -> None:
        # Called by Android for the Back gesture while the editor is open.
        asyncio.ensure_future(self.cancel_editing())

    async def cancel_editing(self, widget=None) -> None:
        if self.busy:
            return
        if self.placements and not await self.ask(
            "Discard changes?",
            "The photos you have moved or turned will be put back as they were.",
        ):
            return
        self.log.write("Left the editor without saving.")
        self.show_home()

    async def save_framed(self, widget=None) -> None:
        await self.exclusively("saving the framed photos", self._save_framed())

    async def _save_framed(self) -> None:
        to_gallery = bool(self.gallery_switch.value)
        if self.tree is None and not to_gallery:
            await self.tell(
                "Nowhere to save",
                "No folder is chosen and saving to the gallery is switched off. "
                "Go back and choose a folder, or switch the gallery on.",
            )
            return
        here = self.here if self.tree is not None else None
        folder = self.trail[-1][1] if self.tree is not None else None
        total = len(self.picked)
        saved = await self.work(
            self.save_framed_now, list(self.picked), self.current_framing(),
            dict(self.placements), to_gallery, self.tree, here,
        )
        self.show_home()
        if self.tree is not None:
            await self.refresh_listing()
        if saved == total:
            self.announce(
                words.saved(saved, folder, to_gallery),
                logged=f"saved {words.photos(saved)}.",
            )
        else:
            await self.tell(
                "Not everything was saved",
                f"{saved} of {words.photos(total)} saved. The details are in "
                "the log in Download/IGprepper.",
            )

    def show_progress(self, number: int, total: int) -> None:
        self.count_label.text = f"Saving {number} of {total}…"

    def save_framed_now(
        self, picked, chosen: Framing, placements, to_gallery, tree, here
    ) -> int:
        """One photo at a time, start to finish, so memory stays flat.

        Returns how many were saved.
        """
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

        saved = 0
        for number, (address, name) in enumerate(picked, start=1):
            self.loop.call_soon_threadsafe(self.show_progress, number, len(picked))
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
                saved += 1

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
        return saved


def main() -> IGprepper:
    return IGprepper()
