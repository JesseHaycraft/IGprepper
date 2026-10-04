"""Fetching small pictures for a list without holding the list up.

A folder can hold thousands of photos, and asking for a thumbnail can mean
a trip over the network. So nothing is fetched until its row is on screen,
only a few are fetched at once, the most recently shown go first, and rows
that were scrolled past before their turn came are forgotten.

Nothing here is Android-specific; the desktop test suite runs it.
"""

from __future__ import annotations

from collections import OrderedDict

_NONE = object()  # asked for, and there turned out to be no picture


class Thumbnails:
    def __init__(
        self, loop, on_ready, *, keep: int = 400, at_once: int = 3, backlog: int = 40
    ) -> None:
        self.loop = loop
        self.on_ready = on_ready
        self.keep, self.at_once, self.backlog = keep, at_once, backlog
        self.fetch = None
        self.cache: OrderedDict = OrderedDict()
        self.waiting: OrderedDict = OrderedDict()
        self.fetching: set = set()
        self.round = 0

    def start(self, fetch) -> None:
        """Begin on a new folder. `fetch(key)` returns a picture or None, and
        may take its time: it is run away from the screen's thread."""
        self.round += 1
        self.fetch = fetch
        self.cache.clear()
        self.waiting.clear()
        self.fetching.clear()

    def get(self, key):
        """The picture for `key` if it is to hand; otherwise None, and it is
        sent for. `on_ready` is called when it, or any other, arrives."""
        if key in self.cache:
            self.cache.move_to_end(key)
            found = self.cache[key]
            return None if found is _NONE else found
        if self.fetch is not None and key not in self.fetching:
            self.waiting[key] = True
            self.waiting.move_to_end(key)
            while len(self.waiting) > self.backlog:
                self.waiting.popitem(last=False)
            self._send()
        return None

    def _send(self) -> None:
        while self.waiting and len(self.fetching) < self.at_once:
            key, _ = self.waiting.popitem(last=True)
            self.fetching.add(key)
            self.loop.run_in_executor(None, self._fetch, key, self.fetch, self.round)

    def _fetch(self, key, fetch, round_) -> None:
        try:
            found = fetch(key)
        except Exception:
            found = None
        self.loop.call_soon_threadsafe(self._arrived, key, found, round_)

    def _arrived(self, key, found, round_) -> None:
        if round_ != self.round:
            return  # for a folder no longer on screen
        self.fetching.discard(key)
        self.cache[key] = _NONE if found is None else found
        while len(self.cache) > self.keep:
            self.cache.popitem(last=False)
        self._send()
        self.on_ready()
