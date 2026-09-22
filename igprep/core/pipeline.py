"""Turning queued files into written JPEGs.

This module is the seam between the GUI and the image code: the GUI builds
`Job`s, asks for a `Preview` to show, then calls `process`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from . import geometry as g
from . import naming, render
from .settings import Framing, Settings

SUPPORTED_SUFFIXES = frozenset(
    {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
)
OUTPUT_SUFFIX = ".jpg"

_EXIF_IFD = 0x8769
_DATETIME_ORIGINAL = 36867
_DATETIME = 306
_ORIENTATION = 274
# Orientations 5-8 involve a 90 degree turn, so width and height swap.
_ROTATED = {5, 6, 7, 8}


def iter_images(paths) -> list[Path]:
    """Expand a drop of files and folders into a sorted, de-duplicated list."""
    found: list[Path] = []
    seen: set[Path] = set()
    for raw in paths:
        p = Path(raw)
        candidates = (
            sorted(q for q in p.rglob("*") if q.is_file())
            if p.is_dir()
            else [p]
        )
        for c in candidates:
            if c.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            key = c.resolve()
            if key not in seen:
                seen.add(key)
                found.append(c)
    return found


@dataclass
class Probe:
    """Cheap header-only look at a source file."""

    size: tuple[int, int]
    captured: datetime


def probe(path: Path) -> Probe:
    """Read dimensions and capture time without decoding the pixels."""
    with Image.open(path) as img:
        size = img.size
        try:
            exif = img.getexif()
            if exif.get(_ORIENTATION, 1) in _ROTATED:
                size = (size[1], size[0])
            raw = exif.get_ifd(_EXIF_IFD).get(_DATETIME_ORIGINAL) or exif.get(
                _DATETIME
            )
        except Exception:
            raw = None

    captured = None
    if raw:
        try:
            captured = datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
        except ValueError:
            captured = None
    return Probe(size, captured or datetime.fromtimestamp(path.stat().st_mtime))


@dataclass
class Job:
    """One queued photo and how it is framed."""

    source: Path
    framing: Framing = field(default_factory=Framing)


@dataclass
class Preview:
    """What `process` would do, resolved without touching any pixels."""

    layout: g.Layout
    output: Path
    source_size: tuple[int, int]
    warnings: list[str] = field(default_factory=list)


@dataclass
class Result:
    job: Job
    output: Path | None = None
    error: str | None = None
    skipped: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and not self.skipped


def _dest_dir(job: Job, settings: Settings) -> Path:
    if settings.output.dest_mode == "folder" and settings.output.dest_folder:
        return Path(settings.output.dest_folder)
    return job.source.parent


def plan(job: Job, settings: Settings, index: int = 1) -> Preview:
    """Resolve a job into a concrete layout and output path."""
    info = probe(job.source)
    ratio = g.ratio_for(job.framing.ratio)
    layout = g.plan(
        info.size,
        ratio=ratio,
        width=settings.output.output_width,
        border_pct=job.framing.border_pct,
        mode=job.framing.mode,
    )

    stem = naming.render(
        settings.output.template,
        name=job.source.stem,
        custom=settings.custom_name,
        n=index,
        ratio=ratio.key,
        w=layout.canvas[0],
        h=layout.canvas[1],
        when=info.captured,
    )
    output = _dest_dir(job, settings) / f"{stem}{OUTPUT_SUFFIX}"

    warnings: list[str] = []
    if layout.upscaled:
        pct = round(layout.scale * 100)
        warnings.append(
            f"Source is smaller than the frame; it will be enlarged to {pct}%"
        )
    return Preview(layout, output, info.size, warnings)


def _resolve_collision(output: Path, source: Path, settings: Settings):
    """Return the path to write, or None to skip.

    Never returns the source path: overwriting the original is always wrong,
    whatever the collision policy says.
    """
    try:
        same = output.resolve() == source.resolve()
    except OSError:
        same = False
    if same:
        return naming.unique_path(output)
    if not output.exists():
        return output
    if settings.output.collision == "overwrite":
        return output
    if settings.output.collision == "skip":
        return None
    return naming.unique_path(output)


def process(job: Job, settings: Settings, index: int = 1) -> Result:
    """Render one job and write it to disk."""
    try:
        preview = plan(job, settings, index)
        target = _resolve_collision(preview.output, job.source, settings)
        if target is None:
            return Result(job, skipped=True)

        img = render.load(job.source)
        canvas = render.render(
            img,
            preview.layout,
            frame_color=job.framing.frame_color,
            sharpen=settings.output.sharpen,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        render.save_jpeg(canvas, target, quality=settings.output.quality)
        return Result(job, output=target)
    except (UnidentifiedImageError, OSError) as exc:
        return Result(job, error=f"Could not read or write the file: {exc}")
    except (g.GeometryError, naming.NamingError) as exc:
        return Result(job, error=str(exc))
    except Exception as exc:  # a bad file should not take the batch down
        return Result(job, error=f"Unexpected error: {exc}")
