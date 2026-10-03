"""Press the system pickers' buttons during the build's emulator check.

    python phone/tools/ci_drive.py /path/to/adb [seconds]

The app's self-test opens Android's folder picker and then its file picker,
and in an emulator there is nobody to press anything. This watches the
screen, presses what a person would, and stops once the app's log says the
self-test has finished.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ADB = sys.argv[1]
SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 300
LOGS = "/sdcard/Download/IGprepper"
FINISHED = "=== Self-test finished ==="
TEST_PHOTO = "igprepper-test-photo.jpg"

# Buttons to press whenever they are on screen, matched on their whole label.
BUTTONS = ("use this folder", "allow", "select", "open")

SHOTS = Path("screenshots")
SHOT_REQUEST = re.compile(r"SCREENSHOT (\S+)")
captured: set[str] = set()

TAG = re.compile(r"<node\b([^>]*)>")
ATTRIBUTE = re.compile(r'([\w-]+)="([^"]*)"')
BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def adb(*args: str) -> str:
    result = subprocess.run(
        [ADB, *args], capture_output=True, text=True, errors="replace"
    )
    return result.stdout


def newest_log() -> str:
    name = adb("shell", f"ls -t {LOGS}/*.txt 2>/dev/null | head -1").strip()
    return adb("shell", "cat", name) if name else ""


def capture_requested(log: str) -> bool:
    """Photograph the screen for each request in the log not yet honoured."""
    took = False
    for name in SHOT_REQUEST.findall(log):
        if name in captured:
            continue
        captured.add(name)
        time.sleep(2)  # let the screen settle after the request was logged
        png = subprocess.run(
            [ADB, "exec-out", "screencap", "-p"], capture_output=True
        ).stdout
        SHOTS.mkdir(exist_ok=True)
        (SHOTS / f"{name}.png").write_bytes(png)
        print(f"captured {name} ({len(png)} bytes)", flush=True)
        took = True
    return took


def screen() -> list[dict]:
    adb("shell", "uiautomator", "dump", "/sdcard/window.xml")
    xml = adb("shell", "cat", "/sdcard/window.xml")
    return [dict(ATTRIBUTE.findall(tag)) for tag in TAG.findall(xml)]


def tap(node: dict, why: str) -> bool:
    match = BOUNDS.fullmatch(node.get("bounds", ""))
    if not match:
        return False
    left, top, right, bottom = map(int, match.groups())
    x, y = (left + right) // 2, (top + bottom) // 2
    adb("shell", "input", "tap", str(x), str(y))
    print(f"pressed {why} at {x},{y}", flush=True)
    return True


def label(node: dict) -> str:
    return node.get("text", "").strip().lower()


def act(nodes: list[dict]) -> bool:
    for wanted in BUTTONS:
        for node in nodes:
            if label(node) == wanted and node.get("enabled") != "false":
                return tap(node, repr(node.get("text")))

    # The test photo, wherever its name appears: as a caption in a list, or
    # only as a description when the picker shows a grid of thumbnails.
    for node in nodes:
        named = TEST_PHOTO in label(node) or TEST_PHOTO in node.get("content-desc", "").lower()
        if named and "documentsui" in node.get("package", ""):
            return tap(node, "the test photo")

    # Failing that, in the image picker, the first thumbnail on offer.
    if any(label(n).startswith("images in ") for n in nodes):
        for node in nodes:
            identifier = node.get("resource-id", "")
            if identifier.endswith((":id/item_root", ":id/icon_thumb", ":id/thumbnail")):
                return tap(node, f"the first thumbnail ({identifier})")
    return False


def describe(nodes: list[dict]) -> None:
    for node in nodes:
        text, desc = node.get("text", ""), node.get("content-desc", "")
        identifier = node.get("resource-id", "")
        if text or desc or identifier.rsplit("/", 1)[-1] in ("item_root", "icon_thumb", "thumbnail"):
            kind = node.get("class", "").rsplit(".", 1)[-1]
            print(f"  {kind:<14} id={identifier.rsplit('/', 1)[-1]:<18} "
                  f"text={text[:60]!r} desc={desc[:60]!r} {node.get('bounds', '')}")


def main() -> int:
    deadline = time.time() + SECONDS
    while time.time() < deadline:
        log = newest_log()
        if FINISHED in log:
            print("the self-test finished", flush=True)
            return 0
        if capture_requested(log):
            continue
        pressed = act(screen())
        time.sleep(1 if pressed else 2)

    print("Timed out waiting for the self-test. On screen:")
    describe(screen())
    return 1


if __name__ == "__main__":
    sys.exit(main())
