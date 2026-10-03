"""IGprepper phone test app.

Build 1 proves the route from GitHub to the phone, and that the log file can
be found and shared. It does no Proton Drive or image work yet.
"""

from __future__ import annotations

import platform
import sys

import toga
from toga.style import Pack
from toga.style.pack import COLUMN

from .phonelog import PhoneLog

BUILD = "Build 1"


class IGprepperTest(toga.App):
    def startup(self) -> None:
        self.log = PhoneLog()
        self.log.install_excepthook()

        self.output = toga.MultilineTextInput(readonly=True, style=Pack(flex=1))
        heading = toga.Label(
            f"IGprepper test app - {BUILD}", style=Pack(margin_bottom=8)
        )
        button = toga.Button(
            "Write a test line to the log",
            on_press=self.write_test_line,
            style=Pack(margin_top=8),
        )
        box = toga.Box(
            children=[heading, self.output, button],
            style=Pack(direction=COLUMN, margin=12),
        )

        self.main_window = toga.MainWindow(title=self.formal_name)
        self.main_window.content = box
        self.main_window.show()

        # Show what was logged before the screen existed, then follow along.
        self.output.value = "\n".join(self.log.lines)
        self.log.listeners.append(self.show_line)

        try:
            self.report_environment()
        except Exception:
            self.log.exception("describing the phone")

    def show_line(self, line: str) -> None:
        self.output.value = (self.output.value or "") + "\n" + line

    def write_test_line(self, widget) -> None:
        self.presses = getattr(self, "presses", 0) + 1
        self.log.write(f"Test line {self.presses}: the button was pressed")

    # --- what Build 1 reports ---------------------------------------------

    def report_environment(self) -> None:
        log = self.log
        log.section(f"IGprepper test app, {BUILD}")
        log.write(f"App version: {self.version}")
        log.write(f"Log file: {log.location}")

        log.section("Phone")
        try:
            from android.os import Build

            log.write(f"Android {Build.VERSION.RELEASE} (API {Build.VERSION.SDK_INT})")
            log.write(f"Model: {Build.MANUFACTURER} {Build.MODEL}")
        except Exception:
            log.exception("reading the Android version")

        log.section("Python")
        log.write(f"Python {sys.version.split()[0]} on {platform.machine()}")
        log.write(f"Toga {toga.__version__}")

        log.section("Image library")
        try:
            import PIL
            from PIL import features

            log.write(f"Pillow {PIL.__version__}")
            for name, label in (
                ("littlecms2", "Colour-profile conversion"),
                ("jpg", "JPEG"),
                ("libjpeg_turbo", "Fast JPEG codec"),
                ("zlib", "PNG"),
                ("webp", "WebP"),
                ("libtiff", "TIFF"),
            ):
                available = features.check(name)
                version = features.version(name) if available else None
                detail = f" ({version})" if version else ""
                log.write(f"{label}: {'yes' if available else 'NO'}{detail}")
        except Exception:
            log.exception("loading the image library")

        log.section("Done")
        log.write("Build 1 checks finished. Press the button to add a line,")
        log.write("then open the log file in the Files app and share it.")


def main() -> IGprepperTest:
    return IGprepperTest()
