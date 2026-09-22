"""The photo list.

A selection list and nothing more: the columns report what each photo is set
to, but none of them are editable. Framing is changed in the right-hand panel,
which acts on the selection -- having controls in both places was the source
of the "two settings views" confusion.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem,
)

from ..core.pipeline import Job, iter_images, plan, probe
from ..core.settings import Framing, Settings

COL_FILE, COL_FRAMING, COL_OUTPUT, COL_STATUS = range(4)
HEADERS = ["Photo", "Framing", "Output", "Status"]

WARN_COLOR = QColor(184, 110, 0)
ERROR_COLOR = QColor(190, 60, 60)
OK_COLOR = QColor(40, 140, 70)


def _read_only_item(text: str = "") -> QTableWidgetItem:
    """A cell that cannot be edited even if edit triggers are ever turned on.

    Qt sets ItemIsEditable by default; the list is for selecting photos, and
    framing is changed in the panel on the right.
    """
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return item


def describe(framing: Framing) -> str:
    """Compact, read-only summary of a photo's framing."""
    fit = "fit" if framing.mode == "fit" else "crop"
    return f"{framing.ratio}  {fit}  {framing.border_pct:g}%"


class QueueTable(QTableWidget):
    """Drop target and selection list."""

    jobsChanged = Signal()
    selectionChangedJob = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(0, len(HEADERS), parent)
        self._jobs: list[Job] = []
        self._settings = Settings()

        self.setHorizontalHeaderLabels(HEADERS)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setAcceptDrops(True)

        header = self.horizontalHeader()
        header.setMinimumSectionSize(64)
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_OUTPUT, QHeaderView.ResizeMode.Stretch)
        for col in (COL_FRAMING, COL_STATUS):
            header.setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )

        self.itemSelectionChanged.connect(self.selectionChangedJob)

    # --- drag and drop ----------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()

    # --- jobs -------------------------------------------------------------

    def jobs(self) -> list[Job]:
        return list(self._jobs)

    def is_empty(self) -> bool:
        return not self._jobs

    def add_paths(self, paths, framing: Framing | None = None) -> int:
        """Add every supported image under `paths`, returning how many were new.

        New photos inherit `framing`, so a second drop matches the first.
        """
        template = framing or self._settings.framing
        existing = {j.source.resolve() for j in self._jobs}
        added = 0
        for path in iter_images(paths):
            try:
                if path.resolve() in existing:
                    continue
                existing.add(path.resolve())
            except OSError:
                continue
            self._jobs.append(Job(path, framing=template.copy()))
            self._append_row(self._jobs[-1])
            added += 1
        if added:
            self.refresh(self._settings)
            self.jobsChanged.emit()
        return added

    def remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.selectedIndexes()}, reverse=True)
        for row in rows:
            self.removeRow(row)
            del self._jobs[row]
        if rows:
            self.refresh(self._settings)
            self.jobsChanged.emit()

    def clear_all(self) -> None:
        if not self._jobs:
            return
        self.setRowCount(0)
        self._jobs.clear()
        self.jobsChanged.emit()

    # --- selection --------------------------------------------------------

    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.selectedIndexes()})

    def selected_jobs(self) -> list[Job]:
        return [self._jobs[r] for r in self.selected_rows() if r < len(self._jobs)]

    def current_job(self) -> Job | None:
        """The photo the preview should show: first selected, else the first."""
        rows = self.selected_rows()
        row = rows[0] if rows else (0 if self._jobs else -1)
        return self._jobs[row] if 0 <= row < len(self._jobs) else None

    def apply_framing(self, framing: Framing, to_all: bool = False) -> None:
        """Write `framing` onto the selection, or onto every photo."""
        targets = self._jobs if to_all else (self.selected_jobs() or self._jobs[:1])
        for job in targets:
            job.framing = framing.copy()
        self.refresh(self._settings)
        self.jobsChanged.emit()

    # --- rows -------------------------------------------------------------

    def _append_row(self, job: Job) -> None:
        row = self.rowCount()
        self.insertRow(row)

        try:
            size = probe(job.source).size
            size_text = f"{size[0]} x {size[1]} px"
        except Exception:
            size_text = "unreadable"

        name = _read_only_item(job.source.name)
        name.setToolTip(f"{job.source}\n{size_text}")
        self.setItem(row, COL_FILE, name)
        for col in (COL_FRAMING, COL_OUTPUT, COL_STATUS):
            self.setItem(row, col, _read_only_item())

    # --- display ----------------------------------------------------------

    def refresh(self, settings: Settings) -> None:
        """Recompute every row's framing summary, output name and warnings."""
        self._settings = settings
        for row, job in enumerate(self._jobs):
            self._set_cell(
                row, COL_FRAMING, describe(job.framing), None,
                "Change this in the Framing panel on the right",
            )
            try:
                preview = plan(job, settings, index=row + 1)
            except Exception as exc:
                self._set_cell(row, COL_OUTPUT, "-", ERROR_COLOR, str(exc))
                self._set_cell(row, COL_STATUS, "Error", ERROR_COLOR, str(exc))
                continue

            self._set_cell(
                row, COL_OUTPUT, preview.output.name, None, str(preview.output)
            )
            if preview.warnings:
                self._set_cell(
                    row, COL_STATUS, "Will enlarge", WARN_COLOR,
                    "\n".join(preview.warnings),
                )
            else:
                self._set_cell(row, COL_STATUS, "", None, "")

    def set_result(self, row: int, result) -> None:
        if result.skipped:
            self._set_cell(row, COL_STATUS, "Skipped", WARN_COLOR,
                           "A file of that name already exists")
        elif result.error:
            self._set_cell(row, COL_STATUS, "Failed", ERROR_COLOR, result.error)
        else:
            self._set_cell(row, COL_STATUS, "Done", OK_COLOR, str(result.output))
            self._set_cell(row, COL_OUTPUT, result.output.name, None,
                           str(result.output))

    def _set_cell(self, row: int, col: int, text: str, fg, tooltip: str) -> None:
        item = self.item(row, col)
        if item is None:
            item = _read_only_item()
            self.setItem(row, col, item)
        item.setText(text)
        item.setToolTip(tooltip)
        item.setForeground(QBrush(fg) if fg else QBrush())
