"""Android's Storage Access Framework, from Python.

Another app's storage -- Google Drive, say -- is reached through the system
folder picker. The picker hands back a "tree" address for the folder that was
chosen; everything after that is a query or a create call against Android's
ContentResolver using that address. The app that owns the storage does the
actual work, including any upload.

This module only imports on Android.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from android.content import ContentValues, Intent
from java import jarray, jbyte, jclass
from java.lang import String
from org.beeware.android import MainActivity

from .entries import DIR_MIME, Entry

DocumentsContract = jclass("android.provider.DocumentsContract")
GalleryImages = jclass("android.provider.MediaStore$Images$Media")
Point = jclass("android.graphics.Point")
ThumbnailUtils = jclass("android.media.ThumbnailUtils")

RESULT_OK = -1
READ_ONLY = Intent.FLAG_GRANT_READ_URI_PERMISSION
READ_WRITE = (
    Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
)
LOCAL_STORAGE = "com.android.externalstorage.documents"

_COLUMNS = [
    "document_id", "_display_name", "mime_type", "_size", "flags", "last_modified",
]


class StorageError(RuntimeError):
    """The storage app refused or failed an operation."""


@dataclass
class Listing:
    entries: list[Entry]
    # True when the storage app handed over what it had so far and is still
    # fetching the rest, as cloud storage does for a large folder.
    loading: bool = False


def resolver():
    return MainActivity.singletonThis.getContentResolver()


# --- choosing a folder ------------------------------------------------------

async def pick_folder(app, initial_uri=None, write: bool = True):
    """Show the system folder picker; return the chosen tree, or None.

    Access is requested as persistable, and taken as such, so it survives the
    app closing and the phone restarting without a second trip through the
    picker. A folder that will only be read from is asked for read access
    alone.
    """
    access = READ_WRITE if write else READ_ONLY
    intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
    intent.addFlags(access | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
    if initial_uri is not None:
        intent.putExtra("android.provider.extra.INITIAL_URI", initial_uri)

    result_code, data = await _start(app, intent)
    if result_code != RESULT_OK or data is None:
        return None
    tree = data.getData()
    resolver().takePersistableUriPermission(tree, access)
    return tree


async def _start(app, intent):
    """Start a system screen and wait for what it hands back."""
    loop = asyncio.get_event_loop()
    finished = loop.create_future()

    def on_complete(result_code, data):
        loop.call_soon_threadsafe(finished.set_result, (result_code, data))

    # Toga has no folder dialog on Android, so system pickers are started
    # through the same hook its own file dialogs use.
    app._impl.start_activity(intent, on_complete=on_complete)
    return await finished


def _grants():
    permissions = resolver().getPersistedUriPermissions()
    return [permissions.get(i) for i in range(permissions.size())]


def held(address: str, write: bool):
    """The tree at `address` if access to it is still held, else None."""
    for grant in _grants():
        if str(grant.getUri()) != address:
            continue
        if grant.isWritePermission() if write else grant.isReadPermission():
            return grant.getUri()
    return None


def newest_writable_grant():
    """The most recently granted writable folder, or None.

    Only for versions of the app that kept no record of their own: there
    was one folder then, and this is how it was found.
    """
    newest = None
    for grant in _grants():
        if not grant.isWritePermission():
            continue
        if newest is None or grant.getPersistedTime() > newest.getPersistedTime():
            newest = grant
    return newest.getUri() if newest is not None else None


def release(address: str) -> None:
    """Give up access to a folder that is no longer either side's.

    Android allows an app only so many, and there is no reason to keep hold
    of a folder nobody is looking at.
    """
    for grant in _grants():
        if str(grant.getUri()) == address:
            flags = READ_WRITE if grant.isWritePermission() else READ_ONLY
            resolver().releasePersistableUriPermission(grant.getUri(), flags)


def address(tree) -> str:
    return str(tree)


def local_folder_uri(path: str):
    """Address of a folder on the phone's own storage, e.g. "Download/IGprepper".

    Only used to point the picker somewhere predictable during automated tests.
    """
    return DocumentsContract.buildDocumentUri(LOCAL_STORAGE, f"primary:{path}")


# --- looking -----------------------------------------------------------------

def root_id(tree) -> str:
    return DocumentsContract.getTreeDocumentId(tree)


def provider_name(tree) -> str:
    """Which app owns this storage. An app identifier, not personal data."""
    return str(tree.getAuthority())


def _doc_uri(tree, doc_id: str):
    return DocumentsContract.buildDocumentUriUsingTree(tree, doc_id)


def document_uri(tree, doc_id: str):
    """The address of one file, for reading it."""
    return _doc_uri(tree, doc_id)


def _rows(uri) -> Listing:
    cursor = resolver().query(uri, jarray(String)(_COLUMNS), None, None, None)
    if cursor is None:
        raise StorageError("The storage app returned nothing for that folder")
    entries = []
    try:
        extras = cursor.getExtras()
        loading = bool(extras is not None and extras.getBoolean("loading", False))
        while cursor.moveToNext():
            mime = cursor.getString(2)
            entries.append(
                Entry(
                    doc_id=str(cursor.getString(0)),
                    name=str(cursor.getString(1)),
                    is_dir=(mime == DIR_MIME),
                    size=None if cursor.isNull(3) else int(cursor.getLong(3)),
                    flags=0 if cursor.isNull(4) else int(cursor.getInt(4)),
                    mime="" if mime is None else str(mime),
                    modified=0 if cursor.isNull(5) else int(cursor.getLong(5)),
                )
            )
    finally:
        cursor.close()
    return Listing(entries, loading)


def describe(tree, doc_id: str) -> Entry:
    rows = _rows(_doc_uri(tree, doc_id)).entries
    if not rows:
        raise StorageError("The storage app no longer knows that item")
    return rows[0]


def listing(tree, parent_id: str) -> Listing:
    """What a folder holds, and whether the storage app is still counting."""
    uri = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parent_id)
    return _rows(uri)


def children(tree, parent_id: str) -> list[Entry]:
    return listing(tree, parent_id).entries


def thumbnail(tree, doc_id: str, side: int):
    """A small square picture of a file, from the storage app; None if it
    has none to give. Slow for cloud storage: not for the screen's thread."""
    try:
        picture = DocumentsContract.getDocumentThumbnail(
            resolver(), _doc_uri(tree, doc_id), Point(side, side), None
        )
    except Exception:
        return None
    if picture is None:
        return None
    return ThumbnailUtils.extractThumbnail(picture, side, side)


