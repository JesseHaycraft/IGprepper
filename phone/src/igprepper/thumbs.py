"""Fetching small pictures for a list without holding the list up.

A folder can hold thousands of photos, and asking for a thumbnail can mean
a trip over the network. So nothing is fetched until its row is on screen,
only a few are fetched at once, the most recently shown go first, and rows
that were scrolled past before their turn came are forgotten.

A file with no picture is asked about again a few times, further apart each
time. Cloud storage has no thumbnail for a photo it has only just been
given; it does a little later.

Nothing here is Android-specific; the desktop test suite runs it.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

# Seconds to wait before asking again for a picture that was not there, for
# the first, second and third time of asking. After that it is left alone.
RETRY_AFTER = (4.0, 15.0, 60.0)


@dataclass
class _Missing:
    """Asked for, and there turned out to be no picture."""

    tries: int
    since: float


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

    def start(self, fetch, keep: int | None = None) -> None:
        """Begin on a new folder. `fetch(key)` returns a picture or None, and
        may take its time: it is run away from the screen's thread."""
        self.round += 1
        self.fetch = fetch
        if keep is not None:
            self.keep = keep
        self.cache.clear()
        self.waiting.clear()
        self.fetching.clear()

    def get(self, key):
        """The picture for `key` if it is to hand; otherwise None, and it is
        sent for. `on_ready` is called when it, or any other, arrives."""
        found = self.cache.get(key)
        if found is not None:
            self.cache.move_to_end(key)
            if not isinstance(found, _Missing):
                return found
            if not self._due(found):
                return None
        if self.fetch is not None and key not in self.fetching:
            self.waiting[key] = True
            self.waiting.move_to_end(key)
            while len(self.waiting) > self.backlog:
                self.waiting.popitem(last=False)
            self._send()
        return None

    def put(self, key, picture) -> None:
        """Supply a picture that is already to hand, such as one of a file
        this app has just written."""
        self.cache[key] = picture
        self.cache.move_to_end(key)
        self._trim()

    def ask_again(self) -> None:
        """Forget which files had no picture, so each is asked about afresh."""
        for key in [k for k, v in self.cache.items() if isinstance(v, _Missing)]:
            del self.cache[key]

    def _due(self, missing: _Missing) -> bool:
        if missing.tries > len(RETRY_AFTER):
            return False
        return self.loop.time() - missing.since >= RETRY_AFTER[missing.tries - 1]

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
        if found is None:
            before = self.cache.get(key)
            tries = before.tries + 1 if isinstance(before, _Missing) else 1
            self.cache[key] = _Missing(tries, self.loop.time())
            if tries <= len(RETRY_AFTER):
                # Nothing will ask again unless the list is redrawn.
                self.loop.call_later(RETRY_AFTER[tries - 1] + 0.1, self._nudge, round_)
        else:
            self.cache[key] = found
        self.cache.move_to_end(key)
        self._trim()
        self._send()
        self.on_ready()

    def _nudge(self, round_) -> None:
        if round_ == self.round:
            self.on_ready()

    def _trim(self) -> None:
        while len(self.cache) > self.keep:
            self.cache.popitem(last=False)
