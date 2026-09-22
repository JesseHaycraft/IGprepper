"""Background batch processing.

Rendering blocks for a second or more per photo, so it runs off the UI thread;
the window stays responsive and the run stays cancellable.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ..core.pipeline import Job, Result, process
from ..core.settings import Settings


class ProcessWorker(QThread):
    progress = Signal(int, int, str)   # completed, total, current filename
    item_done = Signal(int, object)    # row index, Result
    finished_all = Signal(list)        # list[Result]

    def __init__(self, jobs: list[Job], settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self._jobs = list(jobs)
        self._settings = settings
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        results: list[Result] = []
        total = len(self._jobs)
        for i, job in enumerate(self._jobs):
            if self._cancelled:
                break
            # Index is 1-based so {n} starts at 1 in filename templates.
            result = process(job, self._settings, index=i + 1)
            results.append(result)
            self.item_done.emit(i, result)
            self.progress.emit(i + 1, total, job.source.name)
        self.finished_all.emit(results)