# --- creating ----------------------------------------------------------------

def _create(tree, parent_id: str, mime: str, name: str) -> Entry:
    uri = DocumentsContract.createDocument(
        resolver(), _doc_uri(tree, parent_id), mime, name
    )
    if uri is None:
        raise StorageError(f"The storage app refused to create {name!r}")
    return describe(tree, str(DocumentsContract.getDocumentId(uri)))


def create_folder(tree, parent_id: str, name: str) -> Entry:
    return _create(tree, parent_id, DIR_MIME, name)


def create_file(tree, parent_id: str, name: str, mime: str) -> Entry:
    return _create(tree, parent_id, mime, name)


# --- reading and writing ------------------------------------------------------

def write_bytes(tree, doc_id: str, data: bytes, chunk: int = 1 << 20) -> None:
    stream = resolver().openOutputStream(_doc_uri(tree, doc_id), "w")
    if stream is None:
        raise StorageError("The storage app would not open the file for writing")
    try:
        for start in range(0, len(data), chunk):
            stream.write(data[start:start + chunk])
        stream.flush()
    finally:
        stream.close()


def _to_bytes(java_bytes, count: int) -> bytes:
    """Java's bytes are signed; Python's are not."""
    try:
        return bytes(java_bytes)[:count]
    except (TypeError, ValueError):
        return bytes((b + 256) % 256 for b in list(java_bytes)[:count])


def read_bytes(tree, doc_id: str) -> bytes:
    return read_uri(_doc_uri(tree, doc_id))


def read_uri(uri) -> bytes:
    stream = resolver().openInputStream(uri)
    if stream is None:
        raise StorageError("The storage app would not open the file for reading")
    collected = bytearray()
    buffer = jarray(jbyte)(bytes(1 << 16))
    try:
        while True:
            count = stream.read(buffer)
            if count < 0:
                break
            collected += _to_bytes(buffer, count)
    finally:
        stream.close()
    return bytes(collected)


def save_to_gallery(name: str, jpeg: bytes) -> None:
    """Add a JPEG to the phone's own gallery, under Pictures/IGprepper."""
    values = ContentValues()
    values.put("_display_name", name)
    values.put("mime_type", "image/jpeg")
    values.put("relative_path", "Pictures/IGprepper")
    uri = resolver().insert(GalleryImages.EXTERNAL_CONTENT_URI, values)
    if uri is None:
        raise StorageError("Android refused to add the photo to the gallery")
    stream = resolver().openOutputStream(uri, "w")
    try:
        stream.write(jpeg)
        stream.flush()
    finally:
        stream.close()
