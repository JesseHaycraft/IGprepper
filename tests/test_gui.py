"""Headless GUI tests.

These run against Qt's offscreen platform, so they exercise real widgets,
signals and painting without needing a display.
"""

import os

import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from igprep.core import naming  # noqa: E402
from igprep.core.settings import Framing, OutputSettings, Settings  # noqa: E402
from igprep.gui.main import MainWindow  # noqa: E402
from igprep.gui.preview import ProxyCache, render_preview  # noqa: E402
from igprep.gui.queue import COL_FRAMING, COL_OUTPUT, COL_STATUS  # noqa: E402
from igprep.gui.style import MAX_BORDER_PCT  # noqa: E402


# --- the list is selection only -------------------------------------------

def test_the_list_has_no_editable_controls(window, photos):
    """Framing is changed on the right, never in the list."""
    window.queue.add_paths(photos(2))
    for row in range(window.queue.rowCount()):
        for col in range(window.queue.columnCount()):
            assert window.queue.cellWidget(row, col) is None
            item = window.queue.item(row, col)
            assert not (item.flags() & Qt.ItemFlag.ItemIsEditable)


def test_dropping_photos_populates_the_list(window, photos):
    assert window.queue.add_paths(photos(3)) == 3
    assert window.queue.rowCount() == 3


def test_duplicates_are_ignored(window, photos):
    paths = photos(2)
    window.queue.add_paths(paths)
    assert window.queue.add_paths(paths) == 0
    assert window.queue.rowCount() == 2


def test_list_reports_each_photo_framing_read_only(window, photos):
    window.queue.add_paths(photos(1))
    text = window.queue.item(0, COL_FRAMING).text()
    assert "3:4" in text and "fit" in text and "4%" in text


def test_list_shows_the_resolved_output_name(window, photos):
    window.queue.add_paths(photos(1))
    assert window.queue.item(0, COL_OUTPUT).text() == "shot_0_ig.jpg"


def test_list_flags_photos_that_would_be_enlarged(window, photos):
    window.queue.add_paths(photos(1, w=300, h=200))
    assert "enlarge" in window.queue.item(0, COL_STATUS).text().lower()


def test_remove_and_clear(window, photos):
    window.queue.add_paths(photos(3))
    window.queue.selectRow(1)
    window.queue.remove_selected()
    assert window.queue.rowCount() == 2
    window.queue.clear_all()
    assert window.queue.is_empty()


# --- framing is per photo --------------------------------------------------

def test_framing_applies_to_the_selection_only(window, photos):
    window.queue.add_paths(photos(3))
    window.queue.selectRow(1)
    window.framing.ratio.setCurrentIndex(window.framing.ratio.findData("1:1"))

    jobs = window.queue.jobs()
    assert jobs[1].framing.ratio == "1:1"
    assert jobs[0].framing.ratio == "3:4"
    assert jobs[2].framing.ratio == "3:4"


def test_framing_applies_to_every_selected_photo(window, photos):
    window.queue.add_paths(photos(3))
    window.queue.selectAll()
    window.framing.border_spin.setValue(8.0)
    assert all(j.framing.border_pct == 8.0 for j in window.queue.jobs())


def test_selecting_a_photo_loads_its_framing(window, photos):
    window.queue.add_paths(photos(2))
    window.queue.jobs()[1].framing = Framing(
        ratio="1.91:1", mode="crop", border_pct=9.0
    )
    window.queue.selectRow(1)
    assert window.framing.ratio.currentData() == "1.91:1"
    assert window.framing.mode.currentData() == "crop"
    assert window.framing.border_spin.value() == pytest.approx(9.0)


def test_loading_a_photo_framing_does_not_write_it_back(window, photos):
    """Selecting must not stamp the panel's old values onto the new photo."""
    window.queue.add_paths(photos(2))
    window.queue.jobs()[0].framing = Framing(ratio="1:1")
    window.queue.jobs()[1].framing = Framing(ratio="4:5")
    window.queue.selectRow(0)
    window.queue.selectRow(1)
    assert window.queue.jobs()[0].framing.ratio == "1:1"
    assert window.queue.jobs()[1].framing.ratio == "4:5"


