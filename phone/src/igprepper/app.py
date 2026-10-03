"""IGprepper phone test app.

Build 2 answers the question the project depends on: can an app create
folders and files inside Proton Drive through Android's folder picker, and
does Proton sync them? It also runs the image pipeline's own checks on the
phone.

The app never invents a folder name. Folders are created only when a name is
typed and the button pressed, exactly as typed.

The log records what the app did, including the names of folders it was asked
to create. It does not record what was already in the storage: existing
folders appear on screen but are never written to the log.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import sys
import time
from datetime import datetime

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from . import androidimage, imagetests, storage
from .phonelog import PhoneLog

BUILD = "Build 2"
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

        self.build_screen()
        self.output.value = "\n".join(self.log.lines)
        self.log.listeners.append(self.show_line)

        self.guard("describing the phone", self.report_environment)
        self.refresh_controls()

    def build_screen(self) -> None:
        heading = toga.Label(f"IGprepper test app - {BUILD}")
        self.choose_btn = toga.Button(
            "Choose a folder", on_press=self.choose_folder, style=Pack(margin_top=6)
        )
        self.location = toga.Label("No folder chosen yet", style=Pack(margin_top=6))

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
        self.output = toga.MultilineTextInput(
            readonly=True, style=Pack(flex=1, margin_top=8)
        )

        box = toga.Box(
            children=[
                heading, self.choose_btn, self.location, navigate, create,
                self.files_btn, self.images_btn, self.output,
            ],
            style=Pack(direction=COLUMN, margin=12),
        )
        self.main_window = toga.MainWindow(title=self.formal_name)
        self.main_window.content = box
        self.main_window.show()

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

    def refresh_controls(self) -> None:
        have_folder = self.tree is not None
        free = not self.busy
        self.choose_btn.enabled = free
        self.images_btn.enabled = free
        self.open_btn.enabled = free and have_folder and bool(self.subfolders)
        self.up_btn.enabled = free and len(self.trail) > 1
        self.create_btn.enabled = free and have_folder
        self.files_btn.enabled = free and have_folder

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
        log.section(f"IGprepper test app, {BUILD}")
        log.write(f"App version: {self.version}")
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
        self.log.write("The storage app allows: " + (", ".join(allowed) or "nothing"))
        if refused:
            self.log.write("It does not allow: " + ", ".join(refused))

    async def refresh_listing(self) -> None:
        entries = await self.work(storage.children, self.tree, self.here)
        self.subfolders = sorted(
            (e for e in entries if e.is_dir), key=lambda e: e.name.lower()
        )
        files = sum(1 for e in entries if not e.is_dir)
        self.folder_select.items = [e.name for e in self.subfolders]
        self.location.text = " / ".join(name for _, name in self.trail)
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


def main() -> IGprepperTest:
    return IGprepperTest()
