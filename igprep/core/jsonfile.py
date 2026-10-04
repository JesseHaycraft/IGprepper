"""Writing a small JSON file so that it is never left half-written."""

from __future__ import annotations

import json
import os
from pathlib import Path


def write_json(path: Path, data, indent: int | None = None) -> None:
    """Write `data` to `path`, creating the folder if need be.

    Written beside the real file and swapped in, so a crash part-way cannot
    leave a file that will not load.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".tmp")
    with open(partial, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=indent)
    os.replace(partial, path)