def test_apply_to_all_copies_the_current_framing(window, photos):
    window.queue.add_paths(photos(3))
    window.queue.selectRow(0)
    window.framing.ratio.setCurrentIndex(window.framing.ratio.findData("4:5"))
    window.framing.mode.setCurrentIndex(window.framing.mode.findData("crop"))
    window.framing.apply_all_btn.click()

    assert all(
        j.framing.ratio == "4:5" and j.framing.mode == "crop"
        for j in window.queue.jobs()
    )


def test_new_photos_inherit_the_current_framing(window, photos, tmp_path):
    window.queue.add_paths(photos(1))
    window.queue.selectRow(0)
    window.framing.ratio.setCurrentIndex(window.framing.ratio.findData("1:1"))

    later = tmp_path / "later.jpg"
    Image.new("RGB", (2000, 2000)).save(later)
    window._add([later])
    assert window.queue.jobs()[-1].framing.ratio == "1:1"


def test_scope_label_names_what_is_being_edited(window, photos):
    assert "photos you add" in window.framing.scope.text()
    window.queue.add_paths(photos(3))
    window.queue.selectRow(0)
    assert "shot_0.jpg" in window.framing.scope.text()
    window.queue.selectAll()
    assert "3 selected" in window.framing.scope.text()


# --- batch settings --------------------------------------------------------

def test_batch_panel_round_trips_settings(window):
    original = Settings(
        framing=Framing(ratio="1:1"),
        output=OutputSettings(
            output_width=1440, quality=88, sharpen=25,
            template=naming.PRESET_CUSTOM, collision="skip",
        ),
        custom_name="iceland",
    )
    window.batch.load(original)
    assert window.batch.to_settings(original) == original


def test_batch_width_reframes_every_photo(window, photos):
    window.queue.add_paths(photos(2))
    window.batch.width.setCurrentIndex(window.batch.width.findData(1440))
    assert window.settings.output.output_width == 1440
    assert "1440" in window.framing.dimensions.text()


def test_border_slider_and_spinbox_stay_in_sync(window):
    window.framing.border_spin.setValue(7.5)
    assert window.framing.border.value() == 75
    window.framing.border.setValue(20)
    assert window.framing.border_spin.value() == pytest.approx(2.0)


def test_border_control_is_capped_for_usability(window):
    """Geometry allows ~49%, which would bury the useful range in the slider."""
    for key in ("3:4", "1:1", "1.91:1"):
        window.framing.ratio.setCurrentIndex(window.framing.ratio.findData(key))
        assert window.framing.border_spin.maximum() == MAX_BORDER_PCT


def test_changing_the_ratio_updates_the_dimension_label(window):
    window.framing.ratio.setCurrentIndex(window.framing.ratio.findData("1:1"))
    assert "1080 x 1080" in window.framing.dimensions.text()
    window.framing.ratio.setCurrentIndex(window.framing.ratio.findData("4:5"))
    assert "1080 x 1350" in window.framing.dimensions.text()


def test_border_hint_reports_the_pixel_width(window):
    window.framing.border_spin.setValue(4.0)
    assert "43 px" in window.framing.border_hint.text()


def test_hint_text_is_not_invisible(window):
    """palette(mid) rendered as near-black on a dark theme."""
    for label in (window.framing.border_hint, window.framing.dimensions,
                  window.preview_info):
        assert "palette(mid)" not in label.styleSheet()
        assert "rgba(" in label.styleSheet()


def test_a_bad_template_disables_processing(window, photos):
    window.queue.add_paths(photos(1))
    assert window.process_btn.isEnabled()
    window.batch.template.setText("{nonsense}")
    assert not window.process_btn.isEnabled()
    window.batch.template.setText(naming.PRESET_SUFFIX)
    assert window.process_btn.isEnabled()


def test_an_empty_destination_folder_disables_processing(window, photos):
    window.queue.add_paths(photos(1))
    window.batch.dest_folder_radio.setChecked(True)
    window.batch.dest_edit.setText("")
    assert not window.process_btn.isEnabled()
    assert "folder" in window.process_btn.toolTip().lower()


