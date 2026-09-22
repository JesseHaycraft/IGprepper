"""Launching the app: file arguments and the Linux library check."""

import os
import sys

from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from igprep.gui.main import (  # noqa: E402
    file_arguments, warn_if_qt_libs_missing,
)


# --- file arguments --------------------------------------------------------

def test_existing_files_are_collected(tmp_path):
    a = tmp_path / "a.jpg"
    Image.new("RGB", (10, 10)).save(a)
    assert file_arguments(["igprep", str(a)]) == [a]


def test_the_program_name_is_skipped(tmp_path):
    assert file_arguments([str(tmp_path)]) == []


def test_missing_files_are_ignored(tmp_path):
    assert file_arguments(["igprep", str(tmp_path / "nope.jpg")]) == []


def test_options_are_ignored(tmp_path):
    a = tmp_path / "a.jpg"
    Image.new("RGB", (10, 10)).save(a)
    args = ["igprep", "--style", "fusion", str(a)]
    assert file_arguments(args) == [a]


def test_no_arguments_gives_nothing():
    assert file_arguments(["igprep"]) == []


def test_opening_paths_fills_the_queue(window, photos):
    """What "Open with" and a .desktop launcher end up calling."""
    window.open_paths(photos(2))
    assert window.queue.rowCount() == 2


def test_opening_a_folder_adds_the_photos_inside(window, photos, tmp_path):
    photos(2)
    window.open_paths([tmp_path])
    assert window.queue.rowCount() == 2


# --- the Linux library warning ---------------------------------------------

def test_silent_on_windows_and_mac(monkeypatch, capsys):
    for platform in ("win32", "darwin"):
        monkeypatch.setattr(sys, "platform", platform)
        warn_if_qt_libs_missing()
    assert capsys.readouterr().err == ""


def test_silent_when_the_platform_is_already_chosen(monkeypatch, capsys):
    """Offscreen and Wayland runs do not need the X11 library."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr("ctypes.util.find_library", lambda name: None)
    warn_if_qt_libs_missing()
    assert capsys.readouterr().err == ""


def test_names_the_package_to_install(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr("ctypes.util.find_library", lambda name: None)
    warn_if_qt_libs_missing()

    err = capsys.readouterr().err
    assert "libxcb-cursor0" in err
    assert "apt install" in err


def test_silent_when_the_library_is_present(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setattr(
        "ctypes.util.find_library", lambda name: "libxcb-cursor.so.0"
    )
    warn_if_qt_libs_missing()
    assert capsys.readouterr().err == ""
