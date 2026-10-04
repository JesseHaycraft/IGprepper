"""A log file like any other file, in the temporary folder."""

from __future__ import annotations

import tempfile
from pathlib import Path


class LogFile:
    def __init__(self, name: str) -> None:
        self.path = Path(tempfile.gettempdir()) / name
        self.location = str(self.path)

    def write(self, text: str, everything) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(text)

    def prune(self, keep: int, prefix: str) -> int:
        return 0
