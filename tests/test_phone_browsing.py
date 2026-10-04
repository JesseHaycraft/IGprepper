"""The phone app's folder browsing, run on the desktop: what counts as a
photo, the order of a listing, remembering folders, and fetching thumbnails."""

import asyncio
import sys
import threading
from pathlib import Path

import pytest

PHONE_SRC = Path(__file__).resolve().parents[1] / "phone" / "src"
sys.path.insert(0, str(PHONE_SRC))

from igprepper import entries, places, words  # noqa: E402
from igprepper.entries import Entry  # noqa: E402
from igprepper.thumbs import Thumbnails  # noqa: E402


def folder(name, doc_id=None):
    return Entry(doc_id or name, name, True, None, 8, entries.DIR_MIME, 0)


def file(name, mime="", modified=0, flags=0, doc_id=None):
    return Entry(doc_id or name, name, False, 100, flags, mime, modified)


# --- what counts as a photo ---------------------------------------------------

@pytest.mark.parametrize("mime", sorted(entries.PHOTO_TYPES))
def test_known_picture_types_are_photos(mime):
    assert file("whatever", mime).is_photo


@pytest.mark.parametrize(
    "name", ["a.jpg", "A.JPG", "b.jpeg", "c.png", "d.webp", "e.HEIC", "f.heif"]
)
def test_a_photo_is_known_by_its_name_when_its_type_is_not_given(name):
    assert file(name, "application/octet-stream").is_photo
    assert file(name, "").is_photo


@pytest.mark.parametrize(
    "name,mime",
    [
        ("notes.txt", "text/plain"),
        ("clip.mp4", "video/mp4"),
        ("anim.gif", "image/gif"),
        ("raw.dng", "image/x-adobe-dng"),
        ("jpg", ""),
        ("archive.jpg.zip", "application/zip"),
    ],
)
def test_other_files_are_not_photos(name, mime):
    assert not file(name, mime).is_photo


def test_a_folder_is_never_a_photo_whatever_it_is_called():
    assert not folder("holiday.jpg").is_photo


def test_thumbnail_flag_is_read_from_the_storage_apps_flags():
    assert file("a.jpg", flags=1).has_thumbnail
    assert file("a.jpg", flags=1 | 2 | 4).has_thumbnail
    assert not file("a.jpg", flags=2 | 4).has_thumbnail


def test_capabilities_differ_for_files_and_folders():
    assert "overwrite" in file("a.jpg").capabilities()
    assert "create items inside" in folder("a").capabilities()
    assert folder("a").capabilities()["create items inside"] is True


# --- the order of a listing -----------------------------------------------------

def test_folders_come_first_by_name_then_files_newest_first():
    listing = [
        file("old.jpg", modified=100),
        folder("zebra"),
        file("new.jpg", modified=300),
        folder("Apple"),
        file("middle.txt", modified=200),
        folder("mango"),
    ]
    assert [e.name for e in entries.ordered(listing)] == [
        "Apple", "mango", "zebra", "new.jpg", "middle.txt", "old.jpg",
    ]


def test_files_without_a_date_fall_back_to_their_names():
    listing = [file("b.jpg"), file("C.jpg"), file("a.jpg"), file("dated.jpg", modified=5)]
    assert [e.name for e in entries.ordered(listing)] == [
        "dated.jpg", "a.jpg", "b.jpg", "C.jpg",
    ]


def test_ordering_leaves_the_original_list_alone():
    listing = [file("b.jpg"), folder("a")]
    entries.ordered(listing)
    assert [e.name for e in listing] == ["b.jpg", "a"]


# --- what is checked ----------------------------------------------------------------

def test_chosen_photos_come_out_in_the_order_listed():
    listing = entries.ordered(
        [file("1.jpg", modified=1), file("2.jpg", modified=2), file("3.jpg", modified=3)]
    )
    picked = entries.chosen(listing, {"1.jpg", "3.jpg"})
    assert [e.name for e in picked] == ["3.jpg", "1.jpg"]


