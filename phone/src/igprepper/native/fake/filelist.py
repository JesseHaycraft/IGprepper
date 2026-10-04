"""A list that only remembers what it was told to show.

For tests: `rows`, `checked`, `tiles`, `note` and `counter` are what would
be on screen, and `press(name)` is a finger on one row.
"""

from __future__ import annotations

from ...thumbs import Thumbnails


class FileList:
    def __init__(self, holder, loop, log, icon, on_press) -> None:
        self.loop, self.log, self.icon, self.on_press = loop, log, icon, on_press
        self.rows: list = []
        self.checked: set[str] = set()
        self.selectable = False
        self.tiles = False
        self.note: str | None = None
        self.counter: str | None = None
        self.shown = 0  # how many times a folder has been put on screen afresh
        self.thumbs = Thumbnails(loop, lambda: None)

    @property
    def thumb_px(self) -> int:
        return 300 if self.tiles else 94

    def show(
        self, rows: list, fetch=None, *, selectable: bool = False, tiles: bool = False
    ) -> None:
        self.rows = list(rows)
        self.selectable, self.tiles = selectable, tiles
        self.shown += 1
        side = self.thumb_px
        self.thumbs.start(None if fetch is None else (lambda key: fetch(key, side)))

    def update(self, rows: list) -> None:
        self.rows = list(rows)

    def seed(self, doc_id: str, picture) -> None:
        self.thumbs.put(doc_id, picture)

    def say(self, text: str | None) -> None:
        self.note = text

    def count(self, text: str | None) -> None:
        self.counter = text

    # --- for tests ------------------------------------------------------------

    def names(self) -> list[str]:
        return [row.name for row in self.rows]

    def press(self, name: str) -> None:
        self.on_press(next(row for row in self.rows if row.name == name))
