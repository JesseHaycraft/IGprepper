# IGprepper

[![tests](https://github.com/JesseHaycraft/IGprepper/actions/workflows/tests.yml/badge.svg)](https://github.com/JesseHaycraft/IGprepper/actions/workflows/tests.yml)

Resizes photos for Instagram and puts a white frame around them.

![IGprepper](docs/screenshot.png)

## Why

Instagram wants sRGB at 1080px wide. Upload something bigger and their servers
shrink it for you and re-compress it, with no sharpening. Upload AdobeRGB or
Display P3 and the colours come out flat, because Instagram ignores the
embedded profile.

IGprepper does the conversion and the resize itself, sharpens to make up for
the downscale, and writes 4:4:4 JPEG so there's less left for Instagram's own
compression to chew on. It also puts an identical border on every photo, which
is the tedious part to do by hand.

## Install

**Windows.** Download `IGprepper.exe` from the
[latest release](../../releases/latest) and run it. Nothing else required.

**Ubuntu / Linux.**

```bash
sudo apt install python3-venv libxcb-cursor0
git clone https://github.com/JesseHaycraft/IGprepper.git && cd IGprepper
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m igprep
```

`libxcb-cursor0` is the only system package Qt needs. Without it the window
won't open, and the app says so on startup.

**macOS.** As above, minus the apt line.

## Using it

Drop photos on the window, or pass them on the command line with
`python -m igprep photo.jpg`. Select one or more in the list, set the framing
on the right, press Process.

### Ratios

| Ratio | Pixels | |
|---|---|---|
| 1:1 | 1080 × 1080 | loses 135px a side in the grid |
| 4:5 | 1080 × 1350 | tallest the feed displays |
| 3:4 | 1080 × 1440 | default; uncropped everywhere |
| 1.91:1 | 1080 × 566 | widest allowed |
| 9:16 | 1080 × 1920 | stories and reels |

Instagram replaced its square profile grid with a 3:4 one in 2025, so 3:4 is
the only ratio that survives the feed and the grid intact. Turn on the grid
overlay to see what the others lose.

### Border

A percentage of the canvas width. Every Instagram canvas is 1080 wide, so the
same percentage produces the same pixel border at every ratio and your
portraits and landscapes match. 4% is 43px.

### Fit or crop

Fit keeps all of the photo and lets the white mat go uneven. Crop trims to the
target ratio for an even border. Set per photo.

### Presets

Two lists. Framing presets (ratio, fit, border, colour) apply to whatever is
selected. Output presets (width, quality, sharpening, destination, filename)
apply to the whole run. Choosing a preset you already have selected re-applies
it, which is how you discard edits; the dropdown reads `(modified)` when
you've drifted from it.

### Filenames

A template field taking `{name}` `{custom}` `{n}` `{ratio}` `{w}` `{h}`
`{date}` `{time}`. Pad the counter as `{n:03}`. Two buttons fill in the common
cases. Originals are never overwritten, whatever the collision setting says.

Settings and presets live in `%APPDATA%\igprep` on Windows and
`~/.config/igprep` on Linux.

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

201 tests. The GUI ones run headless, so they need no display. CI runs the lot
on Windows and Ubuntu for every push.

`igprep/core/` holds the image pipeline and imports nothing from the UI, so it
can be tested on its own. `igprep/gui/` is the PySide6 app. The order of
operations in the pipeline matters, and is written down in [SPEC.md](SPEC.md).

`python build_exe.py` builds the Windows executable. Pushing a `v*` tag makes
GitHub build it and attach it to a release.
