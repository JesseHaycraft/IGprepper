import json

import pytest

from igprep.core.presets import (
    VERSION, PresetError, PresetLibrary, clean_name,
)
from igprep.core.settings import Framing, OutputSettings


@pytest.fixture
def library(tmp_path):
    return PresetLibrary(tmp_path / "presets.json")


# --- names -----------------------------------------------------------------

def test_names_are_trimmed_and_collapsed():
    assert clean_name("  Gallery   mat  ") == "Gallery mat"


@pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
def test_blank_names_are_rejected(bad):
    with pytest.raises(PresetError):
        clean_name(bad)


def test_overlong_names_are_rejected():
    with pytest.raises(PresetError):
        clean_name("x" * 200)


def test_any_character_is_allowed(library):
    """Names never reach the filesystem, so nothing needs sanitising."""
    awkward = 'A/B:C*D? <>|"\\'
    library.framing.save(awkward, Framing(ratio="1:1"))
    assert library.framing.get(awkward).ratio == "1:1"


# --- basic operations ------------------------------------------------------

def test_starts_empty(library):
    assert library.framing.names() == []
    assert library.output.names() == []


def test_save_and_get(library):
    library.framing.save("Square", Framing(ratio="1:1", border_pct=6.0))
    got = library.framing.get("Square")
    assert (got.ratio, got.border_pct) == ("1:1", 6.0)


def test_the_two_lists_are_independent(library):
    library.framing.save("Mine", Framing(ratio="1:1"))
    library.output.save("Mine", OutputSettings(quality=80))
    assert library.framing.names() == ["Mine"]
    assert library.output.names() == ["Mine"]
    assert library.framing.get("Mine").ratio == "1:1"
    assert library.output.get("Mine").quality == 80


def test_get_returns_none_for_an_unknown_name(library):
    assert library.framing.get("nope") is None


def test_saving_the_same_name_overwrites(library):
    library.framing.save("A", Framing(ratio="1:1"))
    library.framing.save("A", Framing(ratio="4:5"))
    assert library.framing.names() == ["A"]
    assert library.framing.get("A").ratio == "4:5"


def test_names_are_case_insensitive(library):
    """"Square" and "square" as separate presets would just be confusing."""
    library.framing.save("Square", Framing(ratio="1:1"))
    library.framing.save("square", Framing(ratio="4:5"))
    assert library.framing.names() == ["square"]
    assert library.framing.get("SQUARE").ratio == "4:5"


def test_order_is_preserved(library):
    for name in ("C", "A", "B"):
        library.framing.save(name, Framing())
    assert library.framing.names() == ["C", "A", "B"]


def test_rename_keeps_the_position(library):
    for name in ("A", "B", "C"):
        library.framing.save(name, Framing())
    library.framing.rename("B", "Bee")
    assert library.framing.names() == ["A", "Bee", "C"]


def test_rename_onto_an_existing_name_is_rejected(library):
    library.framing.save("A", Framing())
    library.framing.save("B", Framing())
    with pytest.raises(PresetError):
        library.framing.rename("A", "B")


def test_rename_to_a_different_case_of_itself_is_allowed(library):
    library.framing.save("square", Framing())
    library.framing.rename("square", "Square")
    assert library.framing.names() == ["Square"]


def test_rename_of_a_missing_preset_is_rejected(library):
    with pytest.raises(PresetError):
        library.framing.rename("nope", "something")


def test_delete(library):
    library.framing.save("A", Framing())
    library.framing.delete("A")
    assert library.framing.names() == []


def test_deleting_something_absent_is_harmless(library):
    library.framing.delete("nope")
    assert library.framing.names() == []


# --- persistence -----------------------------------------------------------

def test_written_through_on_every_change(tmp_path):
    path = tmp_path / "presets.json"
    library = PresetLibrary(path)
    library.framing.save("A", Framing(ratio="1:1"))
    assert path.exists(), "a saved preset must survive an immediate crash"


def test_round_trip(tmp_path):
    path = tmp_path / "presets.json"
    first = PresetLibrary(path)
    first.framing.save("Look", Framing(ratio="4:5", mode="crop", border_pct=7.5))
    first.output.save("Web", OutputSettings(quality=82, template="{name}_web"))

    second = PresetLibrary.load(path)
    look = second.framing.get("Look")
    web = second.output.get("Web")
    assert (look.ratio, look.mode, look.border_pct) == ("4:5", "crop", 7.5)
    assert (web.quality, web.template) == (82, "{name}_web")


def test_saved_file_records_its_version(tmp_path):
    path = tmp_path / "presets.json"
    PresetLibrary(path).framing.save("A", Framing())
    assert json.loads(path.read_text())["version"] == VERSION


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "presets.json"
    PresetLibrary(path).framing.save("A", Framing())
    assert list(tmp_path.glob("*.tmp")) == []


def test_missing_file_gives_empty_lists(tmp_path):
    library = PresetLibrary.load(tmp_path / "nope.json")
    assert library.framing.names() == []


def test_corrupt_file_gives_empty_lists_without_raising(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text("{not json at all")
    library = PresetLibrary.load(path)
    assert library.framing.names() == []
    assert library.output.names() == []


def test_a_json_document_of_the_wrong_shape_is_ignored(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text(json.dumps(["not", "an", "object"]))
    assert PresetLibrary.load(path).framing.names() == []


def test_malformed_entries_are_skipped_but_good_ones_survive(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text(json.dumps({
        "version": 1,
        "framing": [
            {"name": "Good", "values": {"ratio": "1:1"}},
            {"name": "", "values": {"ratio": "4:5"}},
            {"name": "NoValues"},
            "not even a dict",
        ],
    }))
    library = PresetLibrary.load(path)
    assert library.framing.names() == ["Good"]


def test_a_preset_naming_a_ratio_that_no_longer_exists_degrades(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text(json.dumps({
        "version": 1,
        "framing": [{"name": "Old", "values": {"ratio": "7:9", "mode": "fit"}}],
    }))
    got = PresetLibrary.load(path).framing.get("Old")
    assert got.ratio == "3:4"  # fell back rather than raising


def test_unknown_keys_in_a_preset_are_dropped(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text(json.dumps({
        "version": 1,
        "framing": [{"name": "A", "values": {"ratio": "1:1", "future": 7}}],
    }))
    assert PresetLibrary.load(path).framing.get("A").ratio == "1:1"
