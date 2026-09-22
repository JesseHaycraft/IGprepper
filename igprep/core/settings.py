"""Persisted application settings.

Two levels, matching the two halves of the window:

* `Framing` is per photo -- how one image is composed inside its canvas.
  Edited in the right-hand panel, which acts on the current selection.
* `Settings` is the batch -- encoding and where files land. Edited beneath
  the photo list, because it describes the run rather than any one image.

Loading is deliberately forgiving: a corrupt or out-of-date file falls back to
defaults rather than refusing to start.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import geometry as g
from . import naming, render

log = logging.getLogger(__name__)

# Deliberately not renamed alongside the app: this is the folder holding
# settings and presets, and changing it would orphan anything already
# saved. It also matches the Python package name.
APP_NAME = "igprep"
CONFIG_FILE = "settings.json"

DEST_MODES = ("source", "folder")
COLLISION_POLICIES = ("increment", "skip", "overwrite")
MODES = ("crop", "fit")
# Fit never discards any of the photo, which is the safer thing to do to
# someone's work by default.
DEFAULT_MODE = "fit"


def config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / CONFIG_FILE


def _clamp(value, low, high):
    return max(low, min(high, value))


@dataclass
class Framing:
    """How a single photo sits inside its canvas."""

    ratio: str = g.DEFAULT_RATIO
    mode: str = DEFAULT_MODE
    border_pct: float = g.DEFAULT_BORDER_PCT
    frame_color: str = render.DEFAULT_FRAME_COLOR

    def aspect(self) -> g.AspectRatio:
        return g.RATIOS_BY_KEY.get(self.ratio) or g.ratio_for(g.DEFAULT_RATIO)

    def max_border_pct(self, width: int = g.DEFAULT_OUTPUT_WIDTH) -> float:
        """Cap for this ratio -- wide ratios run out of room sooner."""
        if width not in g.OUTPUT_WIDTHS:
            width = g.DEFAULT_OUTPUT_WIDTH
        return g.max_border_pct(self.aspect(), width)

    def copy(self) -> "Framing":
        return Framing(**asdict(self))

    def normalized(self, width: int = g.DEFAULT_OUTPUT_WIDTH) -> "Framing":
        f = self.copy()
        if f.ratio not in g.RATIOS_BY_KEY:
            f.ratio = g.DEFAULT_RATIO
        if f.mode not in MODES:
            f.mode = DEFAULT_MODE
        if not str(f.frame_color).startswith("#") or len(f.frame_color) != 7:
            f.frame_color = render.DEFAULT_FRAME_COLOR
        f.border_pct = float(_clamp(f.border_pct, 0.0, f.max_border_pct(width)))
        return f

    @classmethod
    def from_dict(cls, data) -> "Framing":
        if not isinstance(data, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class OutputSettings:
    """How the batch is encoded and where it lands.

    Grouped rather than left flat on `Settings` so that it is the same shape
    as `Framing`: one preset store then serves both.

    `custom_name` is deliberately not here. It is content -- the name you type
    for today's batch -- not reusable configuration, and a preset that
    overwrote it would be a nuisance.
    """

    output_width: int = g.DEFAULT_OUTPUT_WIDTH
    quality: int = render.DEFAULT_QUALITY
    sharpen: int = render.DEFAULT_SHARPEN
    dest_mode: str = "source"
    dest_folder: str = ""
    template: str = naming.DEFAULT_TEMPLATE
    collision: str = "increment"

    def copy(self) -> "OutputSettings":
        return OutputSettings(**asdict(self))

    def normalized(self) -> "OutputSettings":
        o = self.copy()
        if o.dest_mode not in DEST_MODES:
            o.dest_mode = "source"
        if o.collision not in COLLISION_POLICIES:
            o.collision = "increment"
        if o.output_width not in g.OUTPUT_WIDTHS:
            o.output_width = g.DEFAULT_OUTPUT_WIDTH
        o.quality = int(_clamp(o.quality, 60, 100))
        o.sharpen = int(_clamp(o.sharpen, 0, 100))
        if naming.validate(o.template) is not None:
            o.template = naming.DEFAULT_TEMPLATE
        return o

    @classmethod
    def from_dict(cls, data) -> "OutputSettings":
        if not isinstance(data, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Settings:
    """Batch-wide settings, plus the framing newly added photos inherit."""

    # Applied to photos as they are added; the panel keeps this in step with
    # whatever was last used, so a second drop matches the first.
    framing: Framing = field(default_factory=Framing)
    output: OutputSettings = field(default_factory=OutputSettings)

    custom_name: str = ""
    show_grid_overlay: bool = True
    last_open_dir: str = ""

    def normalized(self) -> "Settings":
        """Return a copy with every field forced into a usable range."""
        s = Settings(
            framing=self.framing.copy(),
            output=self.output.normalized(),
            custom_name=self.custom_name,
            show_grid_overlay=self.show_grid_overlay,
            last_open_dir=self.last_open_dir,
        )
        s.framing = s.framing.normalized(s.output.output_width)
        return s

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        nested = {"framing", "output"}
        known = {f.name for f in fields(cls)} - nested
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["framing"] = Framing.from_dict(data.get("framing"))
        # Files written before the output settings were grouped have these
        # keys flat at the top level; from_dict ignores everything it does not
        # recognise, so handing it the whole document recovers them.
        raw = data.get("output")
        kwargs["output"] = OutputSettings.from_dict(
            raw if isinstance(raw, dict) else data
        )
        return cls(**kwargs).normalized()

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or config_path()
        try:
            with open(path, encoding="utf-8") as fh:
                return cls.from_dict(json.load(fh))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError, TypeError) as exc:
            log.warning("ignoring unreadable settings at %s (%s)", path, exc)
            return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-replace so a crash mid-write cannot corrupt the file.
            tmp = path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, indent=2)
            os.replace(tmp, path)
        except OSError as exc:
            log.warning("could not save settings to %s (%s)", path, exc)