def test_processing_is_disabled_with_an_empty_queue(window):
    assert not window.process_btn.isEnabled()


# --- preview --------------------------------------------------------------

def test_preview_renders_at_the_planned_ratio(photos):
    from igprep.core import geometry as g

    proxy = ProxyCache().get(photos(1)[0])
    img = render_preview(
        proxy, ratio=g.ratio_for("4:5"), border_pct=4.0, mode="crop",
        frame_color="#FFFFFF",
    )
    assert abs(img.width / img.height - 0.8) < 0.01
    assert img.getpixel((0, 0)) == (255, 255, 255)


def test_proxy_cache_reuses_the_same_object(photos):
    cache = ProxyCache()
    path = photos(1)[0]
    assert cache.get(path) is cache.get(path)


def test_proxy_is_downscaled_for_speed(photos):
    proxy = ProxyCache().get(photos(1, w=6000, h=4000)[0])
    assert max(proxy.size) <= 1600


def test_selecting_a_row_produces_a_preview(window, photos):
    window.queue.add_paths(photos(2))
    window.queue.selectRow(1)
    window._render_preview()
    assert window.preview._pixmap is not None
    assert "shot_1.jpg" in window.preview_info.text()


def test_preview_caption_reports_both_sizes(window, photos):
    window.queue.add_paths(photos(1, w=3000, h=2000))
    window.queue.selectRow(0)
    window._render_preview()
    text = window.preview_info.text()
    assert "3000 x 2000" in text and "1080 x 1440" in text


def test_preview_follows_the_selected_photo_framing(window, photos):
    window.queue.add_paths(photos(2))
    window.queue.jobs()[1].framing = Framing(ratio="1:1")
    window.queue.selectRow(1)
    window._render_preview()
    pm = window.preview._pixmap
    assert pm.width() == pm.height()


def test_grid_overlay_toggle_reaches_the_preview(window):
    window.grid_toggle.setChecked(False)
    assert window.preview._show_grid is False
    window.grid_toggle.setChecked(True)
    assert window.preview._show_grid is True


def test_an_unreadable_file_does_not_crash_the_preview(window, tmp_path):
    bad = tmp_path / "broken.jpg"
    bad.write_bytes(b"not an image")
    window.queue.add_paths([bad])
    window.queue.selectRow(0)
    window._render_preview()  # must not raise
    assert window.preview._pixmap is None


# --- processing -----------------------------------------------------------

def test_processing_writes_every_photo(window, photos, tmp_path):
    out = tmp_path / "out"
    window.queue.add_paths(photos(3))
    window.batch.dest_folder_radio.setChecked(True)
    window.batch.dest_edit.setText(str(out))

    window._process()
    assert window.worker is not None
    window.worker.wait(30000)
    QApplication.processEvents()

    written = sorted(p.name for p in out.glob("*.jpg"))
    assert written == ["shot_0_ig.jpg", "shot_1_ig.jpg", "shot_2_ig.jpg"]
    for p in out.glob("*.jpg"):
        with Image.open(p) as img:
            assert img.size == (1080, 1440)


def test_processing_honours_per_photo_framing(window, photos, tmp_path):
    out = tmp_path / "out"
    window.queue.add_paths(photos(2))
    window.queue.jobs()[0].framing = Framing(ratio="1:1")
    window.batch.dest_folder_radio.setChecked(True)
    window.batch.dest_edit.setText(str(out))

    window._process()
    window.worker.wait(30000)
    QApplication.processEvents()

    with Image.open(out / "shot_0_ig.jpg") as a:
        assert a.size == (1080, 1080)
    with Image.open(out / "shot_1_ig.jpg") as b:
        assert b.size == (1080, 1440)


def test_settings_survive_a_restart(window, photos, tmp_path):
    window.queue.add_paths(photos(1))
    window.queue.selectRow(0)
    window.framing.ratio.setCurrentIndex(window.framing.ratio.findData("1:1"))
    window.framing.border_spin.setValue(6.0)
    window.batch.sharpen.setValue(15)
    window.batch.custom_name.setText("iceland")
    window.close()

    reopened = MainWindow()
    try:
        assert reopened.settings.framing.ratio == "1:1"
        assert reopened.settings.framing.border_pct == pytest.approx(6.0)
        assert reopened.settings.output.sharpen == 15
        assert reopened.settings.custom_name == "iceland"
    finally:
        reopened.close()


