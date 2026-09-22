import os

import pytest
from PIL import Image, ImageCms

# Set before any Qt import, so the GUI fixtures below need no display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

RED = (220, 40, 40)


@pytest.fixture
def solid():
    """A solid-colour source image of a given size."""

    def make(w=3000, h=2000, color=RED):
        return Image.new("RGB", (w, h), color)

    return make


@pytest.fixture
def gradient():
    """Detailed source, so resampling and sharpening have something to act on."""

    def make(w=1200, h=1200):
        img = Image.new("RGB", (w, h))
        px = img.load()
        for y in range(h):
            for x in range(w):
                px[x, y] = ((x * 7) % 256, (y * 5) % 256, ((x + y) * 3) % 256)
        return img

    return make


@pytest.fixture
def warm_profile_bytes():
    """A real, valid RGB profile that is not sRGB.

    Built by shifting sRGB's white point, which gives a profile whose
    transform to sRGB measurably moves pixel values.
    """
    return ImageCms.ImageCmsProfile(
        ImageCms.createProfile("sRGB", 5000)
    ).tobytes()


def write_jpeg(img, path, **kw):
    img.save(path, "JPEG", quality=98, **kw)
    return path


@pytest.fixture
def jpeg_file(tmp_path):
    def make(img, name="src.jpg", **kw):
        return write_jpeg(img, tmp_path / name, **kw)

    return make


# --- shared GUI fixtures ---------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def photos(tmp_path):
    def make(count=3, w=3000, h=2000):
        paths = []
        for i in range(count):
            p = tmp_path / f"shot_{i}.jpg"
            Image.new("RGB", (w, h), (30 * i + 40, 90, 160)).save(p)
            paths.append(p)
        return paths

    return make


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    from igprep.core.settings import Settings
    from igprep.gui.main import MainWindow

    # Never touch the real user config during tests -- both files, since
    # presets resolve their own path independently of settings.
    monkeypatch.setattr(
        "igprep.core.settings.config_path", lambda: tmp_path / "settings.json"
    )
    monkeypatch.setattr(
        "igprep.core.presets.presets_path", lambda: tmp_path / "presets.json"
    )
    win = MainWindow()
    win.settings = Settings()
    win.batch.load(win.settings)
    win.framing.load(win.settings.framing, win.settings.output.output_width)
    yield win
    win.close()


@pytest.fixture
def dialogs(monkeypatch):
    """Stub the preset bar's modal dialogs and record what it asked."""
    state = {"text": "", "ok": True, "confirm": True, "warnings": []}

    class FakeInput:
        @staticmethod
        def getText(*args, **kwargs):
            return state["text"], state["ok"]

    class FakeBox:
        class StandardButton:
            Yes = True
            No = False

        @staticmethod
        def question(*args, **kwargs):
            return state["confirm"]

        @staticmethod
        def warning(*args, **kwargs):
            state["warnings"].append(args[-1] if args else "")

    monkeypatch.setattr("igprep.gui.preset_bar.QInputDialog", FakeInput)
    monkeypatch.setattr("igprep.gui.preset_bar.QMessageBox", FakeBox)
    return state
