"""The phone app's log, exercised off the phone.

On a desktop the Android imports fail, and the log falls back to a plain file.
That is enough to check everything except the Android storage calls
themselves, which only a real phone can prove.
"""

import sys
from pathlib import Path

import pytest

PHONE_SRC = Path(__file__).resolve().parents[1] / "phone" / "src"
sys.path.insert(0, str(PHONE_SRC))

from igprepper.phonelog import PhoneLog  # noqa: E402


@pytest.fixture
def log(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    return PhoneLog()


def _file_text(log):
    return Path(log.location).read_text(encoding="utf-8")


def test_falls_back_to_a_plain_file_off_the_phone(log, tmp_path):
    assert Path(log.location).parent == tmp_path
    assert Path(log.location).name.startswith("igprepper-log-")


def test_each_line_reaches_the_file_immediately(log):
    """No buffering: a crash must leave everything written so far."""
    log.write("first")
    assert "first" in _file_text(log)
    log.write("second")
    assert _file_text(log).count("\n") == 2


def test_lines_are_timestamped(log):
    log.write("hello")
    assert log.lines[-1][2] == ":" and log.lines[-1].endswith("  hello")


def test_multi_line_messages_keep_their_line_breaks(log):
    log.write("one\ntwo")
    assert [line.split("  ", 1)[1] for line in log.lines[-2:]] == ["one", "two"]


def test_exception_records_what_was_being_attempted(log):
    try:
        raise ValueError("bad folder name")
    except ValueError:
        log.exception("creating a folder")
    text = _file_text(log)
    assert "FAILED while creating a folder" in text
    assert "ValueError: bad folder name" in text


def test_uncaught_errors_are_logged(log, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", lambda *args: None)
    log.install_excepthook()
    try:
        raise KeyError("boom")
    except KeyError:
        sys.excepthook(*sys.exc_info())
    assert "UNCAUGHT ERROR" in _file_text(log)
    assert "KeyError" in _file_text(log)


def test_a_file_that_stops_accepting_writes_does_not_raise(log, monkeypatch):
    log.write("before")
    log._sink.path = Path(log.location).parent / "no" / "such" / "dir" / "log.txt"
    log.write("after")  # must not raise
    assert "stopped accepting writes" in log.location
    assert any("after" in line for line in log.lines)
