"""Preset behaviour through the real widgets.

Fixtures (`window`, `photos`, `dialogs`) come from conftest; `dialogs` stubs
the preset bar's modal prompts so a headless run never blocks.
"""

import os

from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from igprep.gui.main import MainWindow  # noqa: E402


def _pick(bar, name):
    """Choose a preset the way the user would."""
    bar.choose(name)


def _ratio(window, key):
    window.framing.ratio.setCurrentIndex(window.framing.ratio.findData(key))


# --- saving ----------------------------------------------------------------

def test_preset_lists_start_empty(window):
    assert window.presets.framing.names() == []
    assert window.presets.output.names() == []
    assert window.framing.presets.current_name() is None


def test_saving_a_framing_preset(window, dialogs):
    _ratio(window, "1:1")
    dialogs["text"] = "Square"
    window.framing.presets.save_btn.click()

    assert window.presets.framing.names() == ["Square"]
    assert window.framing.presets.current_name() == "Square"
    assert window.presets.framing.get("Square").ratio == "1:1"


def test_saving_does_not_disturb_the_selection(window, photos, dialogs):
    window.queue.add_paths(photos(2))
    window.queue.selectRow(1)
    dialogs["text"] = "Mine"
    window.framing.presets.save_btn.click()
    assert window.queue.selected_rows() == [1]


def test_a_blank_name_is_reported_not_saved(window, dialogs):
    dialogs["text"] = "   "
    window.framing.presets.save_btn.click()
    assert window.presets.framing.names() == []
    assert dialogs["warnings"]


def test_declining_an_overwrite_leaves_the_preset_alone(window, dialogs):
    window.framing.border_spin.setValue(4.0)
    dialogs["text"] = "Mine"
    window.framing.presets.save_btn.click()

    window.framing.border_spin.setValue(11.0)
    dialogs["confirm"] = False
    window.framing.presets.save_btn.click()

    assert window.presets.framing.get("Mine").border_pct == 4.0


# --- applying --------------------------------------------------------------

def test_applying_a_framing_preset_hits_every_selected_photo(
    window, photos, dialogs
):
    window.queue.add_paths(photos(3))
    window.queue.selectRow(0)
    _ratio(window, "1:1")
    dialogs["text"] = "Square"
    window.framing.presets.save_btn.click()

    _ratio(window, "3:4")
    window.queue.selectAll()
    _pick(window.framing.presets, "Square")

    assert all(j.framing.ratio == "1:1" for j in window.queue.jobs())


def test_applying_a_preset_reaches_the_preview(window, photos, dialogs):
    window.queue.add_paths(photos(1))
    window.queue.selectRow(0)
    _ratio(window, "1:1")
    dialogs["text"] = "Square"
    window.framing.presets.save_btn.click()
    _ratio(window, "3:4")
    _pick(window.framing.presets, "Square")

    window._render_preview()
    pixmap = window.preview._pixmap
    assert pixmap.width() == pixmap.height()


def test_applying_with_nothing_queued_sets_what_new_photos_inherit(
    window, dialogs, tmp_path
):
    _ratio(window, "4:5")
    dialogs["text"] = "Feed"
    window.framing.presets.save_btn.click()
    _ratio(window, "3:4")
    _pick(window.framing.presets, "Feed")

    later = tmp_path / "later.jpg"
    Image.new("RGB", (2000, 1500)).save(later)
    window._add([later])
    assert window.queue.jobs()[0].framing.ratio == "4:5"


# --- the modified marker ---------------------------------------------------

def test_modified_marker_appears_and_clears(window, dialogs):
    dialogs["text"] = "Square"
    window.framing.presets.save_btn.click()
    bar = window.framing.presets
    assert "modified" not in bar.combo.currentText()

    window.framing.border_spin.setValue(9.0)
    assert "modified" in bar.combo.currentText()

    bar.update_action.trigger()
    assert "modified" not in bar.combo.currentText()
    assert window.presets.framing.get("Square").border_pct == 9.0


def test_selecting_a_photo_that_matches_clears_modified(
    window, photos, dialogs
):
    """The marker tracks the panel, so it follows the selection for free."""
    window.queue.add_paths(photos(2))
    window.queue.selectRow(0)
    _ratio(window, "1:1")
    dialogs["text"] = "Square"
    window.framing.presets.save_btn.click()
    bar = window.framing.presets

    window.queue.selectRow(1)  # still 3:4, so the panel no longer matches
    assert "modified" in bar.combo.currentText()
    window.queue.selectRow(0)  # back to the photo the preset was applied to
    assert "modified" not in bar.combo.currentText()


def test_update_is_only_offered_when_modified(window, dialogs):
    bar = window.framing.presets
    assert not bar.update_action.isEnabled()
    dialogs["text"] = "Square"
    bar.save_btn.click()
    assert not bar.update_action.isEnabled()
    window.framing.border_spin.setValue(9.0)
    assert bar.update_action.isEnabled()


# --- renaming and deleting -------------------------------------------------

def test_renaming_a_preset(window, dialogs):
    dialogs["text"] = "Old"
    window.framing.presets.save_btn.click()
    dialogs["text"] = "New"
    window.framing.presets.rename_action.trigger()

    assert window.presets.framing.names() == ["New"]
    assert window.framing.presets.current_name() == "New"


def test_renaming_onto_an_existing_name_is_refused(window, dialogs):
    dialogs["text"] = "A"
    window.framing.presets.save_btn.click()
    dialogs["text"] = "B"
    window.framing.presets.save_btn.click()

    _pick(window.framing.presets, "A")
    dialogs["text"] = "B"
    window.framing.presets.rename_action.trigger()

    assert sorted(window.presets.framing.names()) == ["A", "B"]
    assert dialogs["warnings"]


