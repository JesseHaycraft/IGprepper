"""The log.

There is no cable to the phone, so this is the only way to see what happened
on it. Every line is handed to a file straight away, so a crash still leaves
everything up to that point. Where that file lives is the platform's
business: on Android it goes where the Files app can reach it
(`native/android/log.py`).

Nothing here lists what is already in anyone's storage: it records only what
the app itself did.

Nothing here is Android-specific; the desktop test suite runs it.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime

from .native import log as files

PREFIX = "igprepper-log-"


class PhoneLog:
    """Timestamped lines, kept in memory and mirrored to a file."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.location = "(no file)"
        self._sink = None

        name = f"{PREFIX}{datetime.now():%Y%m%d-%H%M%S}.txt"
        try:
            self._sink = files.LogFile(name)
            self.location = self._sink.location
        except Exception:
            # Still usable: lines stay in memory.
            self.location = "(log file could not be created)"
            self.write("Could not create the log file:")
            self.write(traceback.format_exc())

    def prune(self, keep: int) -> int:
        """Delete this app's older log files, leaving the newest `keep`.

        A log is written on every launch, and nobody wants a hundred of them
        in their Downloads. Returns how many were removed.
        """
        if self._sink is None:
            return 0
        removed = self._sink.prune(keep, PREFIX)
        if removed:
            self.write(f"Removed {removed} old log file(s); the newest {keep} are kept.")
        return removed

    # --- writing ----------------------------------------------------------

    def write(self, message: str = "") -> None:
        """Add one entry. Multi-line messages keep their line breaks."""
        stamp = datetime.now().strftime("%H:%M:%S")
        for part in str(message).splitlines() or [""]:
            line = f"{stamp}  {part}"
            self.lines.append(line)
            self._store(line + "\n")

    def section(self, title: str) -> None:
        self.write("")
        self.write(f"=== {title} ===")

    def exception(self, doing: str) -> None:
        """Record the exception being handled, with what was being attempted."""
        self.write(f"FAILED while {doing}:")
        self.write(traceback.format_exc())

    def install_excepthook(self) -> None:
        """Send anything uncaught to the log before the default handling."""
        previous = sys.excepthook

        def hook(kind, value, tb):
            self.write("UNCAUGHT ERROR:")
            self.write("".join(traceback.format_exception(kind, value, tb)))
            previous(kind, value, tb)

        sys.excepthook = hook

    def _store(self, text: str) -> None:
        if self._sink is None:
            return
        try:
            self._sink.write(text, lambda: "\n".join(self.lines) + "\n")
        except Exception:
            # Keep going in memory; say so once rather than on every line.
            if self.location != "(log file stopped accepting writes)":
                self.location = "(log file stopped accepting writes)"
                self.lines.append(traceback.format_exc())
