"""Fingers on the preview, pretended.

Nothing listens. A test plays the fingers itself, by calling what the app
gave `listen` with `CHANGED`, `MOVED` and `ENDED`. `frames` is every picture
that was put on the preview the quick way.
"""

from __future__ import annotations

CHANGED, MOVED, ENDED = "changed", "moved", "ended"

# Where the pretend preview is on its pretend screen: centre, and width.
SHOWN_AT = (300.0, 400.0, 600.0)


class Listener:
    def __init__(self, handler, on_error) -> None:
        self.handler, self.on_error = handler, on_error


def listen(view, handler, on_error) -> Listener:
    return Listener(handler, on_error)


def shown_at(view) -> tuple[float, float, float]:
    return SHOWN_AT


class Canvas:
    def __init__(self) -> None:
        self.frames: list = []

    def show(self, view, image) -> None:
        self.frames.append(image)
