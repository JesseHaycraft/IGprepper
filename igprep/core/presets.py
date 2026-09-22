"""Named presets.

Two independent lists -- framing (the look, applied to selected photos) and
output (encoding and destination, applied to the run) -- sharing one file.
Because `Framing` and `OutputSettings` are the same shape, one generic store
serves both.

Kept out of `settings.json`: presets have a different lifecycle, they are the
thing worth copying between machines, and a corrupt presets file must not take
the settings with it.

Stored as JSON rather than one file per preset, so preset names never reach
the filesystem and need no sanitising -- any name is safe.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Generic, TypeVar

from .settings import Framing, OutputSettings, config_dir

log = logging.getLogger(__name__)

PRESETS_FILE = "presets.json"
VERSION = 1
FRAMING_SECTION = "framing"
OUTPUT_SECTION = "output"
MAX_NAME_LENGTH = 80

T = TypeVar("T")


class PresetError(ValueError):
    """A preset could not be saved under that name."""


def presets_path() -> Path:
    return config_dir() / PRESETS_FILE


def clean_name(name: str) -> str:
    """Validate a preset name, returning the trimmed form."""
    cleaned = " ".join(str(name).split())
    if not cleaned:
        raise PresetError("Give the preset a name")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise PresetError(
            f"Names are limited to {MAX_NAME_LENGTH} characters"
        )
    return cleaned


class PresetStore(Generic[T]):
    """One named list, backed by a section of the library's file."""

    def __init__(
        self,
        library: "PresetLibrary",
        section: str,
        factory: Callable[[dict], T],
    ) -> None:
        self._library = library
        self._section = section
        self._factory = factory

    @property
    def _raw(self) -> dict[str, dict]:
        return self._library.section(self._section)

    def names(self) -> list[str]:
        return list(self._raw)

    def __len__(self) -> int:
        return len(self._raw)

    def find(self, name: str) -> str | None:
        """The stored spelling matching `name`, ignoring case."""
        target = str(name).casefold().strip()
        for existing in self._raw:
            if existing.casefold() == target:
                return existing
        return None

    def exists(self, name: str) -> bool:
        return self.find(name) is not None

    def get(self, name: str) -> T | None:
        stored = self.find(name)
        if stored is None:
            return None
        # Normalised on the way out, so a preset naming a ratio that no longer
        # exists degrades instead of breaking the panel that loads it.
        return self._factory(self._raw[stored]).normalized()

    def save(self, name: str, values) -> str:
        """Create or overwrite, returning the stored name."""
        cleaned = clean_name(name)
        existing = self.find(cleaned)
        if existing is not None and existing != cleaned:
            # Same name in different case: replace it rather than ending up
            # with "Square" and "square" side by side.
            del self._raw[existing]
        self._raw[cleaned] = asdict(values)
        self._library.save()
        return cleaned

    def rename(self, old: str, new: str) -> str:
        cleaned = clean_name(new)
        stored = self.find(old)
        if stored is None:
            raise PresetError(f"There is no preset called {old!r}")
        clash = self.find(cleaned)
        if clash is not None and clash != stored:
            raise PresetError(f"A preset called {cleaned!r} already exists")
        # Rebuild to keep the original position rather than moving it to
        # the end, which would make the list jump around as you rename.
        section = self._raw
        items = [
            (cleaned if key == stored else key, value)
            for key, value in section.items()
        ]
        section.clear()
        section.update(items)
        self._library.save()
        return cleaned

    def delete(self, name: str) -> None:
        stored = self.find(name)
        if stored is None:
            return
        del self._raw[stored]
        self._library.save()


class PresetLibrary:
    """Both preset lists, and the file they live in."""

    def __init__(self, path: Path | None = None, data: dict | None = None):
        self.path = path or presets_path()
        self._data: dict[str, dict[str, dict]] = data or {
            FRAMING_SECTION: {},
            OUTPUT_SECTION: {},
        }
        self.framing: PresetStore[Framing] = PresetStore(
            self, FRAMING_SECTION, Framing.from_dict
        )
        self.output: PresetStore[OutputSettings] = PresetStore(
            self, OUTPUT_SECTION, OutputSettings.from_dict
        )

    def section(self, name: str) -> dict[str, dict]:
        return self._data.setdefault(name, {})

    # --- persistence ------------------------------------------------------

    @staticmethod
    def _read_section(raw) -> dict[str, dict]:
        """Accept the on-disk list form, skipping anything malformed."""
        out: dict[str, dict] = {}
        if not isinstance(raw, list):
            return out
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name, values = entry.get("name"), entry.get("values")
            if isinstance(name, str) and isinstance(values, dict) and name.strip():
                out[name] = values
        return out

    @classmethod
    def load(cls, path: Path | None = None) -> "PresetLibrary":
        path = path or presets_path()
        try:
            with open(path, encoding="utf-8") as fh:
                document = json.load(fh)
        except FileNotFoundError:
            return cls(path)
        except (OSError, ValueError, TypeError) as exc:
            log.warning("ignoring unreadable presets at %s (%s)", path, exc)
            return cls(path)

        if not isinstance(document, dict):
            log.warning("presets at %s are not an object; ignoring", path)
            return cls(path)
        return cls(path, {
            FRAMING_SECTION: cls._read_section(document.get(FRAMING_SECTION)),
            OUTPUT_SECTION: cls._read_section(document.get(OUTPUT_SECTION)),
        })

    def to_dict(self) -> dict:
        # A list of {name, values} rather than an object, so order is explicit
        # and survives any JSON reader.
        return {
            "version": VERSION,
            **{
                section: [
                    {"name": name, "values": values}
                    for name, values in self._data.get(section, {}).items()
                ]
                for section in (FRAMING_SECTION, OUTPUT_SECTION)
            },
        }

    def save(self) -> None:
        """Written through on every change, so a crash cannot lose a preset
        that appeared to save."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, indent=2)
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("could not save presets to %s (%s)", self.path, exc)
