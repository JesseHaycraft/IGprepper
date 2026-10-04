"""The app's icons, drawn rather than shipped as files.

Each is laid out on the 24-unit grid Android's own icons use, so they sit and
weigh the same as the ones in other apps. They are drawn large and shrunk,
which is what smooths their edges.

Nothing here is Android-specific; the desktop test suite runs it.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageOps

GRID = 24
OVERSAMPLE = 4
STROKE = 2.0


class _Pen:
    """Draws in grid units onto a mask: white is ink, black is clear."""

    def __init__(self, pixels: int) -> None:
        self.scale = pixels * OVERSAMPLE / GRID
        side = pixels * OVERSAMPLE
        self.mask = Image.new("L", (side, side), 0)
        self.draw = ImageDraw.Draw(self.mask)

    def _at(self, point):
        return point[0] * self.scale, point[1] * self.scale

    def line(self, points, width: float = STROKE, ink: int = 255) -> None:
        """A stroke with rounded ends and corners."""
        w = max(1, round(width * self.scale))
        scaled = [self._at(p) for p in points]
        self.draw.line(scaled, fill=ink, width=w, joint="curve")
        for x, y in scaled:
            self.draw.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=ink)

    def shape(self, points, ink: int = 255) -> None:
        self.draw.polygon([self._at(p) for p in points], fill=ink)

    def dot(self, centre, radius: float, ink: int = 255) -> None:
        (x, y), r = self._at(centre), radius * self.scale
        self.draw.ellipse([x - r, y - r, x + r, y + r], fill=ink)

    def arc(self, centre, radius: float, start: float, end: float) -> None:
        """Part of a circle. Angles run clockwise from three o'clock."""
        (x, y), r = self._at(centre), radius * self.scale
        w = max(1, round(STROKE * self.scale))
        self.draw.arc(
            [x - r - w / 2, y - r - w / 2, x + r + w / 2, y + r + w / 2],
            start, end, fill=255, width=w,
        )


def _folder(pen: _Pen) -> None:
    pen.shape([
        (2, 6), (4, 4), (9.5, 4), (11.5, 6), (20, 6), (22, 8),
        (22, 18), (20, 20), (4, 20), (2, 18),
    ])


def _new_folder(pen: _Pen) -> None:
    _folder(pen)
    # The plus is cut out of the folder, not laid over it.
    pen.line([(15, 10.5), (15, 16.5)], width=1.8, ink=0)
    pen.line([(12, 13.5), (18, 13.5)], width=1.8, ink=0)


def _photo(pen: _Pen) -> None:
    pen.line([(4, 5), (20, 5), (20, 19), (4, 19), (4, 5)])
    pen.shape([(6.5, 16.5), (10.5, 11), (13.2, 14.5), (15, 12.5), (17.8, 16.5)])
    pen.dot((15.5, 8.8), 1.4)


def _up(pen: _Pen) -> None:
    pen.line([(12, 19.5), (12, 5)])
    pen.line([(5.5, 11.5), (12, 5), (18.5, 11.5)])


def _rotate_right(pen: _Pen) -> None:
    # Three quarters of a circle, open at the top right, with the arrowhead
    # at twelve o'clock pointing the way a clockwise turn travels.
    pen.arc((12, 13.5), 6.5, 0, 270)
    pen.shape([(12, 2.8), (12, 11.2), (17, 7)])


def _check(pen: _Pen) -> None:
    pen.line([(4.5, 12.5), (9.5, 17.5), (19.5, 7)], width=2.2)


def _close(pen: _Pen) -> None:
    pen.line([(6, 6), (18, 18)])
    pen.line([(18, 6), (6, 18)])


def _chevron_right(pen: _Pen) -> None:
    pen.line([(9.5, 6), (15.5, 12), (9.5, 18)], width=2.2)


def _file(pen: _Pen) -> None:
    pen.line([(6.5, 3.5), (13.5, 3.5), (17.5, 7.5), (17.5, 20.5), (6.5, 20.5), (6.5, 3.5)])
    pen.line([(13.5, 3.5), (13.5, 7.5), (17.5, 7.5)], width=1.6)


def _circle(pen: _Pen) -> None:
    pen.arc((12, 12), 7.5, 0, 360)


def _checked(pen: _Pen) -> None:
    pen.dot((12, 12), 9.5)
    # The tick is cut out of the disc, not laid over it.
    pen.line([(7.6, 12.4), (10.6, 15.4), (16.4, 9.2)], width=2.0, ink=0)


def _tiles(pen: _Pen) -> None:
    for left, top in ((4, 4), (13.5, 4), (4, 13.5), (13.5, 13.5)):
        pen.shape([
            (left, top), (left + 6.5, top), (left + 6.5, top + 6.5), (left, top + 6.5),
        ])


def _list(pen: _Pen) -> None:
    for y in (6.5, 12, 17.5):
        pen.dot((5, y), 1.3)
        pen.line([(9.5, y), (20, y)])


# name -> (how to draw it, whether to mirror the drawing left to right)
_ICONS = {
    "folder": (_folder, False),
    "new_folder": (_new_folder, False),
    "photo": (_photo, False),
    "up": (_up, False),
    "rotate_right": (_rotate_right, False),
    "rotate_left": (_rotate_right, True),
    "check": (_check, False),
    "close": (_close, False),
    "next": (_chevron_right, False),
    "previous": (_chevron_right, True),
    "file": (_file, False),
    "unchecked": (_circle, False),
    "checked": (_checked, False),
    "tiles": (_tiles, False),
    "list": (_list, False),
}
NAMES = tuple(_ICONS)


def icon(name: str, pixels: int, colour: str = "#FFFFFF") -> Image.Image:
    """One icon, `pixels` square, in one colour on a clear background."""
    draw, mirrored = _ICONS[name]
    pen = _Pen(pixels)
    draw(pen)
    mask = pen.mask.resize((pixels, pixels), Image.Resampling.LANCZOS)
    if mirrored:
        mask = ImageOps.mirror(mask)
    image = Image.new("RGBA", (pixels, pixels), colour)
    image.putalpha(mask)
    return image
