"""The app's colours, in one place.

It is always dark: one accent for the main action on each screen and for
what is selected, two greys for text, and a few surfaces.

Nothing here is Android-specific; the desktop test suite runs it.
"""

from __future__ import annotations

ACCENT = "#8AB4F8"
ON_ACCENT = "#0B1B33"  # text and icons drawn on the accent

TEXT = "#E8EAED"
DIM = "#9AA0A6"    # captions, hints, the path beside a heading
FAINT = "#7D8388"  # what cannot be used: other files, unchecked marks

PANEL = "#1D1E21"        # behind a list
TILE = "#2A2C30"         # behind a tile's picture
CHECKED_ROW = "#263347"  # a checked row of a list
MENU = "#2E3035"         # an opened drop-down menu
GRIP = "#80868B"         # the divider's handle
SCRIM = "#99000000"      # the disc behind a mark that sits on a photo

# Android draws a switched-off button almost exactly like a working one, so
# each kind of button, and "off", is given colours of its own.
BUTTON_LOOKS = {
    "primary": {"color": ON_ACCENT, "background_color": ACCENT},
    "plain": {"color": "#FFFFFF", "background_color": "#3C4043"},
    "off": {"color": "#6F7378", "background_color": "#232427"},
}
