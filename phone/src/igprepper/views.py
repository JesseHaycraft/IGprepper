"""Remembering how the main screen was left.

Two things: which folders were being looked at as tiles rather than as a
list, and where the divider between the two halves of the screen was. Both
are kept in a small file in the app's own private storage.

Nothing here is Android-specific; the desktop test suite runs it.
"""

from __future__ import annotations

import json
from pathlib import Path

# A list is what a folder gets until told otherwise, so only the folders
# shown as tiles need writing down. Old ones are let go eventually.
MOST_FOLDERS = 500
DEFAULT_SPLIT = 0.5


class Views:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.tiled: list[str] = []
        self.split = DEFAULT_SPLIT
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(stored, dict):
            return
        tiled = stored.get("tiled")
        if isinstance(tiled, list) and all(isinstance(key, str) for key in tiled):
            self.tiled = tiled[-MOST_FOLDERS:]
        split = stored.get("split")
        if isinstance(split, (int, float)) and not isinstance(split, bool):
            if 0 < split < 1:
                self.split = float(split)

    def is_tiled(self, folder: str) -> bool:
        return folder in self.tiled

    def set_tiled(self, folder: str, tiled: bool) -> None:
        self.tiled = [key for key in self.tiled if key != folder]
        if tiled:
            self.tiled.append(folder)
            self.tiled = self.tiled[-MOST_FOLDERS:]
        self.save()

    def set_split(self, split: float) -> None:
        """The upper list's share of the room the two lists have between them."""
        self.split = min(0.99, max(0.01, float(split)))
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Written beside and swapped in, so a crash cannot leave half a file.
        partial = self.path.with_suffix(".part")
        partial.write_text(
            json.dumps({"tiled": self.tiled, "split": self.split}), encoding="utf-8"
        )
        partial.replace(self.path)


def divide(upper: float, lower: float, moved: float, least: float) -> float | None:
    """Where a drag of the divider leaves it.

    `upper` and `lower` are the heights of the two lists when the drag began,
    and `moved` how far down the finger has gone since. Returns the upper
    list's new height, never letting either list shrink below `least`: there
    must always be enough of each left to see it and drag it back. None if
    the screen is too small to move the divider at all.
    """
    total = upper + lower
    if total < 2 * least:
        return None
    return min(total - least, max(least, upper + moved))