def test_only_photos_can_be_chosen_even_if_something_else_was_marked():
    listing = [file("a.jpg"), file("notes.txt"), folder("sub")]
    assert [e.name for e in entries.chosen(listing, {"a.jpg", "notes.txt", "sub"})] == ["a.jpg"]


def test_a_check_does_not_outlive_its_file():
    listing = [file("a.jpg"), file("b.jpg")]
    assert entries.still_there(listing, {"a.jpg", "gone.jpg"}) == {"a.jpg"}
    assert entries.still_there([], {"a.jpg"}) == set()


def test_tally_counts_without_naming():
    listing = [folder("x"), folder("y"), file("a.jpg"), file("b.png"), file("c.txt")]
    assert entries.tally(listing) == (2, 2, 1)


def test_selected_wording():
    assert words.selected(1) == "1 selected"
    assert words.selected(3) == "3 selected"


# --- remembering the folders ------------------------------------------------------

def test_places_survive_being_saved_and_loaded(tmp_path):
    path = tmp_path / "deep" / "places.json"
    before = {
        "input": places.Place("content://a/tree/1", [("1", "Camera")]),
        "output": places.Place(
            "content://b/tree/2", [("2", "Photos"), ("2/x", "Édits & more")]
        ),
    }
    places.save(path, before)
    assert places.load(path) == before
    assert not path.with_suffix(".part").exists()


def test_a_side_with_no_folder_is_simply_absent(tmp_path):
    path = tmp_path / "places.json"
    places.save(path, {"input": places.Place(), "output": places.Place("content://b")})
    loaded = places.load(path)
    assert loaded["input"] == places.Place()
    assert loaded["output"].tree == "content://b" and loaded["output"].trail == []


def test_no_file_means_no_folders(tmp_path):
    assert places.load(tmp_path / "missing.json") == {
        "input": places.Place(), "output": places.Place(),
    }


@pytest.mark.parametrize(
    "contents",
    ["", "not json", "[]", '{"input": 5}', '{"input": {"tree": 7}}', '{"output": null}'],
)
def test_a_damaged_file_is_treated_as_no_file(tmp_path, contents):
    path = tmp_path / "places.json"
    path.write_text(contents, encoding="utf-8")
    assert places.load(path) == {"input": places.Place(), "output": places.Place()}


def test_a_damaged_trail_keeps_the_folder_and_starts_from_its_top(tmp_path):
    path = tmp_path / "places.json"
    path.write_text(
        '{"input": {"tree": "content://a", "trail": [["1", "ok"], ["broken"]]}}',
        encoding="utf-8",
    )
    assert places.load(path)["input"] == places.Place("content://a", [])


# --- thumbnails ---------------------------------------------------------------------

class Fetcher:
    """Stands in for the storage app: slow, and countable."""

    def __init__(self, missing=(), broken=()):
        self.asked: list = []
        self.missing, self.broken = set(missing), set(broken)
        self.gate = threading.Event()
        self.gate.set()
        self.busy = 0
        self.most_at_once = 0
        self.lock = threading.Lock()

    def __call__(self, key):
        with self.lock:
            self.asked.append(key)
            self.busy += 1
            self.most_at_once = max(self.most_at_once, self.busy)
        try:
            self.gate.wait(5)
            if key in self.broken:
                raise OSError("no network")
            return None if key in self.missing else f"picture of {key}"
        finally:
            with self.lock:
                self.busy -= 1


async def settle(thumbs, timeout=5.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while (thumbs.waiting or thumbs.fetching) and loop.time() < deadline:
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.02)


def run(coroutine):
    return asyncio.run(coroutine)


def test_a_picture_is_fetched_once_and_then_kept():
    async def scenario():
        arrivals = []
        fetch = Fetcher()
        thumbs = Thumbnails(asyncio.get_running_loop(), lambda: arrivals.append(1))
        thumbs.start(fetch)
        assert thumbs.get("a") is None  # not to hand yet, but sent for
        await settle(thumbs)
        assert thumbs.get("a") == "picture of a"
        assert thumbs.get("a") == "picture of a"
        assert fetch.asked == ["a"] and arrivals == [1]

    run(scenario())


