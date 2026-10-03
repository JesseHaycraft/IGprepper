"""Making sense of fingers on the photo.

Android reports where each finger is, over and over. This turns that stream
into steps: the point being held went from here to there, and two fingers
ended this much further apart than they began. One finger drags; two drag
and pinch at once, about the point midway between them.

Nothing here is Android-specific; the desktop test suite runs it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Point = tuple[float, float]

# Two fingers closer together than this are too close to measure a pinch
# from: a hair's movement would read as an enormous change.
MIN_APART = 24.0


@dataclass(frozen=True)
class Step:
    before: Point
    after: Point
    spread: float = 1.0


@dataclass(frozen=True)
class _Hold:
    middle: Point
    apart: float | None  # None with one finger down


def _hold(points: list[Point]) -> _Hold | None:
    if not points:
        return None
    if len(points) == 1:
        return _Hold(points[0], None)
    (ax, ay), (bx, by) = points[:2]
    return _Hold(((ax + bx) / 2, (ay + by) / 2), math.hypot(bx - ax, by - ay))


class Tracker:
    def __init__(self) -> None:
        self._last: _Hold | None = None

    def changed(self, points: list[Point]) -> None:
        """A finger went down or came up. Measure from here, so the photo
        does not jump to wherever the new midpoint happens to be."""
        self._last = _hold(points)

    def moved(self, points: list[Point]) -> Step | None:
        now = _hold(points)
        last, self._last = self._last, now
        if last is None or now is None:
            return None
        if (last.apart is None) != (now.apart is None):
            return None  # the number of fingers changed without notice
        spread = 1.0
        if last.apart is not None and min(last.apart, now.apart) >= MIN_APART:
            spread = now.apart / last.apart
        if now.middle == last.middle and spread == 1.0:
            return None
        return Step(last.middle, now.middle, spread)

    def ended(self) -> None:
        self._last = None
