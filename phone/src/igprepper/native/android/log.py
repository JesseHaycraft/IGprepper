"""Where the log file lives on Android.

In Download/IGprepper, through the phone's shared media store, which is the
one place an app can write that the Files app can also reach without any
permission being asked for. One file per launch.

This module only imports on Android.
"""

from __future__ import annotations

from android.content import ContentValues
from java import jarray, jclass
from java.lang import String
from org.beeware.android import MainActivity

ContentUris = jclass("android.content.ContentUris")
Downloads = jclass("android.provider.MediaStore$Downloads")

FOLDER = "IGprepper"


class LogFile:
    def __init__(self, name: str) -> None:
        values = ContentValues()
        values.put("_display_name", name)
        values.put("mime_type", "text/plain")
        values.put("relative_path", f"Download/{FOLDER}")

        self.resolver = MainActivity.singletonThis.getContentResolver()
        self.uri = self.resolver.insert(Downloads.EXTERNAL_CONTENT_URI, values)
        if self.uri is None:
            raise RuntimeError("Android refused to create the log file")
        self.location = f"Download/{FOLDER}/{name}"
        self.appends = True

    def write(self, text: str, everything) -> None:
        """Add `text` to the file. `everything()` gives the whole log so far,
        for storage that will only take a file whole."""
        if self.appends:
            try:
                self._stream("wa", text)
                return
            except Exception:
                # Some storage back ends reject append mode; rewrite instead.
                self.appends = False
        self._stream("wt", everything())

    def _stream(self, mode: str, text: str) -> None:
        stream = self.resolver.openOutputStream(self.uri, mode)
        try:
            stream.write(text.encode("utf-8"))
            stream.flush()
        finally:
            stream.close()

    def prune(self, keep: int, prefix: str) -> int:
        """Delete this app's older logs, whose names begin with `prefix`,
        leaving the newest `keep`. Returns how many went."""
        # Android shows an app only the downloads it made itself, and the
        # name and folder are checked as well: nothing else can match.
        cursor = self.resolver.query(
            Downloads.EXTERNAL_CONTENT_URI,
            jarray(String)(["_id", "_display_name"]),
            "relative_path LIKE ? AND _display_name LIKE ?",
            jarray(String)([f"Download/{FOLDER}/%", f"{prefix}%.txt"]),
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
            uri = ContentUris.withAppendedId(Downloads.EXTERNAL_CONTENT_URI, row)
            removed += self.resolver.delete(uri, None, None)
        return removed
