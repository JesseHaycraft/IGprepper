"""Android's Storage Access Framework, from Python.

Another app's storage -- Proton Drive, here -- is reached through the system
folder picker. The picker hands back a "tree" address for the folder that was
chosen; everything after that is a query or a create call against Android's
ContentResolver using that address. The app that owns the storage does the
actual work, including any upload.

This module only imports on Android.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from android.content import Intent
from java import jarray, jbyte, jclass
from java.lang import String
from org.beeware.android import MainActivity

DocumentsContract = jclass("android.provider.DocumentsContract")
Document = jclass("android.provider.DocumentsContract$Document")

DIR_MIME = "vnd.android.document/directory"
RESULT_OK = -1
READ_WRITE = (
    Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
)
LOCAL_STORAGE = "com.android.externalstorage.documents"

_COLUMNS = ["document_id", "_display_name", "mime_type", "_size", "flags"]

# What a storage app may or may not allow, in the order worth reading. The
# two lists differ because Android's "write" flag only ever applies to files;
# reporting it as refused for a folder would read as a problem when it is not.
_SHARED_CAPABILITIES = (
    ("rename", Document.FLAG_SUPPORTS_RENAME),
    ("move", Document.FLAG_SUPPORTS_MOVE),
    ("copy", Document.FLAG_SUPPORTS_COPY),
    ("delete", Document.FLAG_SUPPORTS_DELETE),
)
_FOLDER_CAPABILITIES = (
    ("create items inside", Document.FLAG_DIR_SUPPORTS_CREATE),
) + _SHARED_CAPABILITIES
_FILE_CAPABILITIES = (
    ("overwrite", Document.FLAG_SUPPORTS_WRITE),
) + _SHARED_CAPABILITIES


class StorageError(RuntimeError):
    """The storage app refused or failed an operation."""


@dataclass
class Entry:
    doc_id: str
    name: str
    is_dir: bool
    size: int | None
    flags: int

    def capabilities(self) -> dict[str, bool]:
        table = _FOLDER_CAPABILITIES if self.is_dir else _FILE_CAPABILITIES
        return {label: bool(self.flags & bit) for label, bit in table}


def resolver():
    return MainActivity.singletonThis.getContentResolver()


# --- choosing a folder ------------------------------------------------------

async def pick_folder(app, initial_uri=None):
    """Show the system folder picker; return the chosen tree, or None.

    Access is requested as persistable, and taken as such, so it survives the
    app closing and the phone restarting without a second trip through the
    picker.
    """
    intent = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
    intent.addFlags(READ_WRITE | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
    if initial_uri is not None:
        intent.putExtra("android.provider.extra.INITIAL_URI", initial_uri)

    loop = asyncio.get_event_loop()
    finished = loop.create_future()

    def on_complete(result_code, data):
        loop.call_soon_threadsafe(finished.set_result, (result_code, data))

    # Toga has no folder dialog on Android, so the picker is started through
    # the same hook its own file dialogs use.
    app._impl.start_activity(intent, on_complete=on_complete)
    result_code, data = await finished

    if result_code != RESULT_OK or data is None:
        return None
    tree = data.getData()
    resolver().takePersistableUriPermission(tree, READ_WRITE)
    return tree


def persisted_folder():
    """The most recently granted folder that is still writable, or None."""
    newest = None
    permissions = resolver().getPersistedUriPermissions()
    for i in range(permissions.size()):
        permission = permissions.get(i)
        if not permission.isWritePermission():
            continue
        if newest is None or permission.getPersistedTime() > newest.getPersistedTime():
            newest = permission
    return newest.getUri() if newest is not None else None


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


def _rows(uri) -> list[Entry]:
    cursor = resolver().query(uri, jarray(String)(_COLUMNS), None, None, None)
    if cursor is None:
        raise StorageError("The storage app returned nothing for that folder")
    entries = []
    try:
        while cursor.moveToNext():
            mime = cursor.getString(2)
            entries.append(
                Entry(
                    doc_id=str(cursor.getString(0)),
                    name=str(cursor.getString(1)),
                    is_dir=(mime == DIR_MIME),
                    size=None if cursor.isNull(3) else int(cursor.getLong(3)),
                    flags=0 if cursor.isNull(4) else int(cursor.getInt(4)),
                )
            )
    finally:
        cursor.close()
    return entries


def describe(tree, doc_id: str) -> Entry:
    rows = _rows(_doc_uri(tree, doc_id))
    if not rows:
        raise StorageError("The storage app no longer knows that item")
    return rows[0]


def children(tree, parent_id: str) -> list[Entry]:
    uri = DocumentsContract.buildChildDocumentsUriUsingTree(tree, parent_id)
    return _rows(uri)


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
    stream = resolver().openInputStream(_doc_uri(tree, doc_id))
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
