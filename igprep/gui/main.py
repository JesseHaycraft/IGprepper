"""Main window.

The window is split by *scope*, not by widget type:

* Left column -- the batch. Which photos, then where they are written and
  what they are called.
* Middle -- the preview of the current photo.
* Right column -- framing for the selected photo(s).

Settings appear in exactly one of those places, never two.
"""

from __future__ import annotations

import ctypes.util
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QSplitter,
    QVBoxLayout, QWidget,
)

from ..core import geometry as g
from ..core import naming
from ..core.pipeline import SUPPORTED_SUFFIXES, plan
from ..core.presets import PresetLibrary
from ..core.settings import Settings
from .panel import BatchPanel, FramingPanel
from .preview import PreviewPane, ProxyCache, pil_to_qpixmap, render_preview
from .queue import QueueTable
from .style import hint_style, warning_style
from .worker import ProcessWorker

APP_TITLE = "IGprepper"
# Sliders emit continuously; re-rendering on every tick would stutter.
PREVIEW_DEBOUNCE_MS = 80


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1500, 880)
        self.setAcceptDrops(True)

        self.settings = Settings.load()
        self.presets = PresetLibrary.load()
        self.cache = ProxyCache()
        self.worker: ProcessWorker | None = None

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(PREVIEW_DEBOUNCE_MS)
        self._preview_timer.timeout.connect(self._render_preview)

        self._build_ui()
        self._build_menu()

        self.framing.set_preset_store(self.presets.framing)
        self.batch.set_preset_store(self.presets.output)
        self.batch.load(self.settings)
        self.framing.load(self.settings.framing, self.settings.output.output_width)
        self.queue.refresh(self.settings)
        self.preview.set_show_grid(self.settings.show_grid_overlay)
        self.grid_toggle.setChecked(self.settings.show_grid_overlay)
        self._sync_scope()
        self._update_enabled()

    # --- construction -----------------------------------------------------

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_batch_side())
        splitter.addWidget(self._build_preview_side())
        splitter.addWidget(self._build_framing_side())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([540, 550, 390])

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Drop photos onto the window to begin")

    def _build_batch_side(self) -> QWidget:
        """Photo list, the settings that apply to all of them, then Process.

        Processing acts on the batch, so the button belongs at the foot of the
        batch column rather than spanning a window it only half concerns.
        """
        column = QSplitter(Qt.Orientation.Vertical)
        column.addWidget(self._build_list_pane())
        column.addWidget(self._build_batch_panel())
        column.setStretchFactor(0, 2)
        column.setStretchFactor(1, 3)
        column.setSizes([300, 505])

        side = QWidget()
        layout = QVBoxLayout(side)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(column, 1)
        layout.addLayout(self._build_action_bar())
        return side

    def _build_list_pane(self) -> QWidget:
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)

        caption = QLabel("Photos to process. Select one or more to frame them.")
        caption.setWordWrap(True)
        caption.setStyleSheet(hint_style())
        layout.addWidget(caption)

        bar = QHBoxLayout()
        add = QPushButton("Add photos...")
        add.clicked.connect(self._add_photos)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(lambda: self.queue.remove_selected())
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(lambda: self.queue.clear_all())
        self.select_all_btn = QPushButton("Select all")
        self.select_all_btn.clicked.connect(lambda: self.queue.selectAll())
        for w in (add, self.remove_btn, self.clear_btn, self.select_all_btn):
            bar.addWidget(w)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.queue = QueueTable()
        self.queue.jobsChanged.connect(self._on_queue_changed)
        self.queue.selectionChangedJob.connect(self._on_selection_changed)
        layout.addWidget(self.queue, 1)
        return pane

    def _build_batch_panel(self) -> QWidget:
        self.batch = BatchPanel()
        self.batch.changed.connect(self._on_batch_changed)
        self.batch.warning.connect(self.statusBar().showMessage)

        scroll = QScrollArea()
        scroll.setWidget(self.batch)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        return scroll

    def _build_preview_side(self) -> QWidget:
        side = QWidget()
        layout = QVBoxLayout(side)
        layout.setContentsMargins(0, 0, 0, 0)

        self.preview = PreviewPane()
        layout.addWidget(self.preview, 1)

        self.grid_toggle = QCheckBox("Show the 3:4 profile-grid crop")
        self.grid_toggle.setToolTip(
            "Instagram's grid thumbnails are 3:4, which is taller than 4:5 "
            "or 1:1, so those posts lose their sides in the grid."
        )
        self.grid_toggle.toggled.connect(self._on_grid_toggled)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.grid_toggle)
        row.addStretch(1)
        layout.addLayout(row)

        self.preview_info = QLabel()
        self.preview_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_info.setWordWrap(True)
        self.preview_info.setStyleSheet(hint_style())
        layout.addWidget(self.preview_info)
        return side

    def _build_framing_side(self) -> QWidget:
        self.framing = FramingPanel()
        self.framing.changed.connect(self._on_framing_changed)
        self.framing.applyToAll.connect(self._apply_framing_to_all)

        scroll = QScrollArea()
        scroll.setWidget(self.framing)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setMinimumWidth(360)
        return scroll

    def _build_action_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()

        self.process_btn = QPushButton("Process")
        self.process_btn.setDefault(True)
        self.process_btn.setMinimumWidth(140)
        self.process_btn.clicked.connect(self._process)
        bar.addWidget(self.process_btn)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        bar.addWidget(self.progress, 4)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel)
        bar.addWidget(self.cancel_btn)

        # Keeps the button its own width while the progress bar is hidden;
        # without it the button stretches across the whole column.
        bar.addStretch(1)
        return bar

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        add = QAction("&Add photos...", self)
        add.setShortcut(QKeySequence.StandardKey.Open)
        add.triggered.connect(self._add_photos)
        file_menu.addAction(add)

        process = QAction("&Process", self)
        process.setShortcut("Ctrl+Return")
        process.triggered.connect(self._process)
        file_menu.addAction(process)

        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("&Help")
        about = QAction("&About", self)
        about.triggered.connect(self._about)
        help_menu.addAction(about)

    # --- drag and drop onto the window -----------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [
            Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()
        ]
        if paths:
            self._add(paths)
            event.acceptProposedAction()

    # --- queue ------------------------------------------------------------

    def _add_photos(self) -> None:
        patterns = " ".join(f"*{s}" for s in sorted(SUPPORTED_SUFFIXES))
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add photos", self.settings.last_open_dir,
            f"Images ({patterns})",
        )
        if files:
            self.settings.last_open_dir = str(Path(files[0]).parent)
            self._add([Path(f) for f in files])

    def open_paths(self, paths: list[Path]) -> None:
        """Add files handed to the app at launch."""
        self._add(paths)

    def _add(self, paths: list[Path]) -> None:
        # New photos inherit whatever the framing panel currently shows.
        added = self.queue.add_paths(paths, self.framing.to_framing())
        total = len(self.queue.jobs())
        if added:
            if not self.queue.selected_rows():
                self.queue.selectRow(0)
            self.statusBar().showMessage(
                f"Added {added} photo{'s' if added != 1 else ''} ({total} queued)"
            )
        else:
            self.statusBar().showMessage("Nothing new to add")

    def _on_queue_changed(self) -> None:
        self._update_enabled()
        self._sync_scope()
        self._schedule_preview()

    def _on_selection_changed(self) -> None:
        """Show the selected photo's framing without echoing it back."""
        job = self.queue.current_job()
        if job is not None:
            self.framing.load(job.framing, self.settings.output.output_width)
        self._sync_scope()
        self._schedule_preview()

    def _sync_scope(self) -> None:
        count = len(self.queue.selected_jobs())
        if self.queue.is_empty():
            text = "No photos yet -- this is what photos you add will start from."
        elif count > 1:
            text = f"Applies to the {count} selected photos."
        else:
            job = self.queue.current_job()
            text = f"Applies to {job.source.name}." if job else ""
        self.framing.set_scope(text)

    # --- settings ---------------------------------------------------------

    def _on_framing_changed(self) -> None:
        framing = self.framing.to_framing()
        # Remember it as the starting point for photos added later.
        self.settings.framing = framing.copy()
        if not self.queue.is_empty():
            self.queue.apply_framing(framing)
        self._schedule_preview()

    def _apply_framing_to_all(self) -> None:
        if self.queue.is_empty():
            return
        self.queue.apply_framing(self.framing.to_framing(), to_all=True)
        self.statusBar().showMessage("Applied to every photo")

    def _on_batch_changed(self) -> None:
        self.settings = self.batch.to_settings(self.settings)
        self.framing.set_width(self.settings.output.output_width)
        if naming.validate(self.settings.output.template) is None:
            self.queue.refresh(self.settings)
        self._update_enabled()
        self._schedule_preview()

    def _on_grid_toggled(self, checked: bool) -> None:
        self.settings.show_grid_overlay = checked
        self.preview.set_show_grid(checked)

    def _template_problem(self) -> str | None:
        return naming.validate(self.settings.output.template)

    def _destination_problem(self) -> str | None:
        if self.settings.output.dest_mode == "folder" and not self.settings.output.dest_folder:
            return "Choose an output folder, or write back to the source folder"
        return None

    def _update_enabled(self) -> None:
        busy = self.worker is not None and self.worker.isRunning()
        has_jobs = not self.queue.is_empty()
        problem = self._template_problem() or self._destination_problem()

        self.process_btn.setEnabled(has_jobs and not busy and problem is None)
        self.process_btn.setToolTip(problem or "")
        for btn in (self.remove_btn, self.clear_btn, self.select_all_btn):
            btn.setEnabled(has_jobs and not busy)
        self.framing.apply_all_btn.setEnabled(has_jobs and not busy)

    # --- preview ----------------------------------------------------------

    def _schedule_preview(self) -> None:
        self._preview_timer.start()

    def _render_preview(self) -> None:
        job = self.queue.current_job()
        if job is None:
            self.preview.set_placeholder("Drop photos here")
            self.preview.set_preview(None)
            self.preview_info.setText("")
            return

        try:
            proxy = self.cache.get(job.source)
            image = render_preview(
                proxy,
                ratio=g.ratio_for(job.framing.ratio),
                border_pct=job.framing.border_pct,
                mode=job.framing.mode,
                frame_color=job.framing.frame_color,
            )
            self.preview.set_preview(pil_to_qpixmap(image))
            self.preview_info.setText(self._preview_caption(job))
        except Exception as exc:
            self.preview.set_preview(None)
            self.preview.set_placeholder(f"Could not preview {job.source.name}")
            self.preview_info.setText(str(exc))
            self.preview_info.setStyleSheet(warning_style())

    def _preview_caption(self, job) -> str:
        """Source and output dimensions, plus any warning for this photo."""
        rows = self.queue.selected_rows()
        index = (rows[0] if rows else 0) + 1
        try:
            preview = plan(job, self.settings, index=index)
        except Exception as exc:
            self.preview_info.setStyleSheet(warning_style())
            return str(exc)

        src = f"{preview.source_size[0]} x {preview.source_size[1]}"
        out = f"{preview.layout.canvas[0]} x {preview.layout.canvas[1]}"
        line = (
            f"{job.source.name}   |   {src}  ->  {out} px   |   "
            f"{preview.layout.border} px border   |   {preview.output.name}"
        )
        if preview.warnings:
            self.preview_info.setStyleSheet(warning_style())
            return line + "\n" + "  ".join(preview.warnings)
        self.preview_info.setStyleSheet(hint_style())
        return line

    # --- processing -------------------------------------------------------

    def _process(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        jobs = self.queue.jobs()
        if not jobs:
            return
        problem = self._template_problem() or self._destination_problem()
        if problem:
            QMessageBox.warning(self, APP_TITLE, problem)
            return

        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.cancel_btn.setVisible(True)

        self.worker = ProcessWorker(jobs, self.settings, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.item_done.connect(self.queue.set_result)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.start()
        self._update_enabled()

    def _on_progress(self, done: int, total: int, name: str) -> None:
        self.progress.setValue(done)
        self.statusBar().showMessage(f"Processing {done} of {total}: {name}")

    def _cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.statusBar().showMessage("Finishing the current photo...")

    def _on_finished(self, results: list) -> None:
        cancelled = self.worker is not None and self.worker.cancelled
        self.worker = None
        self.progress.setVisible(False)
        self.cancel_btn.setVisible(False)
        self._update_enabled()

        written = sum(1 for r in results if r.ok)
        skipped = [r for r in results if r.skipped]
        failed = [r for r in results if r.error]

        parts = [f"{written} written"]
        if skipped:
            parts.append(f"{len(skipped)} skipped")
        if failed:
            parts.append(f"{len(failed)} failed")
        if cancelled:
            parts.append("cancelled")
        self.statusBar().showMessage(", ".join(parts))

        if failed:
            detail = "\n".join(
                f"{r.job.source.name}: {r.error}" for r in failed[:10]
            )
            if len(failed) > 10:
                detail += f"\n...and {len(failed) - 10} more"
            QMessageBox.warning(
                self, APP_TITLE,
                f"{len(failed)} photo(s) could not be processed:\n\n{detail}",
            )

    # --- lifecycle --------------------------------------------------------

    def _about(self) -> None:
        QMessageBox.about(
            self, f"About {APP_TITLE}",
            f"<b>{APP_TITLE}</b><br><br>"
            "Resizes photos to Instagram's native dimensions with a "
            "consistent white frame.<br><br>"
            "Converts to sRGB, downscales with Lanczos, sharpens to "
            "compensate, and encodes at 4:4:4 so Instagram's own "
            "recompression has as little to spoil as possible.",
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)
        self.settings.save()
        super().closeEvent(event)


def file_arguments(argv: list[str]) -> list[Path]:
    """Existing files named on the command line.

    Populated by "Open with", by dropping photos on the app's icon, and on
    Linux by the %F field of a .desktop launcher.
    """
    return [
        Path(arg)
        for arg in argv[1:]
        if not arg.startswith("-") and Path(arg).exists()
    ]


def warn_if_qt_libs_missing() -> None:
    """Turn Qt's cryptic X11 failure into something actionable.

    Qt 6.5 and later need libxcb-cursor to load their X11 plugin, and abort
    with "could not load the Qt platform plugin xcb" before any of our code
    runs. Only a warning: the check can be wrong on unusual systems, and
    Wayland does not need the library at all.
    """
    if sys.platform != "linux" or os.environ.get("QT_QPA_PLATFORM"):
        return
    if ctypes.util.find_library("xcb-cursor") is not None:
        return
    print(
        "Warning: the xcb-cursor library was not found.\n"
        "If the window does not open, install it with:\n"
        "    sudo apt install libxcb-cursor0",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    # Read these before QApplication, which strips its own options from argv.
    paths = file_arguments(argv)
    warn_if_qt_libs_missing()

    app = QApplication(argv)
    app.setApplicationName(APP_TITLE)
    window = MainWindow()
    window.show()
    if paths:
        window.open_paths(paths)
    return app.exec()
