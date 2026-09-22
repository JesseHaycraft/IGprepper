from datetime import datetime

import pytest
from PIL import Image

from igprep.core import naming
from igprep.core.pipeline import Job, iter_images, plan, probe, process
from igprep.core.settings import Framing, OutputSettings, Settings


@pytest.fixture
def photo(tmp_path):
    def make(name="DSC_0042.jpg", w=3000, h=2000, **kw):
        path = tmp_path / name
        Image.new("RGB", (w, h), (200, 90, 60)).save(path, **kw)
        return path

    return make


# --- discovery -------------------------------------------------------------

def test_iter_images_filters_by_extension(tmp_path, photo):
    photo("a.jpg")
    photo("b.png")
    (tmp_path / "notes.txt").write_text("hi")
    (tmp_path / "movie.mp4").write_text("nope")
    assert [p.name for p in iter_images([tmp_path])] == ["a.jpg", "b.png"]


def test_iter_images_walks_folders_and_dedupes(tmp_path, photo):
    photo("a.jpg")
    sub = tmp_path / "sub"
    sub.mkdir()
    Image.new("RGB", (10, 10)).save(sub / "c.jpg")
    found = iter_images([tmp_path, tmp_path / "a.jpg"])
    assert [p.name for p in found] == ["a.jpg", "c.jpg"]


def test_iter_images_ignores_unsupported_raw(tmp_path):
    (tmp_path / "shot.cr2").write_bytes(b"raw")
    assert iter_images([tmp_path]) == []


# --- probing ---------------------------------------------------------------

def test_probe_reports_oriented_size(tmp_path):
    exif = Image.Exif()
    exif[274] = 6  # 90 degree rotation: dimensions swap on display
    path = tmp_path / "rot.jpg"
    Image.new("RGB", (3000, 2000)).save(path, exif=exif)
    assert probe(path).size == (2000, 3000)


def test_probe_reads_capture_time_from_exif(tmp_path):
    exif = Image.Exif()
    exif.get_ifd(0x8769)[36867] = "2026:09:22 14:05:09"
    path = tmp_path / "dated.jpg"
    Image.new("RGB", (100, 100)).save(path, exif=exif)
    assert probe(path).captured == datetime(2026, 9, 22, 14, 5, 9)


def test_probe_falls_back_to_file_time(photo):
    assert isinstance(probe(photo()).captured, datetime)


# --- planning --------------------------------------------------------------

def test_plan_resolves_name_and_layout(photo):
    p = photo()
    preview = plan(Job(p), Settings())
    assert preview.output.name == "DSC_0042_ig.jpg"
    assert preview.output.parent == p.parent
    assert preview.layout.canvas == (1080, 1440)


def test_each_photo_carries_its_own_framing(photo):
    """Framing lives on the job, not on the batch settings."""
    square = Job(photo("a.jpg"), framing=Framing(ratio="1:1", mode="fit"))
    tall = Job(photo("b.jpg"), framing=Framing(ratio="3:4", mode="crop"))
    settings = Settings()

    assert plan(square, settings).layout.canvas == (1080, 1080)
    assert plan(square, settings).layout.crop is None
    assert plan(tall, settings).layout.canvas == (1080, 1440)
    assert plan(tall, settings).layout.crop is not None


def test_border_and_colour_are_per_photo(photo):
    thin = Job(photo("a.jpg"), framing=Framing(border_pct=2.0))
    thick = Job(photo("b.jpg"), framing=Framing(border_pct=10.0))
    settings = Settings()
    assert plan(thin, settings).layout.border == 22
    assert plan(thick, settings).layout.border == 108


def test_encoding_width_stays_batch_wide(photo):
    """Width is a batch setting, so it reframes every photo at once."""
    job = Job(photo(), framing=Framing(ratio="1:1"))
    assert plan(job, Settings(output=OutputSettings(output_width=1080))).layout.canvas == (1080, 1080)
    assert plan(job, Settings(output=OutputSettings(output_width=1440))).layout.canvas == (1440, 1440)


def test_plan_warns_when_the_source_is_too_small(photo):
    preview = plan(Job(photo("small.jpg", 400, 400)), Settings())
    assert preview.layout.upscaled
    assert any("enlarged" in w for w in preview.warnings)


def test_plan_uses_the_destination_folder(tmp_path, photo):
    out = tmp_path / "exports"
    s = Settings(output=OutputSettings(dest_mode="folder", dest_folder=str(out)))
    assert plan(Job(photo()), s).output.parent == out


def test_batch_numbering_flows_through_the_template(photo):
    s = Settings(output=OutputSettings(template=naming.PRESET_CUSTOM),
                 custom_name="iceland")
    names = [plan(Job(photo()), s, index=i).output.name for i in (1, 2, 12)]
    assert names == ["iceland_001.jpg", "iceland_002.jpg", "iceland_012.jpg"]


# --- processing ------------------------------------------------------------

def test_process_writes_a_correct_file(photo):
    result = process(Job(photo()), Settings())
    assert result.ok and result.output.exists()
    with Image.open(result.output) as out:
        assert out.size == (1080, 1440)
        assert out.format == "JPEG"


def test_process_never_overwrites_the_source(tmp_path):
    """Template resolving to the source name must not destroy the original."""
    src = tmp_path / "photo.jpg"
    Image.new("RGB", (3000, 2000), (10, 200, 10)).save(src)
    before = src.read_bytes()

    result = process(Job(src), Settings(output=OutputSettings(template="{name}")))
    assert result.ok
    assert result.output != src
    assert src.read_bytes() == before


def test_collision_increments_by_default(photo):
    p = photo()
    first = process(Job(p), Settings())
    second = process(Job(p), Settings())
    assert first.output.name == "DSC_0042_ig.jpg"
    assert second.output.name == "DSC_0042_ig_2.jpg"


def test_collision_skip_leaves_the_existing_file(photo):
    p = photo()
    first = process(Job(p), Settings())
    stamp = first.output.read_bytes()
    second = process(Job(p), Settings(output=OutputSettings(collision="skip")))
    assert second.skipped and second.output is None
    assert first.output.read_bytes() == stamp


def test_collision_overwrite_replaces_it(photo):
    p = photo()
    first = process(Job(p), Settings())
    second = process(Job(p), Settings(output=OutputSettings(collision="overwrite")))
    assert second.output == first.output


def test_process_creates_a_missing_destination_folder(tmp_path, photo):
    out = tmp_path / "new" / "nested"
    s = Settings(output=OutputSettings(dest_mode="folder", dest_folder=str(out)))
    assert process(Job(photo()), s).ok
    assert out.is_dir()


def test_a_corrupt_file_reports_an_error_without_raising(tmp_path):
    bad = tmp_path / "broken.jpg"
    bad.write_bytes(b"this is not a jpeg")
    result = process(Job(bad), Settings())
    assert not result.ok and result.error


def test_a_missing_file_reports_an_error(tmp_path):
    result = process(Job(tmp_path / "gone.jpg"), Settings())
    assert not result.ok and result.error
