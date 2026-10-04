"""What the app says, and how it fits long names into a narrow screen.

The toolkit's labels do not wrap or shorten themselves: text that is too long
simply runs off the edge and takes the rest of the layout with it. So
anything of unknown length is shortened here first.

Nothing here is Android-specific; the desktop test suite runs it.
"""

from __future__ import annotations

ELLIPSIS = "…"
STEP = " › "  # the mark between folders in a path, as in a file manager


def shorten(text: str, limit: int) -> str:
    """`text`, cut to `limit` characters with an ellipsis if it was longer."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + ELLIPSIS


def trail(names: list[str], limit: int) -> str:
    """A path of folder names, keeping the end when it is too long to show.

    The end is the part that says where you are; the start is the same every
    time.
    """
    whole = STEP.join(names)
    if len(whole) <= limit:
        return whole
    kept: list[str] = []
    for name in reversed(names):
        candidate = STEP.join([ELLIPSIS, name, *kept])
        if len(candidate) > limit and kept:
            break
        kept.insert(0, name)
    return shorten(STEP.join([ELLIPSIS, *kept]), limit)


def selected(count: int) -> str:
    return f"{count} selected"


def photos(count: int) -> str:
    return "1 photo" if count == 1 else f"{count} photos"


def saved(count: int, folder: str | None, to_gallery: bool) -> str:
    """What to say once photos have been saved."""
    places = []
    if folder is not None:
        places.append(f"“{shorten(folder, 24)}”")
    if to_gallery:
        places.append("the gallery")
    return f"Saved {photos(count)} to {' and '.join(places)}"


def hint(changed: bool, forced_to_fill: bool, angle: str) -> str:
    """The line under the preview: what can be done, or how to undo it."""
    if not changed:
        return "Drag to move · Pinch to zoom"
    if forced_to_fill:
        return f"Moved photos fill the frame · Tap {angle} to reset"
    return f"Tap {angle} to reset"
