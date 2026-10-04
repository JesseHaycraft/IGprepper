"""What a folder holds, and what the app makes of it.

One `Entry` is one file or folder as the storage app describes it. Which of
them count as photos, and the order they are listed in, is decided here.

Nothing here is Android-specific; the desktop test suite runs it.
"""

from __future__ import annotations

from dataclasses import dataclass

DIR_MIME = "vnd.android.document/directory"

# What Android's decoder turns into a picture and this app has a use for.
PHOTO_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
)
# Storage apps do not always know a file's type; its name usually does.
PHOTO_ENDINGS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif")

@dataclass
class Entry:
    doc_id: str
    name: str
    is_dir: bool
    size: int | None
    flags: int  # what the storage app says may be done with it, as it gave them
    mime: str = ""
    modified: int = 0  # milliseconds since 1970, or 0 when the storage app does not say

    @property
    def is_photo(self) -> bool:
        """A photo this app can frame."""
        if self.is_dir:
            return False
        return self.mime in PHOTO_TYPES or self.name.lower().endswith(PHOTO_ENDINGS)



def ordered(entries: list[Entry]) -> list[Entry]:
    """Folders first, by name; then files, newest first.

    Newest first because the photo wanted is usually the one just taken, and
    the file just saved is the one worth seeing appear.
    """
    folders = sorted((e for e in entries if e.is_dir), key=lambda e: e.name.lower())
    files = sorted(
        (e for e in entries if not e.is_dir),
        key=lambda e: (-e.modified, e.name.lower()),
    )
    return folders + files


def chosen(entries: list[Entry], checked: set[str]) -> list[Entry]:
    """The checked photos, in the order they are listed."""
    return [e for e in entries if e.doc_id in checked and e.is_photo]


def still_there(entries: list[Entry], checked: set[str]) -> set[str]:
    """`checked`, less anything a fresh listing no longer contains."""
    return checked & {e.doc_id for e in entries if e.is_photo}


def tally(entries: list[Entry]) -> tuple[int, int, int]:
    """How many folders, photos and other files: all a log needs to know."""
    folders = sum(1 for e in entries if e.is_dir)
    photos = sum(1 for e in entries if e.is_photo)
    return folders, photos, len(entries) - folders - photos
