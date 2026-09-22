import json

from igprep.core.settings import Framing, OutputSettings, Settings


# --- defaults --------------------------------------------------------------

def test_defaults_match_the_spec():
    """Opens on 3:4 portrait, fit whole photo, 30 sharpening, 1080 wide."""
    s = Settings()
    assert (s.framing.ratio, s.framing.mode) == ("3:4", "fit")
    assert (s.output.output_width, s.output.sharpen) == (1080, 30)
    assert (s.framing.border_pct, s.framing.frame_color) == (4.0, "#FFFFFF")
    assert s.output.quality == 95


def test_the_three_scopes_are_separate_objects():
    """Framing, output and loose state each live in their own place."""
    top = set(Settings.__dataclass_fields__)
    assert {"framing", "output"} <= top
    assert not top & {"ratio", "mode", "border_pct", "frame_color"}
    assert not top & {"output_width", "quality", "sharpen", "template"}
    # custom_name is content, not reusable configuration, so it is not output.
    assert "custom_name" in top
    assert "custom_name" not in OutputSettings.__dataclass_fields__


# --- Framing ---------------------------------------------------------------

def test_framing_copy_is_independent():
    """Each photo owns its framing; editing one must not touch another."""
    a = Framing(ratio="1:1")
    b = a.copy()
    b.ratio = "4:5"
    assert a.ratio == "1:1"


def test_framing_normalizes_bad_values():
    f = Framing(ratio="7:9", mode="stretch", frame_color="blue").normalized()
    assert (f.ratio, f.mode, f.frame_color) == ("3:4", "fit", "#FFFFFF")


def test_framing_border_is_capped_by_the_ratio():
    """Landscape runs out of room long before portrait does."""
    wide = Framing(ratio="1.91:1", border_pct=40).normalized()
    tall = Framing(ratio="3:4", border_pct=40).normalized()
    assert wide.border_pct < 26
    assert tall.border_pct == 40


def test_framing_max_border_is_near_proportional_across_widths():
    """Not exactly equal: the 16px minimum photo size is absolute, so it eats
    a smaller fraction of a 1440 canvas and the cap creeps up slightly."""
    f = Framing(ratio="1.91:1")
    assert f.max_border_pct(1440) > f.max_border_pct(1080)
    assert f.max_border_pct(1440) - f.max_border_pct(1080) < 0.5


def test_framing_max_border_falls_back_for_an_odd_width():
    f = Framing(ratio="3:4")
    assert f.max_border_pct(999) == f.max_border_pct(1080)


# --- persistence -----------------------------------------------------------

def test_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    original = Settings(
        framing=Framing(ratio="1:1", mode="crop", border_pct=6.5),
        output=OutputSettings(sharpen=45),
        custom_name="iceland",
    )
    original.save(path)
    loaded = Settings.load(path)
    assert loaded.framing.ratio == "1:1"
    assert loaded.framing.mode == "crop"
    assert loaded.framing.border_pct == 6.5
    assert (loaded.output.sharpen, loaded.custom_name) == (45, "iceland")


def test_missing_file_gives_defaults(tmp_path):
    assert Settings.load(tmp_path / "nope.json") == Settings()


def test_corrupt_file_gives_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json at all")
    assert Settings.load(path) == Settings()


def test_unknown_keys_are_dropped(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "output": {"sharpen": 42}, "from_a_future_version": 7,
    }))
    assert Settings.load(path).output.sharpen == 42


def test_a_settings_file_without_framing_still_loads(tmp_path):
    """Files written before framing moved onto the photo."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"quality": 88}))
    loaded = Settings.load(path)
    assert loaded.output.quality == 88
    assert loaded.framing == Framing()


def test_out_of_range_values_are_clamped():
    s = Settings(
        output=OutputSettings(quality=500, sharpen=-20, output_width=999)
    ).normalized()
    assert (s.output.quality, s.output.sharpen) == (100, 0)
    assert s.output.output_width == 1080


def test_a_broken_template_reverts_to_the_default():
    s = Settings(output=OutputSettings(template="{nonsense}")).normalized()
    assert s.output.template == "{name}_ig"


def test_a_settings_file_from_before_the_output_split_still_loads(tmp_path):
    """Older files kept these keys flat at the top level."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "quality": 88, "sharpen": 12, "output_width": 1440,
        "template": "{name}_x", "collision": "skip",
        "dest_mode": "folder", "dest_folder": "/tmp/out",
        "custom_name": "iceland",
        "framing": {"ratio": "1:1"},
    }))
    loaded = Settings.load(path)
    assert loaded.output.quality == 88
    assert loaded.output.sharpen == 12
    assert loaded.output.output_width == 1440
    assert loaded.output.template == "{name}_x"
    assert loaded.output.collision == "skip"
    assert loaded.output.dest_mode == "folder"
    assert loaded.custom_name == "iceland"
    assert loaded.framing.ratio == "1:1"


def test_save_is_atomic_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "settings.json"
    Settings().save(path)
    assert path.exists()
    assert list(tmp_path.glob("*.tmp")) == []
