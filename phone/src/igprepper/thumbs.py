"""Fetching small pictures for a list without holding the list up.

A folder can hold thousands of photos, and asking for a thumbnail can mean
a trip over the network. So nothing is fetched until its row is on screen,
only a few are fetched at once, the most recently shown go first, and rows
that were scrolled past before their turn came are forgotten.

A file with no picture is asked about again a few times, further apart each
time. Cloud storage has no thumbnail for a photo it has only just been
given; it does a little later.

A file can also change while its folder is on screen: edited in another app,
or replaced by a newer one of the same name. So each picture is held as being
of one version of its file, and when the file is listed as a different
version the picture is fetched again.

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
        # Which version of its file each thing in `cache` is of.
        self.versions: dict = {}
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
        self.versions.clear()
        self.waiting.clear()
        self.fetching.clear()

    def get(self, key, version=None):
        """The picture for `key` if it is to hand; otherwise None, and it is
        sent for. `on_ready` is called when it, or any other, arrives.

        `version` is anything that changes when the file does. A picture of
        another version is sent for again, and shown only until the new one
        arrives."""
        found = self.cache.get(key)
        outdated = None
        if found is not None:
            self.cache.move_to_end(key)
            # A picture that was supplied is of the file as it is first seen.
            current = self.versions.setdefault(key, version) == version
            if not isinstance(found, _Missing):
                if current:
                    return found
                outdated = found
            elif current and not self._due(found):
                return None
        if self.fetch is not None and key not in self.fetching:
            self.waiting[key] = version
            self.waiting.move_to_end(key)
            while len(self.waiting) > self.backlog:
                self.waiting.popitem(last=False)
            self._send()
        return outdated

    def put(self, key, picture) -> None:
        """Supply a picture that is already to hand, such as one of a file
        this app has just written."""
        self.cache[key] = picture
        self.cache.move_to_end(key)
        self.versions.pop(key, None)
        self._trim()

    def ask_again(self) -> None:
        """Forget which files had no picture, so each is asked about afresh."""
        for key in [k for k, v in self.cache.items() if isinstance(v, _Missing)]:
            del self.cache[key]
            self.versions.pop(key, None)

    def _due(self, missing: _Missing) -> bool:
        if missing.tries > len(RETRY_AFTER):
            return False
        return self.loop.time() - missing.since >= RETRY_AFTER[missing.tries - 1]

    def _send(self) -> None:
        while self.waiting and len(self.fetching) < self.at_once:
            key, version = self.waiting.popitem(last=True)
            self.fetching.add(key)
            self.loop.run_in_executor(
                None, self._fetch, key, version, self.fetch, self.round
            )

    def _fetch(self, key, version, fetch, round_) -> None:
        try:
            found = fetch(key)
        except Exception:
            found = None
        self.loop.call_soon_threadsafe(self._arrived, key, version, found, round_)

    def _arrived(self, key, version, found, round_) -> None:
        if round_ != self.round:
            return  # for a folder no longer on screen
        self.fetching.discard(key)
        before = self.cache.get(key)
        same_file = key in self.versions and self.versions[key] == version
        self.versions[key] = version
        if found is None:
            # Tries are counted for one version of a file: a changed file is
            # a fresh start.
            again = isinstance(before, _Missing) and same_file
            tries = before.tries + 1 if again else 1
            self.cache[key] = _Missing(tries, self.loop.time())
            if tries <= len(RETRY_AFTER):
                # Nothing will ask again unless the list is redrawn.
                self.loop.call_later(RETRY_AFTER[tries - 1] + 0.1, self._nudge, round_)
        else:
            self.cache[key] = found
        self.cache.move_to_end(key)
        self._trim()
        self._send()
        if found is not None or not (before is None or isinstance(before, _Missing)):
            # A file with no picture, that had none before either, looks the
            # same as it did: nothing to redraw.
            self.on_ready()

    def _nudge(self, round_) -> None:
        if round_ == self.round:
            self.on_ready()

    def _trim(self) -> None:
        while len(self.cache) > self.keep:
            key, _ = self.cache.popitem(last=False)
            self.versions.pop(key, None)
