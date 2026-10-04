"""Storage that is a folder on this computer's disk.

A "tree" is a folder's path. An item inside it is known by its path from
that folder, with forward slashes; the folder itself by the empty string.

For tests: `picks` is what the folder picker will hand back next, `granted`
is what access is held, `gallery` is what was saved to the gallery, and the
sets and counters below make particular things fail or arrive slowly.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from ... import words
from ...entries import Entry, Listing, StorageError

picks: list[Path | None] = []
granted: dict[str, bool] = {}         # address -> whether it may be written to
gallery: dict[str, bytes] = {}
fail_writes: set[str] = set()         # names of files whose contents cannot be written
fail_gallery: set[str] = set()
fail_deletes: set[str] = set()
slow: dict[str, int] = {}             # folder -> how many listings come back part-done
listings = 0                          # how many times any folder has been listed

_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".txt": "text/plain",
}


def reset() -> None:
    global listings
    picks.clear(), granted.clear(), gallery.clear(), slow.clear()
    fail_writes.clear(), fail_gallery.clear(), fail_deletes.clear()
    listings = 0


def _path(tree, doc_id: str) -> Path:
    return Path(tree) / doc_id if doc_id else Path(tree)


def _entry(tree, path: Path) -> Entry:
    stat = path.stat()
    is_dir = path.is_dir()
    doc_id = "" if path == Path(tree) else path.relative_to(tree).as_posix()
    return Entry(
        doc_id=doc_id,
        name=path.name,
        is_dir=is_dir,
        size=None if is_dir else stat.st_size,
        flags=0,
        mime="" if is_dir else _TYPES.get(path.suffix.lower(), "application/octet-stream"),
        modified=stat.st_mtime_ns // 1_000_000,
    )


# --- being granted a folder ------------------------------------------------------

async def pick_folder(app, initial_uri=None, write: bool = True):
    tree = picks.pop(0) if picks else None
    if tree is not None:
        granted[address(tree)] = granted.get(address(tree), False) or write
    return tree


def held(address_: str, write: bool):
    if address_ in granted and (granted[address_] or not write):
        return Path(address_)
    return None


def newest_writable_grant():
    writable = [a for a, can_write in granted.items() if can_write]
    return Path(writable[-1]) if writable else None


def release(address_: str) -> None:
    granted.pop(address_, None)


def address(tree) -> str:
    return str(tree)


# --- looking -----------------------------------------------------------------------

def root_id(tree) -> str:
    return ""


def provider_name(tree) -> str:
    return "a folder on this computer"


def where(tree, trail) -> str:
    return words.remote_path("Disk", [name for _, name in trail])


def document_uri(tree, doc_id: str):
    return _path(tree, doc_id)


def describe(tree, doc_id: str) -> Entry:
    path = _path(tree, doc_id)
    if not path.exists():
        raise StorageError("The storage app no longer knows that item")
    return _entry(tree, path)


def listing(tree, parent_id: str) -> Listing:
    global listings
    listings += 1
    folder = _path(tree, parent_id)
    if not folder.is_dir():
        raise StorageError("The storage app returned nothing for that folder")
    found = [_entry(tree, child) for child in sorted(folder.iterdir())]
    left = slow.get(str(folder), 0)
    if left > 0:
        # As cloud storage does with a large folder: part of it now, and
        # word that there is more to come.
        slow[str(folder)] = left - 1
        return Listing(found[: len(found) // 2], loading=True)
    return Listing(found)


def children(tree, parent_id: str) -> list[Entry]:
    return listing(tree, parent_id).entries


def thumbnail(tree, doc_id: str, side: int):
    try:
        with Image.open(_path(tree, doc_id)) as picture:
            return ImageOps.fit(picture.convert("RGB"), (side, side))
    except Exception:
        return None


# --- changing things ----------------------------------------------------------------

def _free_name(folder: Path, name: str) -> Path:
    """As a storage app does when a name is taken: a number in brackets."""
    candidate, number = folder / name, 0
    stem, dot, ending = name.rpartition(".")
    while candidate.exists():
        number += 1
        candidate = folder / (
            f"{stem} ({number}).{ending}" if dot else f"{name} ({number})"
        )
    return candidate


def create_folder(tree, parent_id: str, name: str) -> Entry:
    path = _free_name(_path(tree, parent_id), name)
    path.mkdir()
    return _entry(tree, path)


def create_file(tree, parent_id: str, name: str, mime: str) -> Entry:
    path = _free_name(_path(tree, parent_id), name)
    path.touch()
    return _entry(tree, path)


def write_bytes(tree, doc_id: str, data: bytes) -> None:
    path = _path(tree, doc_id)
    if path.name in fail_writes:
        raise StorageError("The storage app would not open the file for writing")
    path.write_bytes(data)


def delete(tree, doc_id: str) -> None:
    path = _path(tree, doc_id)
    if path.name in fail_deletes:
        raise StorageError("The storage app would not delete that file")
    path.unlink()


def read_uri(uri) -> bytes:
    return Path(uri).read_bytes()


def save_to_gallery(name: str, jpeg: bytes) -> None:
    if name in fail_gallery:
        raise StorageError("Android would not open the gallery for writing")
    gallery[name] = jpeg
