"""The two settings panels.

`FramingPanel` (right) edits how the selected photos are composed -- it acts
on a selection, so every control there is per photo.

`BatchPanel` (below the list) edits the run: encoding, destination and
filenames. Those apply to everything in the queue, which is why they sit with
the list rather than opposite it.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
    QSlider, QVBoxLayout, QWidget,
)

from ..core import geometry as g
from ..core import naming
from ..core.presets import PresetStore
from ..core.settings import Framing, OutputSettings, Settings
from .preset_bar import PresetBar
from .style import MAX_BORDER_PCT, error_style, hint_style

BORDER_STEPS = 10  # slider granularity: tenths of a percent


class FramingPanel(QWidget):
    """Per-photo framing, applied to whatever is selected in the list."""

    changed = Signal()
    applyToAll = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loading = False
        self._frame_color = "#FFFFFF"
        self._width = g.DEFAULT_OUTPUT_WIDTH

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.presets = PresetBar("Preset", self.to_framing)
        self.presets.applyRequested.connect(self._apply_preset)
        layout.addWidget(self.presets)

        self.scope = QLabel()
        self.scope.setWordWrap(True)
        self.scope.setStyleSheet(hint_style())
        layout.addWidget(self.scope)

        layout.addWidget(self._build_framing())

        self.apply_all_btn = QPushButton("Apply this framing to all photos")
        self.apply_all_btn.setToolTip(
            "Give every photo in the list the settings shown above"
        )
        self.apply_all_btn.clicked.connect(self.applyToAll)
        layout.addWidget(self.apply_all_btn)
        layout.addStretch(1)

    def _build_framing(self) -> QGroupBox:
        box = QGroupBox("Framing")
        form = QFormLayout(box)

        self.ratio = QComboBox()
        for r in g.RATIOS:
            self.ratio.addItem(f"{r.key}  -  {r.label}", r.key)
            if r.note:
                self.ratio.setItemData(
                    self.ratio.count() - 1, r.note, Qt.ItemDataRole.ToolTipRole
                )
        self.ratio.currentIndexChanged.connect(self._on_ratio_changed)
        form.addRow("Aspect ratio", self.ratio)

        self.mode = QComboBox()
        self.mode.addItem("Fit the whole photo", "fit")
        self.mode.addItem("Crop to fill the frame", "crop")
        self.mode.setToolTip(
            "Fit keeps all of the photo and lets the white mat go uneven.\n"
            "Crop trims it to the target ratio for a uniform border."
        )
        self.mode.currentIndexChanged.connect(self._emit)
        form.addRow("Fit", self.mode)

        self.border = QSlider(Qt.Orientation.Horizontal)
        self.border.setSingleStep(1)
        self.border.setPageStep(5)
        self.border.valueChanged.connect(self._on_border_slider)

        self.border_spin = QDoubleSpinBox()
        self.border_spin.setDecimals(1)
        self.border_spin.setSingleStep(0.5)
        self.border_spin.setSuffix(" %")
        self.border_spin.valueChanged.connect(self._on_border_spin)

        row = QHBoxLayout()
        row.addWidget(self.border, 1)
        row.addWidget(self.border_spin)
        form.addRow("Border", row)

        self.border_hint = QLabel()
        self.border_hint.setStyleSheet(hint_style())
        self.border_hint.setToolTip(
            "Measured against canvas width, so a given percentage is the same "
            "number of pixels at every ratio."
        )
        form.addRow("", self.border_hint)

        self.color_button = QPushButton()
        self.color_button.setFixedHeight(26)
        self.color_button.clicked.connect(self._pick_color)
        form.addRow("Frame colour", self.color_button)

        self.dimensions = QLabel()
        self.dimensions.setStyleSheet(hint_style())
        form.addRow("", self.dimensions)
        return box

    # --- reacting ---------------------------------------------------------

    def _emit(self, *_) -> None:
        if not self._loading:
            self.presets.note_values_changed()
            self.changed.emit()

    def set_preset_store(self, store: PresetStore) -> None:
        self.presets.set_store(store)

    def _apply_preset(self, framing: Framing) -> None:
        """Route a preset through the normal edit path.

        Loading then emitting means the selection, multi-select and
        apply-to-all behaviour need no special case for presets.
        """
        self.load(framing)
        self.changed.emit()

    def _on_ratio_changed(self, *_) -> None:
        self._update_border_range()
        self._update_labels()
        self._emit()

    def _on_border_slider(self, value: int) -> None:
        if self._loading:
            return
        self._loading = True
        self.border_spin.setValue(value / BORDER_STEPS)
        self._loading = False
        self._update_labels()
        self._emit()

    def _on_border_spin(self, value: float) -> None:
        if self._loading:
            return
        self._loading = True
        self.border.setValue(int(round(value * BORDER_STEPS)))
        self._loading = False
        self._update_labels()
        self._emit()

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(
            QColor(self._frame_color), self, "Frame colour"
        )
        if chosen.isValid():
            self._set_frame_color(chosen.name().upper())
            self._emit()

    # --- derived display --------------------------------------------------

    def _set_frame_color(self, hex_color: str) -> None:
        self._frame_color = hex_color
        readable = "#000000" if QColor(hex_color).lightness() > 128 else "#FFFFFF"
        self.color_button.setText(hex_color)
        self.color_button.setStyleSheet(
            f"background-color: {hex_color}; color: {readable};"
        )

    def _current_ratio(self) -> g.AspectRatio:
        return g.ratio_for(self.ratio.currentData() or g.DEFAULT_RATIO)

    def _update_border_range(self) -> None:
        """Capped for usability, and again by geometry on very wide ratios."""
        cap = min(
            MAX_BORDER_PCT, g.max_border_pct(self._current_ratio(), self._width)
        )
        was_loading = self._loading
        self._loading = True
        self.border.setRange(0, int(cap * BORDER_STEPS))
        self.border_spin.setRange(0.0, cap)
        self._loading = was_loading

    def _update_labels(self) -> None:
        canvas = g.canvas_size(self._current_ratio(), self._width)
        border = g.border_px(canvas[0], self.border_spin.value())
        self.dimensions.setText(f"Output: {canvas[0]} x {canvas[1]} px")
        self.border_hint.setText(f"{border} px on every side")

    def set_scope(self, text: str) -> None:
        self.scope.setText(text)

    def set_width(self, width: int) -> None:
        """The batch output width changes what the framing resolves to."""
        self._width = width if width in g.OUTPUT_WIDTHS else g.DEFAULT_OUTPUT_WIDTH
        self._update_border_range()
        self._update_labels()

    # --- round trip -------------------------------------------------------

    def load(self, framing: Framing, width: int | None = None) -> None:
        self._loading = True
        if width is not None:
            self._width = (
                width if width in g.OUTPUT_WIDTHS else g.DEFAULT_OUTPUT_WIDTH
            )
        self.ratio.setCurrentIndex(max(0, self.ratio.findData(framing.ratio)))
        self.mode.setCurrentIndex(max(0, self.mode.findData(framing.mode)))
        self._update_border_range()
        self.border_spin.setValue(framing.border_pct)
        self.border.setValue(int(round(framing.border_pct * BORDER_STEPS)))
        self._set_frame_color(framing.frame_color)
        self._loading = False
        self._update_labels()
        self.presets.note_values_changed()

    def to_framing(self) -> Framing:
        return Framing(
            ratio=self.ratio.currentData() or g.DEFAULT_RATIO,
            mode=self.mode.currentData() or "fit",
            border_pct=self.border_spin.value(),
            frame_color=self._frame_color,
        )


class BatchPanel(QWidget):
    """Encoding, destination and filenames -- the whole run, not one photo."""

    changed = Signal()
    warning = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._loading = False

        # Stacked, not side by side: this sits in the narrow left column
        # under the photo list, where three groups abreast would not fit.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.presets = PresetBar("Output preset", self.to_output)
        self.presets.applyRequested.connect(self._apply_preset)
        layout.addWidget(self.presets)

        layout.addWidget(self._build_output())
        layout.addWidget(self._build_destination())
        layout.addWidget(self._build_filename())
        layout.addStretch(1)

    def _build_output(self) -> QGroupBox:
        box = QGroupBox("Output")
        form = QFormLayout(box)

        self.width = QComboBox()
        for w in g.OUTPUT_WIDTHS:
            self.width.addItem(f"{w} px", w)
        self.width.setToolTip(
            "1080 is Instagram's native width. Uploading wider means their "
            "servers downscale and recompress it instead of you."
        )
        self.width.currentIndexChanged.connect(self._emit)
        form.addRow("Width", self.width)

        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(60, 100)
        self.quality.valueChanged.connect(self._on_quality)
        self.quality_label = QLabel()
        qrow = QHBoxLayout()
        qrow.addWidget(self.quality, 1)
        qrow.addWidget(self.quality_label)
        form.addRow("JPEG quality", qrow)

        self.sharpen = QSlider(Qt.Orientation.Horizontal)
        self.sharpen.setRange(0, 100)
        self.sharpen.setToolTip(
            "Compensates for the softening that downscaling causes. Scaled "
            "automatically by how far each photo shrinks."
        )
        self.sharpen.valueChanged.connect(self._on_sharpen)
        self.sharpen_label = QLabel()
        srow = QHBoxLayout()
        srow.addWidget(self.sharpen, 1)
        srow.addWidget(self.sharpen_label)
        form.addRow("Sharpening", srow)
        return box

    def _build_destination(self) -> QGroupBox:
        box = QGroupBox("Destination")
        outer = QVBoxLayout(box)

        self.dest_source = QRadioButton("Same folder as the original")
        self.dest_folder_radio = QRadioButton("This folder:")
        self.dest_source.toggled.connect(self._on_dest_toggled)
        outer.addWidget(self.dest_source)
        outer.addWidget(self.dest_folder_radio)

        row = QHBoxLayout()
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("Choose a folder")
        self.dest_edit.textChanged.connect(self._emit)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._pick_folder)
        row.addWidget(self.dest_edit, 1)
        row.addWidget(browse)
        outer.addLayout(row)

        form = QFormLayout()
        self.collision = QComboBox()
        self.collision.addItem("Add a number", "increment")
        self.collision.addItem("Skip the photo", "skip")
        self.collision.addItem("Overwrite it", "overwrite")
        self.collision.setToolTip(
            "The original is never overwritten, whatever this is set to."
        )
        self.collision.currentIndexChanged.connect(self._emit)
        form.addRow("If the name is taken", self.collision)
        outer.addLayout(form)
        outer.addStretch(1)
        return box

    def _build_filename(self) -> QGroupBox:
        box = QGroupBox("Filename")
        form = QFormLayout(box)

        self.template = QLineEdit()
        self.template.textChanged.connect(self._on_template)
        form.addRow("Template", self.template)

        presets = QHBoxLayout()
        suffix_btn = QPushButton("Append suffix")
        suffix_btn.clicked.connect(
            lambda: self.template.setText(naming.PRESET_SUFFIX)
        )
        custom_btn = QPushButton("Custom name")
        custom_btn.clicked.connect(
            lambda: self.template.setText(naming.PRESET_CUSTOM)
        )
        presets.addWidget(suffix_btn)
        presets.addWidget(custom_btn)
        presets.addStretch(1)
        form.addRow("", presets)

        self.custom_name = QLineEdit()
        self.custom_name.setPlaceholderText("Used by the {custom} token")
        self.custom_name.textChanged.connect(self._emit)
        form.addRow("Custom name", self.custom_name)

        self.template_hint = QLabel()
        self.template_hint.setWordWrap(True)
        self.template_hint.setStyleSheet(hint_style())
        self.template_hint.setToolTip(
            "\n".join(f"{{{k}}}  {v}" for k, v in naming.TOKENS.items())
        )
        form.addRow("", self.template_hint)
        return box

    # --- reacting ---------------------------------------------------------

    def _emit(self, *_) -> None:
        if not self._loading:
            self.presets.note_values_changed()
            self.changed.emit()

    def set_preset_store(self, store: PresetStore) -> None:
        self.presets.set_store(store)

    def _apply_preset(self, output: OutputSettings) -> None:
        """Apply an output preset, tolerating a folder that has since gone.

        An absolute path does not survive moving machines or reorganising
        folders, so the rest of the preset still applies and the missing path
        is reported instead of silently writing somewhere unexpected.
        """
        message = ""
        if output.dest_mode == "folder" and output.dest_folder:
            if not Path(output.dest_folder).is_dir():
                output = output.copy()
                output.dest_folder = ""
                message = (
                    "That preset's output folder no longer exists - "
                    "choose one before processing"
                )
        self.load_output(output)
        if message:
            self.warning.emit(message)

    def _on_quality(self, value: int) -> None:
        self.quality_label.setText(str(value))
        self._emit()

    def _on_sharpen(self, value: int) -> None:
        self.sharpen_label.setText("Off" if value == 0 else str(value))
        self._emit()

    def _on_template(self, *_) -> None:
        problem = naming.validate(self.template.text())
        self.template_hint.setText(
            problem or "Tokens: " + "  ".join(f"{{{k}}}" for k in naming.TOKENS)
        )
        self.template_hint.setStyleSheet(error_style() if problem else hint_style())
        self._emit()

    def _on_dest_toggled(self, *_) -> None:
        self.dest_edit.setEnabled(self.dest_folder_radio.isChecked())
        self._emit()

    def _pick_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Output folder", self.dest_edit.text() or ""
        )
        if chosen:
            self.dest_edit.setText(chosen)
            self.dest_folder_radio.setChecked(True)

    # --- round trip -------------------------------------------------------

    def load(self, settings: Settings) -> None:
        self._loading = True
        self.load_output(settings.output, emit=False)
        self.custom_name.setText(settings.custom_name)
        self._loading = False
        self._on_template()

    def load_output(self, output: OutputSettings, emit: bool = True) -> None:
        """Push an OutputSettings into the controls.

        Separate from `load` so that applying an output preset reuses exactly
        the same path, rather than a parallel one that can drift.
        """
        was_loading = self._loading
        self._loading = True
        self.width.setCurrentIndex(
            max(0, self.width.findData(output.output_width))
        )
        self.quality.setValue(output.quality)
        self.quality_label.setText(str(output.quality))
        self.sharpen.setValue(output.sharpen)
        self.sharpen_label.setText(
            "Off" if output.sharpen == 0 else str(output.sharpen)
        )
        self.dest_source.setChecked(output.dest_mode == "source")
        self.dest_folder_radio.setChecked(output.dest_mode == "folder")
        self.dest_edit.setText(output.dest_folder)
        self.dest_edit.setEnabled(output.dest_mode == "folder")
        self.collision.setCurrentIndex(
            max(0, self.collision.findData(output.collision))
        )
        self.template.setText(output.template)
        self._loading = was_loading
        self._on_template()
        self.presets.note_values_changed()
        if emit and not self._loading:
            self.changed.emit()

    def to_output(self) -> OutputSettings:
        return OutputSettings(
            output_width=self.width.currentData() or g.DEFAULT_OUTPUT_WIDTH,
            quality=self.quality.value(),
            sharpen=self.sharpen.value(),
            dest_mode="folder" if self.dest_folder_radio.isChecked() else "source",
            dest_folder=self.dest_edit.text().strip(),
            template=self.template.text(),
            collision=self.collision.currentData() or "increment",
        )

    def to_settings(self, base: Settings) -> Settings:
        """Read the controls back, keeping `base`'s framing and UI state."""
        return Settings(
            framing=base.framing.copy(),
            output=self.to_output(),
            custom_name=self.custom_name.text().strip(),
            show_grid_overlay=base.show_grid_overlay,
            last_open_dir=base.last_open_dir,
        )
