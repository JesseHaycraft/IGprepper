"""Remembering the two folders between one launch and the next.

Each side of the main screen, input and output, has a folder it was granted
and a path down from there to wherever it was last looking. Both are kept in
a small file in the app's own private storage, which no other app can read.

Nothing here is Android-specific; the desktop test suite runs it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from igprep.core.jsonfile import write_json

SIDES = ("input", "output")


@dataclass
class Place:
    tree: str | None = None  # the granted folder's address, as text
    trail: list[tuple[str, str]] = field(default_factory=list)  # (id, name), top down


def load(path: Path) -> dict[str, Place]:
    """What was saved, or empty places if nothing usable was.

    A damaged file is treated as no file: the cost is choosing the folders
    again, which is better than refusing to start.
    """
    found = {side: Place() for side in SIDES}
    try:
        stored = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return found
    if not isinstance(stored, dict):
        return found
    for side in SIDES:
        entry = stored.get(side)
        if not isinstance(entry, dict) or not isinstance(entry.get("tree"), str):
            continue
        trail = []
        for step in entry.get("trail") or []:
            if (
                isinstance(step, (list, tuple)) and len(step) == 2
                and all(isinstance(part, str) for part in step)
            ):
                trail.append((step[0], step[1]))
            else:
                trail = []
                break
        found[side] = Place(entry["tree"], trail)
    return found


def save(path: Path, places: dict[str, Place]) -> None:
    stored = {
        side: {"tree": place.tree, "trail": [list(step) for step in place.trail]}
        for side, place in places.items()
        if place.tree is not None
    }
    write_json(path, stored)
