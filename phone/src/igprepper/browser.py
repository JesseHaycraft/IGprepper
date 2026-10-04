"""One half of the main screen: a folder, and a way around inside it.

The main screen is two of these. The upper one is where photos come from:
it can only look, and its photos can be checked for processing. The lower
one is where framed photos go: nothing in it can be checked, and it can make
new folders. Otherwise they are the same thing, and this is it.

Android does not let an app wander through storage. A folder is granted
once, in Android's own picker, and the app may then go anywhere inside it
but never above it. So "Up" stops at the granted folder, and "Change" is how
to start somewhere else.

This module only imports on Android.
"""

from __future__ import annotations

import asyncio

import toga
from toga.style import Pack
from toga.style.pack import CENTER, ROW

from . import androidui, entries, storage, words
from .filelist import FileList
from .places import Place

DIM = "#9AA0A6"
# Cloud storage hands over a large folder in instalments.
RECHECK_SECONDS = 1.5
RECHECKS = 40


class Browser:
    def __init__(
        self, app, side: str, title: str, *,
        selects: bool = False, creates: bool = False, ask: str = "",
    ) -> None:
        self.app, self.side, self.title = app, side, title
        self.selects, self.creates, self.ask = selects, creates, ask

        self.tree = None
        # The path from the granted folder down to where we are: (id, name).
        self.trail: list[tuple[str, str]] = []
        self.entries: list[entries.Entry] = []
        self.checked: set[str] = set()
        # Folders this app created, whose names may therefore be logged.
        self.created: set[str] = set()
        self.still_loading = False
        self.visit = 0  # counts changes of folder, to drop late answers
        self.name_dialog = None
        self.files: FileList | None = None
        self.build()

    # --- the screen -------------------------------------------------------------

    def build(self) -> None:
        """The pieces of this half of the screen. The app stacks them:
        `rows`, then `holder`, which is the part that stretches."""
        app = self.app
        heading = toga.Label(
            self.title, style=Pack(font_weight="bold", font_size=11)
        )
        # The path sits beside the heading, in whatever room is left.
        self.path_holder = toga.Box(style=Pack(flex=1, height=24, margin_left=10))
        top = toga.Box(
            children=[heading, self.path_holder],
            style=Pack(direction=ROW, align_items=CENTER),
        )

        self.up_btn = app.button("Up", self.up, icon="up", flex=1)
        tools = [self.up_btn]
        self.new_btn = None
        if self.creates:
            self.new_btn = app.button(
                "New folder", self.new_folder, icon="new_folder",
                flex=1, margin_left=6,
            )
            tools.append(self.new_btn)
        self.choose_btn = app.button(
            "Change", self.choose, icon="folder", flex=1, margin_left=6
        )
        tools.append(self.choose_btn)
        # List or tiles. Only offered once there is a folder to look at:
        # before that the row is needed for the words "Choose folder".
        self.view_btn = app.button(
            "", self.toggle_view, icon="tiles", width=52, margin_left=6
        )
        self.view_offered = False
        self.tools = toga.Box(
            children=tools, style=Pack(direction=ROW, margin_top=2, margin_bottom=4)
        )

        # No margin of its own: the divider shares out the room between the
        # two lists exactly, and a margin would be counted as part of one.
        self.holder = toga.Box(style=Pack(flex=1))
        self.rows = [top, self.tools]
        self.path_view = None
        app.guard(f"building the {self.side} list", self.build_list)
        self.show_path()
        self.show_rows(fresh=True)

    def build_list(self) -> None:
        self.path_view = androidui.end_showing_text(
            self.path_holder._impl.native, DIM, 13
        )
        self.files = FileList(
            self.holder._impl.native, self.app.loop, self.app.log,
            self.app.icon_bitmap, self.pressed,
        )

    def refresh_controls(self, free: bool) -> None:
        app = self.app
        app.switch(self.choose_btn, free)
        app.switch(self.up_btn, free and len(self.trail) > 1)
        app.switch(self.view_btn, free and self.tree is not None)
        if self.new_btn is not None:
            app.switch(self.new_btn, free and self.tree is not None)

    @property
    def here(self) -> str:
        return self.trail[-1][0]

    @property
    def folder_name(self) -> str | None:
        return self.trail[-1][1] if self.tree is not None else None

    @property
    def path(self) -> str:
        """What the line beside the heading says."""
        if self.tree is None:
            return "No folder chosen"
        return storage.where(self.tree, self.trail)

    @property
    def view_key(self) -> str:
        """What this folder is remembered by, for how it was last shown."""
        return f"{storage.address(self.tree)}\n{self.here}"

    @property
    def tiled(self) -> bool:
        return self.tree is not None and self.app.views.is_tiled(self.view_key)

    def show_path(self) -> None:
        if self.path_view is not None:
            self.path_view.setText(self.path)
        self.app.relabel(
            self.choose_btn, "Change" if self.tree is not None else "Choose folder"
        )
        offered = self.tree is not None
        if offered != self.view_offered:
            self.view_offered = offered
            if offered:
                self.tools.add(self.view_btn)
            else:
                self.tools.remove(self.view_btn)
        # The button shows the way of looking that pressing it would give.
        self.app.reicon(self.view_btn, "list" if self.tiled else "tiles")

    def toggle_view(self, widget=None) -> None:
        if self.app.busy or self.tree is None:
            return
        self.app.guard(
            "noting how a folder is shown",
            lambda: self.app.views.set_tiled(self.view_key, not self.tiled),
        )
        self.show_path()
        self.show_rows(fresh=True)

    def show_rows(self, fresh: bool = False) -> None:
        """Put the current entries, marks and messages on screen."""
        files = self.files
        if files is None:
            return
        files.checked = self.checked
        if fresh:
            tree = self.tree
            fetch = None
            if tree is not None:
                fetch = lambda doc_id, side: storage.thumbnail(tree, doc_id, side)  # noqa: E731
            files.show(
                self.entries, fetch, selectable=self.selects, tiles=self.tiled
            )
        else:
            files.update(self.entries)

        if self.tree is None:
            files.say(self.ask)
        elif self.entries:
            files.say(None)
        else:
            files.say("Loading…" if self.still_loading else "This folder is empty")
        self.show_count()

    def show_count(self) -> None:
        if self.files is None:
            return
        if self.checked:
            self.files.count(words.selected(len(self.checked)))
        elif self.still_loading and self.entries:
            self.files.count("Loading more…")
        else:
            self.files.count(None)

    # --- being pressed ------------------------------------------------------------

    def pressed(self, entry: entries.Entry) -> None:
        """A row was pressed. Folders open; photos, where they can be chosen,
        are checked or unchecked."""
        if self.app.busy:
            return
        if entry.is_dir:
            asyncio.ensure_future(self.open(entry))
        elif self.selects and entry.is_photo:
            self.toggle(entry)
        elif self.selects:
            self.app.announce(
                "That is not a photo this app can frame",
                logged="a file that is not a photo was pressed.",
            )

    def toggle(self, entry: entries.Entry) -> None:
        if entry.doc_id in self.checked:
            self.checked.discard(entry.doc_id)
        else:
            self.checked.add(entry.doc_id)
        self.show_rows()
        self.app.selection_changed()

    def uncheck_all(self) -> None:
        if self.checked:
            self.checked.clear()
            self.show_rows()
            self.app.selection_changed()

    def chosen(self) -> list[entries.Entry]:
        return entries.chosen(self.entries, self.checked)

    # --- moving around ----------------------------------------------------------------

    async def choose(self, widget=None, initial=None) -> None:
        await self.app.exclusively(
            f"choosing the {self.side} folder", self._choose(initial)
        )

    async def _choose(self, initial) -> None:
        log = self.app.log
        log.section(f"Choosing the {self.side} folder")
        tree = await storage.pick_folder(self.app, initial, write=self.creates)
        if tree is None:
            log.write("The picker was closed without a folder being chosen.")
            return
        before = storage.address(self.tree) if self.tree is not None else None
        root = await self.app.work(storage.describe, tree, storage.root_id(tree))
        self.tree = tree
        self.trail = [(root.doc_id, root.name)]
        self.created = set()
        log.write(f"PASS  Access to the {self.side} folder granted through the picker.")
        log.write(f"Storage app: {storage.provider_name(tree)}")
        self.app.places_changed(released=before)
        await self.load()

    async def restore(self, place: Place) -> bool:
        """Pick up where the last session left this side. True if it could."""
        if place.tree is None:
            return False
        tree = storage.held(place.tree, write=self.creates)
        if tree is None:
            return False
        log = self.app.log
        root = await self.app.work(storage.describe, tree, storage.root_id(tree))
        trail = [(root.doc_id, root.name)]
        # The folder last looked at, if it is still there to look at.
        if len(place.trail) > 1 and place.trail[0][0] == root.doc_id:
            try:
                await self.app.work(storage.describe, tree, place.trail[-1][0])
                trail = list(place.trail)
            except Exception:
                log.write(
                    f"The {self.side} folder last open has gone; starting from "
                    "the folder above it."
                )
        self.tree, self.trail, self.created = tree, trail, set()
        log.write(
            f"PASS  Access to the {self.side} folder still held from an earlier "
            f"session, {len(trail) - 1} level(s) down, with no trip through the picker."
        )
        await self.load()
        return True

    def place(self) -> Place:
        if self.tree is None:
            return Place()
        return Place(storage.address(self.tree), list(self.trail))

    async def open(self, entry: entries.Entry) -> None:
        await self.app.exclusively(
            f"opening a folder on the {self.side} side", self._open(entry)
        )

    async def _open(self, entry: entries.Entry) -> None:
        self.trail.append((entry.doc_id, entry.name))
        depth = len(self.trail) - 1
        if entry.doc_id in self.created:
            self.app.log.write(
                f"{self.title}: opened {entry.name!r}, {depth} level(s) down."
            )
        else:
            self.app.log.write(
                f"{self.title}: opened an existing folder, {depth} level(s) down. "
                "Its name is not logged."
            )
        self.app.places_changed()
        await self.load()

    async def up(self, widget=None) -> None:
        await self.app.exclusively(
            f"going up a folder on the {self.side} side", self._up()
        )

    async def _up(self) -> None:
        if len(self.trail) <= 1:
            return
        self.trail.pop()
        self.app.log.write(f"{self.title}: went up, now {len(self.trail) - 1} level(s) down.")
        self.app.places_changed()
        await self.load()

    # --- reading the folder -------------------------------------------------------------

    async def load(self) -> None:
        """Show the folder we are now in. Anything checked is let go: what is
        checked is always something that can be seen."""
        self.visit += 1
        visit = self.visit
        had_checks = bool(self.checked)
        self.checked = set()
        self.entries, self.still_loading = [], True
        self.show_path()
        self.show_rows(fresh=True)
        if had_checks:
            self.app.selection_changed()
        self.app.refresh_controls()
        try:
            found = await self.app.work(storage.listing, self.tree, self.here)
        except Exception:
            self.app.log.exception(f"reading the {self.side} folder")
            if visit == self.visit:
                self.still_loading = False
                self.show_rows()
                if self.files is not None:
                    self.files.say("This folder could not be opened")
            return
        if visit != self.visit:
            return
        self.take(found, fresh=True)
        if found.loading:
            self.app.loop.call_later(RECHECK_SECONDS, self.recheck, visit, 1)

    async def reload(self, ask_again: bool = False) -> None:
        """Read the same folder again, keeping what is checked. `ask_again`
        also has another go at any pictures that were not there before."""
        if self.tree is None:
            return
        if ask_again and self.files is not None:
            self.files.thumbs.ask_again()
        visit = self.visit
        found = await self.app.work(storage.listing, self.tree, self.here)
        if visit == self.visit:
            self.take(found, fresh=False)

    def take(self, found: storage.Listing, fresh: bool) -> None:
        self.entries = entries.ordered(found.entries)
        self.still_loading = found.loading
        kept = entries.still_there(self.entries, self.checked)
        dropped = kept != self.checked
        self.checked = kept
        folders, photos, others = entries.tally(self.entries)
        self.app.log.write(
            f"{self.title}: {folders} folder(s), {photos} photo(s) and {others} "
            f"other file(s){', and still loading' if found.loading else ''}. "
            "Names are not logged."
        )
        self.show_rows(fresh=fresh)
        if dropped:
            self.app.selection_changed()

    def recheck(self, visit: int, attempt: int) -> None:
        if visit == self.visit:
            asyncio.ensure_future(self._recheck(visit, attempt))

    async def _recheck(self, visit: int, attempt: int) -> None:
        try:
            found = await self.app.work(storage.listing, self.tree, self.here)
        except Exception:
            self.app.log.exception(f"reading more of the {self.side} folder")
            found = None
        if visit != self.visit:
            return
        if found is None or attempt >= RECHECKS:
            self.still_loading = False
            self.show_rows()
            return
        self.take(found, fresh=False)
        if found.loading:
            self.app.loop.call_later(RECHECK_SECONDS, self.recheck, visit, attempt + 1)

    # --- making a folder ------------------------------------------------------------------

    async def new_folder(self, widget=None) -> None:
        """Ask for a name, as a file manager does."""
        if self.app.busy or self.tree is None:
            return
        self.name_dialog = androidui.ask_for_text(
            "New folder", "Folder name", "Create", self.name_given
        )

    def name_given(self, name: str) -> None:
        # Called by Android when Create is pressed; the work is done in turn.
        asyncio.ensure_future(self.create_folder(name))

    async def create_folder(self, name: str) -> None:
        await self.app.exclusively("creating a folder", self._create_folder(name))

    async def _create_folder(self, name: str) -> None:
        app, log = self.app, self.app.log
        name = name.strip()
        if not name:
            app.announce("No name was typed, so no folder was created")
            return
        log.section("Creating a folder")
        # Some storage will happily hold two folders of one name. Nobody
        # wants that, so it is settled here.
        if any(e.is_dir and e.name.lower() == name.lower() for e in self.entries):
            log.write("A folder of that name is already here; none created.")
            await app.tell(
                "Already there",
                "This folder already has one called "
                f"“{words.shorten(name, 40)}”.",
                logged="a folder of that name is already here.",
            )
            return
        entry = await app.work(storage.create_folder, self.tree, self.here, name)
        self.created.add(entry.doc_id)
        if entry.name == name:
            log.write(f"PASS  Created {entry.name!r}, exactly as typed.")
        else:
            log.write(
                f"INFO  Asked for {name!r}; the storage app created {entry.name!r}."
            )
        await self.reload()
        app.announce(f"Created “{words.shorten(entry.name, 30)}”")
