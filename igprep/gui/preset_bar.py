"""The preset control, used by both settings panels.

The bar owns the store and the dialogs; the panel owns the values. It asks the
panel for the current values through `values_provider`, and hands back a loaded
preset via `applyRequested`, so neither needs to know how the other works.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox,
    QPushButton, QToolButton, QWidget,
)

from ..core.presets import PresetError, PresetStore

NONE_LABEL = "— none —"
MODIFIED_SUFFIX = "  (modified)"


class PresetBar(QWidget):
    """A named-preset picker with save, update, rename and delete."""

    applyRequested = Signal(object)  # the loaded Framing / OutputSettings

    def __init__(
        self,
        label: str,
        values_provider: Callable[[], object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store: PresetStore | None = None
        self._values_provider = values_provider
        self._loading = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(label))

        self.combo = QComboBox()
        # Cap the size hint: a long preset name would otherwise widen the row
        # past the panel and push the menu button off the edge.
        self.combo.setMinimumContentsLength(10)
        # Qt 6 dropped the plain AdjustToMinimumContentsLength; the WithIcon
        # variant is the remaining way to cap the hint at a fixed length.
        self.combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        # `activated`, not `currentIndexChanged`: the latter stays silent when
        # you pick the item already selected, so re-choosing a preset to
        # discard your edits would do nothing. It also fires only on a
        # deliberate pick, so rebuilding the list never re-applies anything.
        self.combo.activated.connect(self._on_activated)
        layout.addWidget(self.combo, 1)

        self.save_btn = QPushButton("Save...")
        self.save_btn.setToolTip("Save the current settings as a preset")
        self.save_btn.clicked.connect(self._save_as)
        layout.addWidget(self.save_btn)

        self.menu_btn = QToolButton()
        self.menu_btn.setText("⋯")
        self.menu_btn.setFixedWidth(30)
        self.menu_btn.setToolTip("Update, rename or delete this preset")
        self.menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.menu_btn)
        self.update_action = menu.addAction("Update", self._update)
        self.rename_action = menu.addAction("Rename...", self._rename)
        menu.addSeparator()
        self.delete_action = menu.addAction("Delete...", self._delete)
        self.menu_btn.setMenu(menu)
        layout.addWidget(self.menu_btn)

    # --- wiring -----------------------------------------------------------

    def set_store(self, store: PresetStore) -> None:
        self._store = store
        self.refresh()

    def current_name(self) -> str | None:
        return self.combo.currentData()

    def refresh(self, select: str | None = None) -> None:
        """Rebuild the list, optionally selecting a preset by name."""
        self._loading = True
        self.combo.clear()
        self.combo.addItem(NONE_LABEL, None)
        if self._store is not None:
            for name in self._store.names():
                self.combo.addItem(name, name)
        index = self.combo.findData(select) if select else 0
        self.combo.setCurrentIndex(max(0, index))
        self._loading = False
        self.note_values_changed()

    def note_values_changed(self) -> None:
        """Recompute the modified marker. Panels call this whenever they edit.

        Without it the control keeps claiming a preset is applied after you
        have moved a slider away from it.
        """
        name = self.current_name()
        modified = False
        if name is not None and self._store is not None:
            saved = self._store.get(name)
            modified = saved is not None and not _same(
                saved, self._values_provider()
            )
        self._set_modified_marker(modified)
        self.update_action.setEnabled(name is not None and modified)
        self.rename_action.setEnabled(name is not None)
        self.delete_action.setEnabled(name is not None)

    def _set_modified_marker(self, modified: bool) -> None:
        index = self.combo.currentIndex()
        name = self.combo.itemData(index)
        if name is None:
            return
        self.combo.setItemText(index, name + (MODIFIED_SUFFIX if modified else ""))

    # --- actions ----------------------------------------------------------

    def choose(self, name: str | None) -> None:
        """Select a preset and apply it, exactly as picking it would."""
        index = self.combo.findData(name)
        if index < 0:
            return
        self.combo.setCurrentIndex(index)
        self._on_activated(index)

    def _clear_markers(self) -> None:
        """Drop any stale "(modified)" left on an item we are leaving."""
        for i in range(self.combo.count()):
            stored = self.combo.itemData(i)
            if stored is not None:
                self.combo.setItemText(i, stored)

    def _on_activated(self, index: int) -> None:
        if self._loading or self._store is None:
            return
        self._clear_markers()

        name = self.combo.itemData(index)
        if name is None:
            self.note_values_changed()
            return
        values = self._store.get(name)
        if values is None:
            self.refresh()
            return
        self.applyRequested.emit(values)
        self.note_values_changed()

    def _save_as(self) -> None:
        if self._store is None:
            return
        suggested = self.current_name() or ""
        name, ok = QInputDialog.getText(
            self, "Save preset", "Preset name:", text=suggested
        )
        if not ok:
            return
        try:
            if self._store.exists(name) and not self._confirm_overwrite(name):
                return
            stored = self._store.save(name, self._values_provider())
        except PresetError as exc:
            QMessageBox.warning(self, "Save preset", str(exc))
            return
        self.refresh(select=stored)

    def _confirm_overwrite(self, name: str) -> bool:
        answer = QMessageBox.question(
            self, "Save preset",
            f"A preset called “{name.strip()}” already exists.\n"
            "Replace it?",
        )
        return answer == QMessageBox.StandardButton.Yes

    def _update(self) -> None:
        name = self.current_name()
        if name is None or self._store is None:
            return
        self._store.save(name, self._values_provider())
        self.note_values_changed()

    def _rename(self) -> None:
        name = self.current_name()
        if name is None or self._store is None:
            return
        new, ok = QInputDialog.getText(
            self, "Rename preset", "New name:", text=name
        )
        if not ok:
            return
        try:
            stored = self._store.rename(name, new)
        except PresetError as exc:
            QMessageBox.warning(self, "Rename preset", str(exc))
            return
        self.refresh(select=stored)

    def _delete(self) -> None:
        name = self.current_name()
        if name is None or self._store is None:
            return
        answer = QMessageBox.question(
            self, "Delete preset", f"Delete “{name}”?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._store.delete(name)
        self.refresh()


def _same(saved, current) -> bool:
    """Compare a stored preset with live panel values.

    The border percentage is rounded to the spinbox's own one-decimal
    granularity, so a value that round-trips through the control does not read
    as modified purely from float noise.
    """
    if type(saved) is not type(current):
        return False
    left, right = dict(vars(saved)), dict(vars(current))
    for side in (left, right):
        if "border_pct" in side:
            side["border_pct"] = round(float(side["border_pct"]), 1)
    return left == right