def test_deleting_falls_back_to_none(window, dialogs):
    dialogs["text"] = "Square"
    window.framing.presets.save_btn.click()
    window.framing.presets.delete_action.trigger()

    assert window.presets.framing.names() == []
    assert window.framing.presets.current_name() is None


# --- output presets --------------------------------------------------------

def test_the_two_lists_are_independent(window, dialogs):
    dialogs["text"] = "Shared name"
    window.framing.presets.save_btn.click()
    window.batch.presets.save_btn.click()
    assert window.presets.framing.names() == ["Shared name"]
    assert window.presets.output.names() == ["Shared name"]


def test_applying_an_output_preset(window, dialogs, tmp_path):
    out = tmp_path / "exports"
    out.mkdir()
    window.batch.width.setCurrentIndex(window.batch.width.findData(1440))
    window.batch.quality.setValue(82)
    window.batch.template.setText("{name}_web")
    window.batch.dest_folder_radio.setChecked(True)
    window.batch.dest_edit.setText(str(out))
    dialogs["text"] = "Web"
    window.batch.presets.save_btn.click()

    window.batch.width.setCurrentIndex(window.batch.width.findData(1080))
    window.batch.quality.setValue(95)
    window.batch.template.setText("{name}_ig")
    _pick(window.batch.presets, "Web")

    assert window.settings.output.output_width == 1440
    assert window.settings.output.quality == 82
    assert window.settings.output.template == "{name}_web"
    assert window.settings.output.dest_folder == str(out)


def test_an_output_preset_never_carries_the_custom_name(window, dialogs):
    """It is content for one batch, not reusable configuration."""
    window.batch.custom_name.setText("iceland")
    dialogs["text"] = "Web"
    window.batch.presets.save_btn.click()
    window.batch.custom_name.setText("norway")
    _pick(window.batch.presets, "Web")
    assert window.batch.custom_name.text() == "norway"


def test_an_output_preset_reframes_the_photos(window, photos, dialogs):
    """Width is a batch setting, so an output preset changes every canvas."""
    window.queue.add_paths(photos(1))
    window.batch.width.setCurrentIndex(window.batch.width.findData(1440))
    dialogs["text"] = "Big"
    window.batch.presets.save_btn.click()
    window.batch.width.setCurrentIndex(window.batch.width.findData(1080))
    _pick(window.batch.presets, "Big")

    assert "1440" in window.framing.dimensions.text()


def test_an_output_preset_with_a_vanished_folder_degrades(
    window, photos, dialogs, tmp_path
):
    gone = tmp_path / "gone"
    gone.mkdir()
    window.queue.add_paths(photos(1))
    window.batch.dest_folder_radio.setChecked(True)
    window.batch.dest_edit.setText(str(gone))
    dialogs["text"] = "Moved"
    window.batch.presets.save_btn.click()

    gone.rmdir()
    window.batch.dest_source.setChecked(True)
    _pick(window.batch.presets, "Moved")

    assert window.settings.output.dest_mode == "folder"
    assert window.batch.dest_edit.text() == ""
    assert "no longer exists" in window.statusBar().currentMessage()
    assert not window.process_btn.isEnabled()


# --- persistence -----------------------------------------------------------

def test_presets_survive_a_restart(window, dialogs):
    _ratio(window, "1:1")
    dialogs["text"] = "Square"
    window.framing.presets.save_btn.click()
    window.close()

    reopened = MainWindow()
    try:
        assert reopened.presets.framing.get("Square").ratio == "1:1"
        bar = reopened.framing.presets
        listed = [bar.combo.itemData(i) for i in range(bar.combo.count())]
        assert "Square" in listed
    finally:
        reopened.close()


def test_presets_are_written_immediately(window, dialogs, tmp_path):
    """Not deferred to shutdown -- a crash must not lose a saved preset."""
    dialogs["text"] = "Square"
    window.framing.presets.save_btn.click()
    assert (tmp_path / "presets.json").exists()


def test_repicking_the_same_preset_discards_your_edits(window, dialogs):
    """currentIndexChanged stays silent here, which is why the bar uses
    activated instead."""
    _ratio(window, "1:1")
    dialogs["text"] = "Square"
    window.framing.presets.save_btn.click()

    window.framing.border_spin.setValue(12.0)
    assert "modified" in window.framing.presets.combo.currentText()

    _pick(window.framing.presets, "Square")
    assert window.framing.border_spin.value() == 4.0
    assert "modified" not in window.framing.presets.combo.currentText()


def test_the_combo_is_wired_to_activated(window, dialogs):
    """A real pick goes through the signal, not just the helper."""
    _ratio(window, "1:1")
    dialogs["text"] = "Square"
    bar = window.framing.presets
    bar.save_btn.click()
    _ratio(window, "4:5")

    bar.combo.activated.emit(bar.combo.findData("Square"))
    assert window.framing.ratio.currentData() == "1:1"


def test_rebuilding_the_list_does_not_apply_anything(window, photos, dialogs):
    """refresh() selects programmatically, which must stay inert."""
    window.queue.add_paths(photos(1))
    window.queue.selectRow(0)
    _ratio(window, "1:1")
    dialogs["text"] = "Square"
    window.framing.presets.save_btn.click()

    window.queue.jobs()[0].framing.ratio = "9:16"
    window.framing.presets.refresh(select="Square")
    assert window.queue.jobs()[0].framing.ratio == "9:16"
