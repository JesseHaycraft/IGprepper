"""Live preview rendering.

Full-size rendering is far too slow to run on every slider tick, so previews
are drawn from a cached, downscaled, already-colour-converted proxy of each
source at a reduced canvas width. Because all the geometry is proportional,
a preview laid out at 600px wide is a faithful scale model of the 1080px
output.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import (
    QColor, QFontMetrics, QImage, QPainter, QPalette, QPen, QPixmap,
)
from PySide6.QtWidgets import QWidget

from ..core import color, geometry as g

PREVIEW_CANVAS_WIDTH = 600
PROXY_MAX = 1600
CACHE_LIMIT = 24

GRID_CAPTION = "Dashed area = what your profile grid thumbnail shows"
CAPTION_GAP = 8
CAPTION_RESERVE = 28


def load_proxy(path: Path) -> Image.Image:
    """A small, sRGB, correctly-oriented stand-in for a source photo."""
    img = Image.open(path)
    # draft() lets the JPEG decoder skip most of its work by decoding at a
    # reduced DCT scale -- the single biggest win for preview responsiveness.
    img.draft("RGB", (PROXY_MAX, PROXY_MAX))
    img = ImageOps.exif_transpose(img) or img
    img = color.to_srgb(img)
    img.thumbnail((PROXY_MAX, PROXY_MAX), Image.Resampling.LANCZOS)
    return img


class ProxyCache:
    """Small LRU cache of proxies, keyed by path and modification time."""

    def __init__(self, limit: int = CACHE_LIMIT) -> None:
        self._items: OrderedDict[tuple, Image.Image] = OrderedDict()
        self._limit = limit

    def get(self, path: Path) -> Image.Image:
        try:
            key = (str(path), path.stat().st_mtime_ns)
        except OSError:
            key = (str(path), 0)
        if key in self._items:
            self._items.move_to_end(key)
            return self._items[key]
        proxy = load_proxy(path)
        self._items[key] = proxy
        while len(self._items) > self._limit:
            self._items.popitem(last=False)
        return proxy

    def clear(self) -> None:
        self._items.clear()


def render_preview(
    proxy: Image.Image,
    *,
    ratio: g.AspectRatio,
    border_pct: float,
    mode: str,
    frame_color: str,
) -> Image.Image:
    """Compose the proxy into a scale model of the finished canvas."""
    layout = g.plan(
        proxy.size,
        ratio=ratio,
        width=PREVIEW_CANVAS_WIDTH,
        border_pct=border_pct,
        mode=mode,
    )
    img = proxy
    if layout.crop is not None:
        img = img.crop(layout.crop)
    if img.size != layout.scaled:
        img = img.resize(layout.scaled, Image.Resampling.LANCZOS)

    canvas = Image.new("RGB", layout.canvas, frame_color)
    canvas.paste(img, layout.origin)
    return canvas


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode != "RGB":
        img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qimg = QImage(data, img.width, img.height, img.width * 3,
                  QImage.Format.Format_RGB888)
    # copy() detaches from the Python buffer, which is about to be collected.
    return QPixmap.fromImage(qimg.copy())


class PreviewPane(QWidget):
    """Displays the framed preview, with an optional profile-grid overlay."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._show_grid = False
        self._placeholder = "Drop photos here"
        self.setMinimumSize(280, 320)

    def set_preview(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self.update()

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text
        self.update()

    def set_show_grid(self, show: bool) -> None:
        self._show_grid = show
        self.update()

    def _grid_crops(self) -> bool:
        """Whether the profile grid would actually discard any of this canvas.

        False for 3:4, which the grid keeps whole -- there is then nothing to
        draw and no caption to leave room for.
        """
        if self._pixmap is None or not self._show_grid:
            return False
        canvas = (self._pixmap.width(), self._pixmap.height())
        left, top, right, bottom = g.grid_crop_rect(canvas)
        # Compared in canvas coordinates: scaled widget coordinates let float
        # rounding fake a 1px crop on a 3:4 canvas.
        return (right - left, bottom - top) != canvas

    def _target_rect(self) -> QRect:
        """Where the canvas lands inside this widget, preserving its ratio."""
        assert self._pixmap is not None
        pw, ph = self._pixmap.width(), self._pixmap.height()
        reserve = CAPTION_RESERVE if self._grid_crops() else 0
        avail_w, avail_h = self.width() - 24, self.height() - 24 - reserve
        scale = min(avail_w / pw, avail_h / ph)
        w, h = max(1, int(pw * scale)), max(1, int(ph * scale))
        return QRect(
            (self.width() - w) // 2,
            (self.height() - reserve - h) // 2,
            w, h,
        )

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        if self._pixmap is None:
            painter.setPen(QColor(140, 140, 140))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder
            )
            return

        rect = self._target_rect()
        # A hairline keeps a white frame legible against a light background.
        painter.setPen(QPen(QColor(0, 0, 0, 40), 1))
        painter.drawRect(rect.adjusted(-1, -1, 0, 0))
        painter.drawPixmap(rect, self._pixmap)

        if self._grid_crops():
            self._paint_grid_overlay(painter, rect)
            self._paint_grid_caption(painter, rect)

    def _paint_grid_overlay(self, painter: QPainter, rect: QRect) -> None:
        """Dashed guide showing what Instagram's 3:4 thumbnail keeps."""
        assert self._pixmap is not None
        canvas = (self._pixmap.width(), self._pixmap.height())
        left, top, right, bottom = g.grid_crop_rect(canvas)

        sx = rect.width() / canvas[0]
        sy = rect.height() / canvas[1]
        keep = QRect(
            rect.left() + round(left * sx),
            rect.top() + round(top * sy),
            round((right - left) * sx),
            round((bottom - top) * sy),
        )

        # Dim what the grid discards, then outline what it keeps.
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 85))
        for band in (
            QRect(rect.left(), rect.top(), keep.left() - rect.left(), rect.height()),
            QRect(keep.right(), rect.top(), rect.right() - keep.right(), rect.height()),
            QRect(keep.left(), rect.top(), keep.width(), keep.top() - rect.top()),
            QRect(keep.left(), keep.bottom(), keep.width(), rect.bottom() - keep.bottom()),
        ):
            if band.width() > 0 and band.height() > 0:
                painter.drawRect(band)

        # Two-tone marching ants: a dark line under white dashes. A plain white
        # dashed line vanishes against a white frame, which leaves the dimmed
        # bands looking like part of the photo rather than an overlay.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 170), 1, Qt.PenStyle.SolidLine))
        painter.drawRect(keep)
        dashes = QPen(QColor(255, 255, 255, 235), 1, Qt.PenStyle.DashLine)
        dashes.setDashPattern([4, 4])
        painter.setPen(dashes)
        painter.drawRect(keep)
        painter.restore()

    def _paint_grid_caption(self, painter: QPainter, rect: QRect) -> None:
        """Name the overlay, below the canvas rather than on top of the photo.

        Sitting on the image it competed with the photo and could land on a
        light area; below it, it reads as the UI annotation it is.
        """
        painter.save()
        color = self.palette().color(QPalette.ColorRole.WindowText)
        color.setAlpha(190)
        painter.setPen(color)
        metrics = QFontMetrics(painter.font())
        box = QRect(
            rect.left(),
            rect.bottom() + CAPTION_GAP,
            rect.width(),
            metrics.height() + 2,
        )
        painter.drawText(
            box,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            GRID_CAPTION,
        )
        painter.restore()