# --- overlay rendering -----------------------------------------------------

def _size_for_render(widget, size=(420, 420)):
    """Resize and let Qt settle.

    Painting immediately after a resize renders against the stale layout, so
    the first render would differ from every later one.
    """
    widget.resize(*size)
    QApplication.processEvents()


def _render_widget(widget, size=(420, 420)):
    """Paint a widget into an image so the overlay can be checked for real."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPainter, QPixmap

    pixmap = QPixmap(*size)
    pixmap.fill(Qt.GlobalColor.white)
    painter = QPainter(pixmap)
    try:
        widget.render(painter, QPoint(0, 0))
    finally:
        painter.end()
    return pixmap.toImage()


@pytest.mark.parametrize(
    "ratio, should_change",
    [("1:1", True), ("4:5", True), ("1.91:1", True), ("9:16", True),
     ("3:4", False)],
)
def test_grid_overlay_paints_only_when_the_grid_crops(
    window, photos, ratio, should_change
):
    """3:4 loses nothing to the grid, so the overlay must draw nothing."""
    window.queue.add_paths(photos(1))
    window.queue.selectRow(0)
    window.framing.ratio.setCurrentIndex(window.framing.ratio.findData(ratio))
    window._render_preview()
    _size_for_render(window.preview)

    window.preview.set_show_grid(False)
    without = _render_widget(window.preview)
    window.preview.set_show_grid(True)
    with_overlay = _render_widget(window.preview)

    assert (without != with_overlay) is should_change


def test_grid_overlay_is_visible_against_a_white_frame(window, tmp_path):
    """A plain white dashed outline would vanish into the frame."""
    path = tmp_path / "pale.jpg"
    Image.new("RGB", (3265, 4366), (250, 250, 250)).save(path)
    window.queue.add_paths([path])
    window.queue.selectRow(0)
    window.framing.ratio.setCurrentIndex(
        window.framing.ratio.findData("1.91:1")
    )
    window._render_preview()
    _size_for_render(window.preview)

    def dark_pixels(image):
        return sum(
            1
            for y in range(image.height())
            for x in range(image.width())
            if image.pixelColor(x, y).lightness() < 120
        )

    window.preview.set_show_grid(False)
    without = dark_pixels(_render_widget(window.preview))
    window.preview.set_show_grid(True)
    with_overlay = dark_pixels(_render_widget(window.preview))

    assert without < 60, "a white photo on a white frame should render pale"
    assert with_overlay > 150, "overlay leaves no visible mark on a white frame"
    assert with_overlay > without * 3


def test_widget_rendering_is_reproducible(window, photos):
    """Underpins the overlay comparisons above."""
    window.queue.add_paths(photos(1))
    window.queue.selectRow(0)
    window._render_preview()
    _size_for_render(window.preview)
    assert _render_widget(window.preview) == _render_widget(window.preview)


def _ancestors(widget):
    chain = []
    while widget is not None:
        chain.append(widget)
        widget = widget.parentWidget()
    return chain


def test_process_button_sits_in_the_batch_column(window):
    """It acts on the batch, so it lives with the list, not across the window.

    If it were back in the root layout its nearest shared ancestor with the
    list would be the central widget.
    """
    list_chain = _ancestors(window.queue)
    shared = [a for a in _ancestors(window.process_btn) if a in list_chain]
    assert shared, "Process button and the list share no ancestor"
    assert shared[0] is not window.centralWidget()
    assert window.framing not in _ancestors(window.process_btn)


def test_process_button_does_not_stretch_when_idle(window, photos):
    """A lone widget in a box layout expands unless something absorbs the slack."""
    window.queue.add_paths(photos(1))
    window.show()
    QApplication.processEvents()
    assert not window.progress.isVisible()
    assert window.process_btn.width() < 260
