"""What the app says.

The toolkit's labels do not wrap or shorten themselves: text that is too long
simply runs off the edge and takes the rest of the layout with it. So a name
of unknown length that is to go in one is shortened here first.

Nothing here is Android-specific; the desktop test suite runs it.
"""

from __future__ import annotations

ELLIPSIS = "…"


def shorten(text: str, limit: int) -> str:
    """`text`, cut to `limit` characters with an ellipsis if it was longer."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + ELLIPSIS


def selected(count: int) -> str:
    return f"{count} selected"


def local_path(folder_id: str, names: list[str]) -> str:
    """The path of a folder on the phone itself.

    Android identifies such a folder by its path, after the name of the
    storage it is on: "primary:DCIM/Camera".
    """
    volume, colon, rest = folder_id.partition(":")
    if not colon:
        return "/".join(names)
    start = "Internal storage" if volume == "primary" else "SD card"
    return f"{start}/{rest}" if rest else start


def remote_path(storage_app: str, names: list[str]) -> str:
    """The path of a folder in another app's storage.

    Android says nothing of what lies above the folder that was granted, so
    this begins there, after the storage app's name.
    """
    path = "/".join(names)
    return f"{storage_app}: {path}" if storage_app else path


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
