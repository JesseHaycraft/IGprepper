"""Theme-aware colours for secondary text.

Qt's `palette(mid)` role is nearly invisible against a dark window background,
so hint and warning text is derived from the live palette instead.
"""

from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

HINT_ALPHA = 165

# Practical ceiling for the border control. The geometric limit is far higher
# -- nearly half the width on tall ratios -- but a border that thick is not a
# photograph any more, and allowing it squeezes the useful 2-8% range into the
# first tenth of the slider.
MAX_BORDER_PCT = 15.0


def _window_text():
    app = QApplication.instance()
    palette = app.palette() if app else QPalette()
    return palette.color(QPalette.ColorRole.WindowText)


def is_dark_theme() -> bool:
    app = QApplication.instance()
    palette = app.palette() if app else QPalette()
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def hint_style() -> str:
    c = _window_text()
    return f"color: rgba({c.red()}, {c.green()}, {c.blue()}, {HINT_ALPHA});"


def warning_style() -> str:
    return "color: #e0913a;" if is_dark_theme() else "color: #b86e00;"


def error_style() -> str:
    return "color: #e87070;" if is_dark_theme() else "color: #be3c3c;"
