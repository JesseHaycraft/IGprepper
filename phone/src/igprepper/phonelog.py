"""The log file.

There is no cable to the phone, so this file is the only way to see what
happened on it. It goes in Download/IGprepper/, where the Files app can reach
it, one file per launch. Every line is appended and closed straight away, so
a crash still leaves everything up to that point.

Nothing here lists what is already in anyone's storage: it records only what
the app itself did.
"""

from __future__ import annotations

import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

FOLDER = "IGprepper"
# MediaStore's Downloads collection arrived in Android 10.
MIN_SDK_FOR_DOWNLOADS = 29


class PhoneLog:
    """Timestamped lines, kept in memory and mirrored to a file."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.listeners: list = []
        self.location = "(no file)"
        self._resolver = None
        self._uri = None
        self._path: Path | None = None
        self._append_works = True

        name = f"igprepper-log-{datetime.now():%Y%m%d-%H%M%S}.txt"
        try:
            self._open_on_android(name)
        except ImportError:
            # Not on a phone: a plain file keeps this module testable.
            self._path = Path(tempfile.gettempdir()) / name
            self.location = str(self._path)
        except Exception:
            # Still usable: lines stay in memory and on screen.
            self.location = "(log file could not be created)"
            self.write("Could not create the log file:")
            self.write(traceback.format_exc())

    def _open_on_android(self, name: str) -> None:
        from android.content import ContentValues
        from android.os import Build
        from java import jclass
        from org.beeware.android import MainActivity

        if Build.VERSION.SDK_INT < MIN_SDK_FOR_DOWNLOADS:
            raise RuntimeError(
                f"Android API {Build.VERSION.SDK_INT} is older than "
                f"{MIN_SDK_FOR_DOWNLOADS}, which the Downloads folder needs"
            )

        downloads = jclass("android.provider.MediaStore$Downloads")
        values = ContentValues()
        values.put("_display_name", name)
        values.put("mime_type", "text/plain")
        values.put("relative_path", f"Download/{FOLDER}")

        resolver = MainActivity.singletonThis.getContentResolver()
        uri = resolver.insert(downloads.EXTERNAL_CONTENT_URI, values)
        if uri is None:
            raise RuntimeError("Android refused to create the log file")
        self._resolver, self._uri = resolver, uri
        self.location = f"Download/{FOLDER}/{name}"

    def prune(self, keep: int) -> int:
        """Delete this app's older log files, leaving the newest `keep`.

        A log is written on every launch, and nobody wants a hundred of them
        in their Downloads. Returns how many were removed.
        """
        if self._resolver is None:
            return 0
        from java import jarray, jclass
        from java.lang import String

        downloads = jclass("android.provider.MediaStore$Downloads")
        ContentUris = jclass("android.content.ContentUris")
        # Android shows an app only the downloads it made itself, and the
        # name and folder are checked as well: nothing else can match.
        cursor = self._resolver.query(
            downloads.EXTERNAL_CONTENT_URI,
            jarray(String)(["_id", "_display_name"]),
            "relative_path LIKE ? AND _display_name LIKE ?",
            jarray(String)([f"Download/{FOLDER}/%", "igprepper-log-%.txt"]),
            "_display_name DESC",
        )
        if cursor is None:
            return 0
        try:
            found = []
            while cursor.moveToNext():
                found.append(cursor.getLong(0))
        finally:
            cursor.close()

        removed = 0
        for row in found[keep:]:
            uri = ContentUris.withAppendedId(downloads.EXTERNAL_CONTENT_URI, row)
            removed += self._resolver.delete(uri, None, None)
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
            for listener in self.listeners:
                try:
                    listener(line)
                except Exception:
                    pass  # a broken display must never stop the log

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
        try:
            if self._uri is not None:
                self._store_on_android(text)
            elif self._path is not None:
                with open(self._path, "a", encoding="utf-8") as fh:
                    fh.write(text)
        except Exception:
            # Keep going in memory; say so once rather than on every line.
            if self.location != "(log file stopped accepting writes)":
                self.location = "(log file stopped accepting writes)"
                self.lines.append(traceback.format_exc())

    def _store_on_android(self, text: str) -> None:
        if self._append_works:
            try:
                self._write_stream("wa", text)
                return
            except Exception:
                # Some storage back ends reject append mode; rewrite instead.
                self._append_works = False
        self._write_stream("wt", "\n".join(self.lines) + "\n")

    def _write_stream(self, mode: str, text: str) -> None:
        stream = self._resolver.openOutputStream(self._uri, mode)
        try:
            stream.write(text.encode("utf-8"))
            stream.flush()
        finally:
            stream.close()