def test_a_file_with_no_picture_is_not_asked_about_again():
    async def scenario():
        fetch = Fetcher(missing={"a"}, broken={"b"})
        thumbs = Thumbnails(asyncio.get_running_loop(), lambda: None)
        thumbs.start(fetch)
        thumbs.get("a"), thumbs.get("b")
        await settle(thumbs)
        assert thumbs.get("a") is None and thumbs.get("b") is None
        await settle(thumbs)
        assert sorted(fetch.asked) == ["a", "b"]

    run(scenario())


def test_asking_again_while_it_is_on_its_way_does_not_fetch_twice():
    async def scenario():
        fetch = Fetcher()
        fetch.gate.clear()
        thumbs = Thumbnails(asyncio.get_running_loop(), lambda: None)
        thumbs.start(fetch)
        for _ in range(5):
            thumbs.get("a")
            await asyncio.sleep(0.01)
        fetch.gate.set()
        await settle(thumbs)
        assert fetch.asked == ["a"]

    run(scenario())


def test_only_a_few_are_fetched_at_once_and_the_latest_shown_go_first():
    async def scenario():
        fetch = Fetcher()
        fetch.gate.clear()
        thumbs = Thumbnails(asyncio.get_running_loop(), lambda: None, at_once=2)
        thumbs.start(fetch)
        for key in "abcdef":
            thumbs.get(key)
        await asyncio.sleep(0.05)
        fetch.gate.set()
        await settle(thumbs)
        assert fetch.most_at_once <= 2
        # a and b went straight out; of the rest, the last asked for led.
        assert fetch.asked[:2] == ["a", "b"] and fetch.asked[2] == "f"
        assert sorted(fetch.asked) == list("abcdef")

    run(scenario())


def test_rows_scrolled_past_long_ago_are_dropped_from_the_queue():
    async def scenario():
        fetch = Fetcher()
        fetch.gate.clear()
        thumbs = Thumbnails(
            asyncio.get_running_loop(), lambda: None, at_once=1, backlog=3
        )
        thumbs.start(fetch)
        for key in range(10):
            thumbs.get(key)
        await asyncio.sleep(0.05)
        fetch.gate.set()
        await settle(thumbs)
        # The one in flight, and the three most recent.
        assert sorted(fetch.asked) == [0, 7, 8, 9]
        # A dropped one is fetched after all if its row comes back.
        thumbs.get(3)
        await settle(thumbs)
        assert thumbs.get(3) == "picture of 3"

    run(scenario())


def test_pictures_for_a_folder_that_was_left_are_thrown_away():
    async def scenario():
        arrivals = []
        slow = Fetcher()
        slow.gate.clear()
        thumbs = Thumbnails(asyncio.get_running_loop(), lambda: arrivals.append(1))
        thumbs.start(slow)
        thumbs.get("a")
        await asyncio.sleep(0.05)

        quick = Fetcher()
        thumbs.start(quick)  # a different folder
        slow.gate.set()
        await asyncio.sleep(0.1)
        assert "a" not in thumbs.cache and arrivals == []
        thumbs.get("a")
        await settle(thumbs)
        assert quick.asked == ["a"] and thumbs.get("a") == "picture of a"

    run(scenario())


def test_only_so_many_pictures_are_kept_and_the_least_used_go_first():
    async def scenario():
        thumbs = Thumbnails(asyncio.get_running_loop(), lambda: None, keep=3)
        thumbs.start(Fetcher())
        for key in "abc":
            thumbs.get(key)
        await settle(thumbs)
        thumbs.get("a")  # used again, so kept
        thumbs.get("d")
        await settle(thumbs)
        assert set(thumbs.cache) == {"a", "c", "d"} or set(thumbs.cache) == {"a", "b", "d"}
        assert "a" in thumbs.cache and len(thumbs.cache) == 3

    run(scenario())


def test_nothing_is_fetched_before_a_folder_is_shown():
    async def scenario():
        thumbs = Thumbnails(asyncio.get_running_loop(), lambda: None)
        assert thumbs.get("a") is None
        await asyncio.sleep(0.02)
        assert not thumbs.waiting and not thumbs.fetching

    run(scenario())
