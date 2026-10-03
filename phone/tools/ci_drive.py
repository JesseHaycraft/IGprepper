"""Press the folder picker's buttons during the build's emulator check.

    python phone/tools/ci_drive.py /path/to/adb [seconds]

The app's self-test opens Android's folder picker, and in an emulator there
is nobody to press "Use this folder" and then "Allow". This watches the
screen, presses those two buttons when they appear, and stops once the app's
log says the self-test has finished.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time

ADB = sys.argv[1]
SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 420
LOGS = "/sdcard/Download/IGprepper"
FINISHED = "=== Self-test finished ==="
BUTTONS = ("use this folder", "allow")

NODE = re.compile(
    r'<node[^>]*?\btext="([^"]*)"[^>]*?\bbounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
)


def adb(*args: str) -> str:
    result = subprocess.run(
        [ADB, *args], capture_output=True, text=True, errors="replace"
    )
    return result.stdout


def newest_log() -> str:
    name = adb("shell", f"ls -t {LOGS}/*.txt 2>/dev/null | head -1").strip()
    return adb("shell", "cat", name) if name else ""


def screen() -> str:
    adb("shell", "uiautomator", "dump", "/sdcard/window.xml")
    return adb("shell", "cat", "/sdcard/window.xml")


def press(xml: str, wanted: str) -> bool:
    for text, left, top, right, bottom in NODE.findall(xml):
        if text.strip().lower() == wanted:
            x = (int(left) + int(right)) // 2
            y = (int(top) + int(bottom)) // 2
            adb("shell", "input", "tap", str(x), str(y))
            print(f"pressed {text!r} at {x},{y}", flush=True)
            return True
    return False


def main() -> int:
    deadline = time.time() + SECONDS
    while time.time() < deadline:
        if FINISHED in newest_log():
            print("the self-test finished", flush=True)
            return 0
        xml = screen()
        pressed = any(press(xml, button) for button in BUTTONS)
        time.sleep(2 if pressed else 4)

    words = sorted({text for text, *_ in NODE.findall(screen()) if text.strip()})
    print("Timed out waiting for the self-test. Text on screen:")
    for word in words[:40]:
        print(f"  {word[:100]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
