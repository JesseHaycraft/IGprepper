"""Output filename templating.

One template engine rather than separate "suffix" and "custom name" modes --
the presets below are just starting templates, so the UI needs one text field
and two buttons instead of a mode switch.
"""

from __future__ import annotations

import string
from datetime import datetime
from pathlib import Path

MAX_COLLISION_TRIES = 9999

TOKENS: dict[str, str] = {
    "name": "Original filename, without extension",
    "custom": "The custom name you type",
    "n": "Sequence number -- pad it as {n:03}",
    "ratio": "Aspect ratio, e.g. 3x4",
    "w": "Output width in pixels",
    "h": "Output height in pixels",
    "date": "Date taken, YYYY-MM-DD",
    "time": "Time taken, HHMMSS",
}

PRESET_SUFFIX = "{name}_ig"
PRESET_CUSTOM = "{custom}_{n:03}"
DEFAULT_TEMPLATE = PRESET_SUFFIX

# Illegal in Windows filenames; also stripped on macOS/Linux so that output
# written on one platform stays portable to the others.
_ILLEGAL = r'<>:"/\|?*'
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class NamingError(ValueError):
    """The template could not be rendered."""


class _StrictFormatter(string.Formatter):
    """A formatter that rejects unknown tokens instead of raising KeyError."""

    def __init__(self, values: dict[str, object]) -> None:
        self.values = values

    def get_field(self, field_name, args, kwargs):
        if not field_name:
            raise NamingError("write {name}, not {} -- tokens need a name")
        if "." in field_name or "[" in field_name:
            raise NamingError(f"{{{field_name}}} is not a valid token")
        if field_name not in self.values:
            known = ", ".join(f"{{{k}}}" for k in TOKENS)
            raise NamingError(f"unknown token {{{field_name}}}. Try one of: {known}")
        return self.values[field_name], field_name


def sanitize(stem: str) -> str:
    """Make an arbitrary string safe to use as a filename stem."""
    cleaned = "".join(
        "-" if (ch in _ILLEGAL or ord(ch) < 32) else ch for ch in stem
    )
    # Windows silently drops trailing dots and spaces, which breaks round-trips.
    cleaned = cleaned.strip().rstrip(". ")
    if not cleaned:
        raise NamingError("template produced an empty filename")
    if cleaned.upper().split(".")[0] in _RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned


def render(
    template: str,
    *,
    name: str,
    custom: str = "",
    n: int = 1,
    ratio: str = "",
    w: int = 0,
    h: int = 0,
    when: datetime | None = None,
) -> str:
    """Render a template into a sanitized filename stem (no extension)."""
    when = when or datetime.now()
    values: dict[str, object] = {
        "name": name,
        "custom": custom,
        "n": n,
        "ratio": ratio.replace(":", "x"),
        "w": w,
        "h": h,
        "date": when.strftime("%Y-%m-%d"),
        "time": when.strftime("%H%M%S"),
    }
    try:
        rendered = _StrictFormatter(values).vformat(template, (), {})
    except NamingError:
        raise
    except (ValueError, IndexError, KeyError) as exc:
        raise NamingError(f"could not read that template: {exc}") from exc
    return sanitize(rendered)


def validate(template: str) -> str | None:
    """Return a human-readable problem with `template`, or None if it is fine.

    Used for live feedback as the user types, so it must never raise.
    """
    if not template.strip():
        return "Filename template is empty"
    try:
        stem = render(
            template,
            name="photo", custom="custom", n=1, ratio="3:4", w=1080, h=1440,
        )
    except NamingError as exc:
        return str(exc)
    if "{" not in template and "}" not in template:
        return f"No tokens, so every photo would be named {stem!r}"
    return None


def unique_path(path: Path) -> Path:
    """First free path at or after `path`, appending _2, _3, ... as needed."""
    if not path.exists():
        return path
    for i in range(2, MAX_COLLISION_TRIES + 1):
        candidate = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise NamingError(f"could not find a free filename near {path.name}")
