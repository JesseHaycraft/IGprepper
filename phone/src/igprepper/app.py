"""IGprepper for Android.

Two screens. The first is a pair of folder browsers, one above the other:
the input folder, where photos are checked for processing, and the output
folder, where the framed photos will go. The second is the editor: the
checked photos one at a time, each positioned by hand inside a frame whose
shape and border the batch shares.

The app works inside whichever folders are chosen in Android's folder
picker, so it is tied to no particular storage. It never changes anything in
the input folder, and never invents a folder name: folders are created only
when a name is typed, exactly as typed.

A log of what the app did is kept in Download/IGprepper for when something
goes wrong. It records the names of folders the app was asked to create, and
nothing about what was already in the storage: existing folders and files
appear on screen but are never written down.
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
from igprep.core.preview import PROXY_MAX
from igprep.core.render import RESAMPLE
from igprep.core.settings import Framing

from . import (
    androidimage,
    androidui,
    framing,
    gestures,
    icons,
    places,
    storage,
    touch,
    views,
    words,
)
from .browser import Browser
from .palette import ACCENT, BUTTON_LOOKS, DIM
from .phonelog import PhoneLog

ICON_DP = 20   # how large an icon is drawn beside a button's label
ICON_PX = 96   # how large it is made, which is larger: it is shrunk to fit

FIT_CHOICES = {
    "Fit – show the whole photo": "fit",
    "Fill – crop to the frame": "crop",
}
# How long the guide lines stay after the last press of a rotation button.
GUIDE_SECONDS = 3
KEPT_LOGS = 10
# The divider can be dragged until this much of a list is left, and no
# further: enough to see that it is there, and to drag it back.
LEAST_LIST_DP = 28
# Coming back to the app re-reads the folders, but not more often than this.
REREAD_SECONDS = 2.0


@dataclass
class Held:
    """Where the preview is on screen and what it is showing, for as long
    as fingers are on it. None of it changes while they are."""

    centre_x: float
    centre_y: float
    scale: float  # screen pixels to pixels of the finished picture
    framing: Framing
    box: tuple[int, int]


@dataclass
class Look:
    """What a button says and how it is drawn."""

    kind: str
    text: str
    icon: str | None
    icon_after: bool = False
    shown: tuple | None = None


class IGprepper(toga.App):
    def startup(self) -> None:
        self.log = PhoneLog()
        self.log.install_excepthook()

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
        # What a drag is measured against, worked out when fingers land.
        self.held: Held | None = None
        self.dragging = False
        self.redraw_pending = False
        self.quick_frames, self.quick_seconds = 0, 0.0
        self.guides_showing = False
        self.guide_timer = None
        self.guide_seconds = GUIDE_SECONDS

        self.looks: dict[toga.Button, Look] = {}
        self.drawn_icons: dict[tuple[str, str], object] = {}
        self.icon_bitmaps: dict[tuple[str, str], object] = {}
        self.back = androidui.BackButton(self.on_back)
        self.views = views.Views(self.paths.data / "views.json")
        self.split_from: tuple[int, int] | None = None
        self.split_to: float | None = None
        self.split_due = False
        self.reread_at = 0.0

        self.build_home()
        self.build_editor()
        self.main_window = toga.MainWindow(title=self.formal_name)
        self.main_window.content = self.home_box
        self.main_window.show()

        self.guard("describing the phone", self.report_environment)
        self.guard("darkening the system bars", androidui.darken_system_bars)
        self.guard("watching for the app being returned to", self.watch_returns)
        self.refresh_controls()

    # --- the two screens ------------------------------------------------------

    def build_home(self) -> None:
        """Two folder browsers, one above the other, with a divider between
        them that can be dragged, and the button that sends the checked
        photos from the upper towards the lower."""
        self.source = Browser(
            self, "input", "Input folder", selects=True,
            ask="Choose the folder your photos are in",
        )
        self.target = Browser(
            self, "output", "Output folder", creates=True,
            ask="Choose the folder framed photos should go to",
        )
        self.browsers = (self.source, self.target)

        self.divider = toga.Box(style=Pack(height=22))
        self.guard("making the divider draggable", self.make_divider)
        self.process_btn = self.button(
            "Frame selected photos", self.process_selected, icon="photo",
            kind="primary", margin_bottom=6,
        )
        self.gallery_switch = toga.Switch(
            "Also save to this phone\u2019s gallery", value=True,
            style=Pack(margin_top=4),
        )

        self.home_box = toga.Box(
            children=[
                *self.source.rows, self.source.holder,
                self.divider, self.process_btn,
                *self.target.rows, self.target.holder,
                self.gallery_switch,
            ],
            style=Pack(direction=COLUMN, margin=12),
        )
        self.apply_split(self.views.split)

    # --- the divider ------------------------------------------------------------

    def make_divider(self) -> None:
        # Kept on the app so it is not swept away while Android still holds it.
        self.divider_listener = androidui.drag_handle(
            self.divider._impl.native, self.split_started, self.split_moved,
            self.split_ended, lambda: self.log.exception("dragging the divider"),
        )

    def list_heights(self) -> tuple[int, int]:
        """How tall each list is on screen at the moment, in its pixels."""
        return tuple(
            androidui.height(browser.holder._impl.native) for browser in self.browsers
        )

    def apply_split(self, share: float) -> None:
        """Give the upper list this share of the room the two have."""
        self.source.holder.style.flex = max(1, round(share * 1000))
        self.target.holder.style.flex = max(1, round((1 - share) * 1000))

    def split_started(self) -> None:
        self.split_from = self.list_heights()
        self.split_to = None

    def split_moved(self, down: float) -> None:
        if self.split_from is None:
            return
        upper, lower = self.split_from
        height = views.divide(upper, lower, down, androidui.dp(LEAST_LIST_DP))
        if height is None:
            return
        self.split_to = height / (upper + lower)
        # Fingers report faster than the screen can be laid out again.
        if not self.split_due:
            self.split_due = True
            self.loop.call_soon(self.split_now)

    def split_now(self) -> None:
        self.split_due = False
        if self.split_to is not None:
            self.guard("moving the divider", lambda: self.apply_split(self.split_to))

    def split_ended(self) -> None:
        self.split_from = None
        if self.split_to is not None:
            share = self.split_to
            self.guard("noting where the divider is", lambda: self.views.set_split(share))

    # --- coming back to the app ---------------------------------------------------

    def watch_returns(self) -> None:
        self.returns = androidui.Returns(
            self.returned, lambda: self.log.exception("noticing a return to the app")
        )

    def returned(self) -> None:
        """The app is on screen again. Files may have arrived, gone, or
        gained a picture while it was not, so both folders are read again."""
        if self.busy or self.main_window.content is not self.home_box:
            return
        now = time.monotonic()
        if now - self.reread_at < REREAD_SECONDS:
            return
        self.reread_at = now
        for browser in self.browsers:
            if browser.tree is not None:
                asyncio.ensure_future(self.reread(browser))

    async def reread(self, browser) -> None:
        try:
            await browser.reload(ask_again=True)
        except Exception:
            self.log.exception(f"re-reading the {browser.side} folder")

    # --- the editor, and moving between the two screens --------------------------

    def build_editor(self) -> None:
        """The photo on top, everything that changes it beneath."""
        self.previous_btn = self.button(
            "Previous photo", self.previous_photo, icon="previous"
        )
        self.count_label = toga.Label("", style=Pack(flex=1, text_align=CENTER))
        self.next_btn = self.button(
            "Next photo", self.next_photo, icon="next", icon_after=True
        )
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

        for menu in (self.ratio_select, self.fit_select):
            self.guard(
                "outlining a menu",
                lambda m=menu: androidui.outline_dropdown(m._impl.native, ACCENT),
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
        # The lists are Android's own, and need telling they are back.
        for browser in self.browsers:
            browser.show_rows()
        self.guard("handing Back to the phone", lambda: self.back.listen(False))
        self.refresh_controls()

    def show_editor(self) -> None:
        self.main_window.content = self.editor_box
        # From here Back means "leave the editor", not "close the app".
        self.guard("taking over Back", lambda: self.back.listen(True))
        self.refresh_controls()

    async def on_running(self) -> None:
        """Once the screen is up: pick up last session's folders, if any."""
        await self.restore_places()
        self.guard("clearing out old logs", lambda: self.log.prune(KEPT_LOGS))
        self.log.write("")
        self.log.write("=== Ready ===")
        if androidui.launched_with("selftest"):
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

    def report_environment(self) -> None:
        log = self.log
        log.section(f"IGprepper phone app, version {self.version}")
        log.write(f"Log file: {log.location}")

        for line in androidui.device():
            log.write(line)
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
        kind: str = "plain", icon_after: bool = False, **style,
    ) -> toga.Button:
        """A button with an icon beside its label, in one of the app's looks."""
        made = toga.Button(text, on_press=on_press, style=Pack(**style))
        self.looks[made] = Look(kind, text, icon, icon_after)
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
                icons.icon(name, ICON_PX, colour), ICON_DP
            )
        return self.drawn_icons[key]

    def icon_bitmap(self, name: str, colour: str):
        """An icon as a plain picture, for a row of a list."""
        key = (name, colour)
        if key not in self.icon_bitmaps:
            self.icon_bitmaps[key] = androidui.bitmap(
                icons.icon(name, ICON_PX, colour)
            )
        return self.icon_bitmaps[key]

    def dress(self, button: toga.Button, on: bool) -> None:
        look = self.looks[button]
        state = (on, look.text, look.icon)
        if look.shown == state:
            return
        look.shown = state
        colours = BUTTON_LOOKS[look.kind if on else "off"]
        button.style.update(**colours)

        def label() -> None:
            icon = (
                self.drawn_icon(look.icon, colours["color"]) if look.icon else None
            )
            androidui.label(button._impl.native, look.text, icon, look.icon_after)

        self.guard("labelling a button", label)
        button.refresh()

    def relabel(self, button: toga.Button, text: str) -> None:
        self.looks[button].text = text
        self.dress(button, bool(button.enabled))

    def reicon(self, button: toga.Button, icon: str) -> None:
        self.looks[button].icon = icon
        self.dress(button, bool(button.enabled))

    def switch(self, button: toga.Button, on: bool) -> None:
        """Enable or disable a button, and make the difference visible."""
        shown = self.looks[button].shown
        if shown is not None and shown[0] == on:
            return  # as it already is: most are, most of the time
        button.enabled = on
        self.dress(button, on)

    def refresh_controls(self) -> None:
        free = not self.busy
        editing = bool(self.picked)
        several = len(self.picked) > 1

        for browser in self.browsers:
            browser.refresh_controls(free)
        self.switch(self.process_btn, free and bool(self.source.checked))

        self.switch(self.previous_btn, free and several)
        self.switch(self.next_btn, free and several)
        for turn in self.turn_btns:
            self.switch(turn, free and editing)
        self.switch(self.cancel_btn, free)
        self.switch(self.save_btn, free and editing)

    # --- the two folders ------------------------------------------------------------

    def places_file(self):
        return self.paths.data / "places.json"

    async def restore_places(self) -> None:
        """Open each side where the last session left it."""
        self.log.section("Folders from an earlier session")
        try:
            remembered = places.load(self.places_file())
            # Versions before this one had a single folder and kept no note
            # of it. That folder was where framed photos went.
            if all(place.tree is None for place in remembered.values()):
                earlier = storage.newest_writable_grant()
                if earlier is not None:
                    remembered["output"] = places.Place(storage.address(earlier))
        except Exception:
            self.log.exception("reading the remembered folders")
            remembered = {}
        restored = 0
        for browser in self.browsers:
            try:
                place = remembered.get(browser.side, places.Place())
                restored += await browser.restore(place)
            except Exception:
                self.log.exception(f"restoring the {browser.side} folder")
        if not restored:
            self.log.write("None: no folder has been chosen yet.")
        self.places_changed()
        self.refresh_controls()

    def places_changed(self, released: str | None = None) -> None:
        """Note where both sides now are, for next time. `released` is a
        folder one side has just left for a different one."""
        current = {browser.side: browser.place() for browser in self.browsers}
        self.guard(
            "noting the folders", lambda: places.save(self.places_file(), current)
        )
        if released is not None and all(
            place.tree != released for place in current.values()
        ):
            self.guard("giving up a folder", lambda: storage.release(released))

    def selection_changed(self) -> None:
        self.refresh_controls()

    # --- choosing photos ------------------------------------------------------------

    def current_framing(self) -> Framing:
        return Framing(
            ratio=self.ratio_choices.get(self.ratio_select.value, g.DEFAULT_RATIO),
            mode=FIT_CHOICES.get(self.fit_select.value, "fit"),
            border_pct=round(float(self.border_slider.value) * 2) / 2,
        )

    async def process_selected(self, widget=None) -> None:
        await self.exclusively("opening the checked photos", self._process_selected())

    async def _process_selected(self) -> None:
        self.log.section("Framing photos")
        chosen = self.source.chosen()
        if not chosen:
            self.log.write("No photos are checked.")
            return
        self.forget_photos()
        tree = self.source.tree
        self.picked = [
            (storage.document_uri(tree, entry.doc_id), entry.name) for entry in chosen
        ]
        self.log.write(f"{len(self.picked)} photo(s) checked. Names are not logged.")
        await self.show_photo()
        self.show_editor()

    def let_go(self) -> None:
        """Drop whatever was in progress on the preview: guide lines, and
        fingers part-way through a drag."""
        self.clear_guides()
        self.tracker.ended()
        self.held = None
        self.dragging = False

    def forget_photos(self) -> None:
        self.let_go()
        self.picked, self.proxies, self.placements = [], {}, {}
        self.sizes, self.quick_proxies = {}, {}
        self.preview_plain = None
        self.preview_index = 0

    def load_proxy(self, address) -> tuple[Image.Image, tuple[int, int]]:
        data = storage.read_uri(address)
        image = framing.prepare(data, androidimage.decode_to_srgb)
        size = image.size
        # Shrunk where it is. The full-size photo is not wanted again until
        # saving, and a copy of it is a great deal of memory.
        image.thumbnail((PROXY_MAX, PROXY_MAX), RESAMPLE)
        return image, size

    async def show_photo(self, index: int | None = None) -> None:
        """Show one of the photos: the one given, or the one already showing.
        It becomes the one showing only once it has been opened, so a photo
        that will not open leaves the screen on the one before."""
        index = self.preview_index if index is None else index
        if index not in self.proxies:
            started = time.perf_counter()
            proxy, size = await self.work(self.load_proxy, self.picked[index][0])
            self.proxies[index] = proxy
            self.sizes[index] = size
            self.log.write(
                f"Photo {index + 1}: opened at {size[0]} x {size[1]} in "
                f"{time.perf_counter() - started:.2f} s"
            )
        self.preview_index = index
        self.let_go()
        self.update_preview()

    async def next_photo(self, widget=None) -> None:
        await self.exclusively("showing the next photo", self._step(1))

    async def previous_photo(self, widget=None) -> None:
        await self.exclusively("showing the previous photo", self._step(-1))

    async def _step(self, by: int) -> None:
        await self.show_photo((self.preview_index + by) % len(self.picked))

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

    def update_preview(self, widget=None, chosen: Framing | None = None) -> None:
        """Redraw the preview properly. `chosen` is the framing, where the
        caller has already read it from the controls."""
        proxy = self.proxies.get(self.preview_index)
        if proxy is None:
            return
        try:
            chosen = chosen or self.current_framing()
            # A change of shape or border moves the zoom limit.
            self.place(
                g.within_limits(
                    self.sizes[self.preview_index], framing.output_box(chosen),
                    self.placement(),
                )
            )
            self.describe(chosen)
            self.preview_plain = framing.preview(proxy, chosen, self.placement())
            self.draw_preview(chosen)
        except Exception:
            self.log.exception("drawing the preview")

    def describe(self, chosen: Framing) -> None:
        """Everything on the editor that is words rather than picture."""
        placement = self.placement()
        count = len(self.picked)
        angle = framing.angle_label(placement.angle)
        self.count_label.text = f"{self.preview_index + 1} of {count}"
        self.border_value.text = f"{chosen.border_pct:g}%"
        self.relabel(self.angle_btn, angle)
        self.hint_label.text = words.hint(
            changed=placement != g.Placement(),
            forced_to_fill=placement.positioned and chosen.mode == "fit",
            angle=angle,
        )
        self.relabel(self.save_btn, "Save photo" if count == 1 else "Save photos")

    def draw_preview(self, chosen: Framing | None = None) -> None:
        image = self.preview_plain
        if image is None:
            return
        if self.guides_showing:
            image = framing.guided(image, chosen or self.current_framing())
        self.preview_view.image = toga.Image(image)

    # --- turning a photo ------------------------------------------------------

    def rotate(self, degrees: int) -> None:
        if self.busy or self.preview_index not in self.proxies:
            return
        chosen = self.current_framing()
        self.place(
            g.turned_further(
                self.sizes[self.preview_index], framing.output_box(chosen),
                self.placement(), degrees,
            )
        )
        self.show_guides()
        self.update_preview(chosen=chosen)

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
        self.finger_listener = touch.listen(
            self.preview_view._impl.native, self.on_fingers,
            lambda: self.log.exception("following a finger"),
        )
        self.live = touch.Canvas()

    def hold(self) -> Held:
        centre_x, centre_y, shown_width = touch.shown_at(
            self.preview_view._impl.native
        )
        chosen = self.current_framing()
        return Held(
            centre_x, centre_y, framing.OUTPUT_WIDTH / shown_width,
            chosen, framing.output_box(chosen),
        )

    def on_fingers(self, kind: str, points) -> None:
        if self.busy or self.preview_index not in self.proxies:
            return
        if kind == touch.CHANGED:
            # Asked of Android and of the controls here, when fingers land or
            # lift, and not again for each of the many moves in between.
            self.held = self.hold()
            self.tracker.changed(points)
        elif kind == touch.MOVED:
            step = self.tracker.moved(points)
            if step is not None:
                self.drag(step)
        else:
            self.tracker.ended()
            self.held = None
            if self.dragging:
                # The fingers have gone: draw it properly.
                self.dragging = False
                self.update_preview()

    def drag(self, step: gestures.Step) -> None:
        """Move the photo with the fingers."""
        held = self.held = self.held or self.hold()

        def on_output(point):
            # Screen pixels to pixels of the finished picture, from its centre.
            return (
                (point[0] - held.centre_x) * held.scale,
                (point[1] - held.centre_y) * held.scale,
            )

        self.place(
            g.moved(
                self.sizes[self.preview_index], held.box, self.placement(),
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
            chosen = self.held.framing if self.held else self.current_framing()
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
        target = self.target
        if target.tree is None and not to_gallery:
            await self.tell(
                "Nowhere to save",
                "No output folder is chosen and saving to the gallery is "
                "switched off. Go back and choose an output folder, or switch "
                "the gallery on.",
            )
            return
        here = target.here if target.tree is not None else None
        folder = target.folder_name
        total = len(self.picked)
        saved, pictures = await self.work(
            self.save_framed_now, list(self.picked), self.current_framing(),
            dict(self.placements), to_gallery, target.tree, here,
        )
        # Done with: what was checked has been processed.
        self.source.uncheck_all()
        self.show_home()
        # Show the new files where they landed. If input and output are the
        # same folder, they have landed in both.
        for browser in self.browsers:
            if browser.tree is not None and (
                browser is target or browser.place() == target.place()
            ):
                # Cloud storage has no thumbnail for a file it was handed a
                # moment ago. This app has the picture itself, so it shows
                # that rather than a blank.
                for doc_id, picture in pictures.items():
                    self.guard(
                        "showing a saved photo",
                        lambda d=doc_id, p=picture: browser.files.seed(d, p),
                    )
                try:
                    await browser.reload()
                except Exception:
                    # The photos are saved whether or not the folder can be
                    # read again; say so, and leave the list as it was.
                    self.log.exception(f"re-reading the {browser.side} folder")
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
        # Under the photo, where there is room for it.
        self.hint_label.text = f"Saving {number} of {total}\u2026"

    def save_framed_now(
        self, picked, chosen: Framing, placements, to_gallery, tree, here
    ) -> tuple[int, dict]:
        """One photo at a time, start to finish, so memory stays flat.

        Returns how many were saved, and a small picture of each file put in
        the folder, by the name the storage app knows it by.
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
        pictures: dict[str, Image.Image] = {}
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
                    pictures[entry.doc_id] = framing.small_copy(result.jpeg)
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
        return saved, pictures


def main() -> IGprepper:
    return IGprepper()
