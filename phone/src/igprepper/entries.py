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

# Android's own flag values (DocumentsContract.Document.FLAG_*), written out
# so that this module needs nothing from Android.
SUPPORTS_THUMBNAIL = 1
_SUPPORTS_WRITE = 2
_SUPPORTS_DELETE = 4
_DIR_SUPPORTS_CREATE = 8
_SUPPORTS_RENAME = 64
_SUPPORTS_COPY = 128
_SUPPORTS_MOVE = 256

# What a storage app may or may not allow, in the order worth reading. The
# two lists differ because Android's "write" flag only ever applies to files;
# reporting it as refused for a folder would read as a problem when it is not.
_SHARED_CAPABILITIES = (
    ("rename", _SUPPORTS_RENAME),
    ("move", _SUPPORTS_MOVE),
    ("copy", _SUPPORTS_COPY),
    ("delete", _SUPPORTS_DELETE),
)
_FOLDER_CAPABILITIES = (
    ("create items inside", _DIR_SUPPORTS_CREATE),
) + _SHARED_CAPABILITIES
_FILE_CAPABILITIES = (("overwrite", _SUPPORTS_WRITE),) + _SHARED_CAPABILITIES


@dataclass
class Entry:
    doc_id: str
    name: str
    is_dir: bool
    size: int | None
    flags: int
    mime: str = ""
    modified: int = 0  # milliseconds since 1970, or 0 when the storage app does not say

    @property
    def is_photo(self) -> bool:
        """A photo this app can frame."""
        if self.is_dir:
            return False
        return self.mime in PHOTO_TYPES or self.name.lower().endswith(PHOTO_ENDINGS)

    @property
    def has_thumbnail(self) -> bool:
        """Whether the storage app offers a small picture of this file."""
        return bool(self.flags & SUPPORTS_THUMBNAIL)

    def capabilities(self) -> dict[str, bool]:
        table = _FOLDER_CAPABILITIES if self.is_dir else _FILE_CAPABILITIES
        return {label: bool(self.flags & bit) for label, bit in table}


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
