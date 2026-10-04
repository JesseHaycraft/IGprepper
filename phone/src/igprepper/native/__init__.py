"""What the app needs from the phone it is running on.

The two screens are written against the toolkit and know nothing of any
particular phone. Everything that has to be asked of the phone itself comes
through here, as six modules:

    storage    folders: being granted one, listing, reading, writing
    decoder    turning a photo's bytes into an sRGB picture
    filelist   the scrolling list and tiles of a folder's contents
    touch      fingers on the preview, and drawing under them quickly
    ui         the pieces of the screen the toolkit has no word for
    log        where the log file lives

`android/` supplies them for Android. `fake/` supplies them for a desk: a
folder on disk for storage, lists that only remember what they were told,
and so on, so that the screens can be run and tested without a phone.

A version for another kind of phone is a third folder that offers the same
names. Whatever `android/` offers that the shared code uses is the whole of
what it must supply.
"""

from __future__ import annotations

import os
import sys

if hasattr(sys, "getandroidapilevel") or "ANDROID_ROOT" in os.environ:
    from .android import decoder, filelist, log, storage, touch, ui
else:
    from .fake import decoder, filelist, log, storage, touch, ui

__all__ = ["decoder", "filelist", "log", "storage", "touch", "ui"]
