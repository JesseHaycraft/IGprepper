"""Things the window must not let happen, or must get exactly right."""

import pytest
from PIL import Image
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from igprep.core.pipeline import Job
from igprep.core.settings import Framing, Settings
from igprep.gui.queue import COL_OUTPUT, COL_STATUS
from igprep.gui.worker import ProcessWorker


def _drop(widget, paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    event = QDropEvent(
        QPointF(5, 5), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    widget.dropEvent(event)


def _ratio(window, key):
    window.framing.ratio.setCurrentIndex(window.framing.ratio.findData(key))


# --- dropping photos ----------------------------------------------------------

def test_photos_dropped_on_the_list_are_framed_as_the_panel_shows(window, photos):
    """Not as whatever was edited last, which is what the list used to do."""
    first = photos(1)
    window.queue.add_paths(first)
    window.queue.selectRow(0)
    _ratio(window, "1:1")          # edits the first photo: the "last edited" framing
    window.queue.clearSelection()
    window.framing.load(Framing(ratio="4:5", border_pct=6.0), 1080)

    other = first[0].with_name("dropped.jpg")
    Image.new("RGB", (800, 600), (10, 20, 30)).save(other)
    _drop(window.queue, [other])

    dropped = window.queue.jobs()[-1]
    assert dropped.source == other
    assert (dropped.framing.ratio, dropped.framing.border_pct) == ("4:5", 6.0)
    assert "Added 1 photo" in window.statusBar().currentMessage()


def test_a_drop_anywhere_else_behaves_the_same(window, photos):
    window.framing.load(Framing(ratio="9:16"), 1080)
    _drop(window, photos(1))
    assert window.queue.jobs()[0].framing.ratio == "9:16"
    assert window.queue.selected_rows() == [0]


# --- while a run is in progress --------------------------------------------------

class _Running:
    cancelled = False

    def isRunning(self):  # noqa: N802
        return True


def test_nothing_that_would_change_the_run_can_be_touched_during_it(window, photos):
    window.queue.add_paths(photos(2))
    window.worker = _Running()
    window._update_enabled()
    assert not window.framing.isEnabled()
    assert not window.batch.isEnabled()
    assert not window.add_btn.isEnabled()
    assert not window.process_btn.isEnabled()

    before = len(window.queue.jobs())
    extra = photos(1)[0].with_name("late.jpg")
    Image.new("RGB", (640, 480), (1, 2, 3)).save(extra)
    _drop(window.queue, [extra])
    window._add([extra])
    assert len(window.queue.jobs()) == before
    assert "finish" in window.statusBar().currentMessage()

    window.worker = None
    window._update_enabled()
    assert window.framing.isEnabled() and window.batch.isEnabled()
    assert window.add_btn.isEnabled()


def test_a_real_run_switches_the_controls_off_and_back_on(window, photos, tmp_path):
    window.queue.add_paths(photos(2))
    window.batch.dest_folder_radio.setChecked(True)
    window.batch.dest_edit.setText(str(tmp_path / "out"))
    window._process()
    assert not window.framing.isEnabled() and not window.batch.isEnabled()
    window.worker.wait(30000)
    QApplication.processEvents()
    assert window.framing.isEnabled() and window.batch.isEnabled()


# --- progress ---------------------------------------------------------------------

def test_each_photo_is_announced_before_it_is_processed(photos, qapp):
    paths = photos(3)
    events = []
    worker = ProcessWorker([Job(p) for p in paths], Settings())
    worker.starting.connect(lambda n, total, name: events.append(("start", n, name)))
    worker.item_done.connect(lambda row, result: events.append(("done", row + 1)))
    worker.progress.connect(lambda done, total, name: events.append(("bar", done)))
    worker.run()  # in this thread, so the order is exactly what was emitted

    assert events[0] == ("start", 1, paths[0].name)
    assert [e[0] for e in events] == ["start", "done", "bar"] * 3
    assert [e[1] for e in events if e[0] == "start"] == [1, 2, 3]


def test_the_status_line_names_the_photo_being_worked_on(window):
    window._on_starting(2, 5, "b.jpg")
    assert window.statusBar().currentMessage() == "Processing 2 of 5: b.jpg"
    window.progress.setRange(0, 5)
    window._on_progress(1, 5, "a.jpg")
    assert window.progress.value() == 1
    assert window.statusBar().currentMessage() == "Processing 2 of 5: b.jpg"


# --- an unusable filename template --------------------------------------------------

def test_the_list_keeps_up_while_the_template_cannot_be_used(window, photos):
    window.queue.add_paths(photos(1, w=1200, h=900))
    assert window.queue.item(0, COL_OUTPUT).text().endswith(".jpg")

    window.batch.template.setText("{nonsense}")
    assert window.queue.item(0, COL_OUTPUT).text() == "-"
    assert window.queue.item(0, COL_OUTPUT).toolTip()
    assert not window.process_btn.isEnabled()
    assert window.queue.item(0, COL_STATUS).text() == ""

    # Still following the other settings: at 1440 wide this photo is too small.
    window.batch.width.setCurrentIndex(window.batch.width.findData(1440))
    assert window.queue._settings.output.output_width == 1440
    assert window.queue.item(0, COL_STATUS).text() == "Will enlarge"

    window.batch.template.setText("{name}_ig")
    assert window.queue.item(0, COL_OUTPUT).text().endswith("_ig.jpg")
    assert window.process_btn.isEnabled()


# --- the grid overlay ----------------------------------------------------------------

def _render(widget, size=(420, 420)):
    widget.resize(*size)
    QApplication.processEvents()
    pixmap = QPixmap(*size)
    pixmap.fill(Qt.GlobalColor.white)
    painter = QPainter(pixmap)
    try:
        widget.render(painter, QPoint(0, 0))
    finally:
        painter.end()
    return pixmap.toImage()


@pytest.mark.parametrize("ratio,across", [("1:1", True), ("9:16", False)])
def test_the_dimmed_bands_reach_the_edge_and_match_each_other(
    window, tmp_path, ratio, across
):
    """Each pair of bands is the same width, and the far one runs to the last
    pixel of the picture. It used to start a pixel early and stop a pixel
    short."""
    path = tmp_path / "white.jpg"
    Image.new("RGB", (2000, 2000), (255, 255, 255)).save(path)
    window.queue.add_paths([path])
    window.queue.selectRow(0)
    _ratio(window, ratio)
    window._render_preview()

    window.preview.set_show_grid(False)
    plain = _render(window.preview)
    window.preview.set_show_grid(True)
    marked = _render(window.preview)

    # Along a line through the middle of the picture, which of its pixels
    # the overlay darkened: a run at each end.
    where = window.preview._target_rect()
    if across:
        picture = list(range(where.x(), where.x() + where.width()))
        fixed = where.y() + where.height() // 2
    else:
        picture = list(range(where.y(), where.y() + where.height()))
        fixed = where.x() + where.width() // 2

    def light(image, n):
        point = (n, fixed) if across else (fixed, n)
        return image.pixelColor(*point).lightness()

    assert all(light(plain, n) == 255 for n in picture), "expected a white picture"
    dimmed = {n for n in picture if light(marked, n) < 200}
    assert dimmed, "the overlay dimmed nothing"

    first, last = picture[0], picture[-1]
    assert first in dimmed and last in dimmed, "a band stops short of the edge"
    near = next(n for n in picture if n not in dimmed) - first
    far = last - next(n for n in reversed(picture) if n not in dimmed)
    # An odd pixel to share between two bands cannot be shared evenly.
    assert abs(near - far) <= 1, f"bands of {near} and {far} pixels"
