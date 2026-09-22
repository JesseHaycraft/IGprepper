# IGprepper — Spec

Desktop app that takes high-quality photos, resizes them for Instagram with a
consistent white frame, and writes upload-ready JPEGs.

Status: **implemented.** See README.md to run it.

---

## 1. Target canvases

All output is a fixed Instagram canvas. Width is 1080 by default (1440 opt-in).

| Ratio | 1080 width | 1440 width | Notes |
|---|---|---|---|
| 1:1 square | 1080 × 1080 | 1440 × 1440 | |
| 4:5 portrait | 1080 × 1350 | 1440 × 1800 | Tallest the feed displays |
| 3:4 portrait | 1080 × 1440 | 1440 × 1920 | **Default.** Only ratio uncropped in both feed and profile grid |
| 1.91:1 landscape | 1080 × 566 | 1440 × 755 | Widest allowed |
| 9:16 story/reel | 1080 × 1920 | 1440 × 2560 | Separate surface, not feed |

**Why 1080 by default:** organic uploads wider than 1080 get downscaled and
recompressed server-side. Doing the downscale ourselves with Lanczos plus
controlled sharpening beats handing that to Instagram's resampler.

**Why 3:4 is the default ratio:** Instagram dropped the square profile grid in
2025 in favour of ~3:4 thumbnails. 3:4 survives both surfaces intact.

**Which way the grid crops.** 3:4 is *taller* relative to its width
(h = 1.333w) than 4:5 (h = 1.25w) or 1:1, so a feed post shown in a 3:4 grid
slot keeps its full height and loses its **sides** -- 33px per side for 4:5,
135px per side for 1:1. Only 9:16, which is taller than 3:4, loses its top and
bottom. The general rule the code implements is the largest centred 3:4
rectangle that fits inside the canvas, which handles every case.

---

## 2. Processing pipeline

Order matters. Each step exists for a reason.

1. **Open, apply EXIF orientation.** Before anything else, so dimensions are real.
2. **Convert ICC profile → sRGB.** Camera and Lightroom exports are often
   AdobeRGB or Display P3. Instagram assumes sRGB and does not reliably honour
   embedded profiles — skipping this is the main cause of "my colours went flat
   after uploading." Assume sRGB if no profile is embedded.
3. **Compute geometry.** Canvas = ratio × output width. Photo box = canvas
   inset by the border on all four sides.
4. **Crop or fit** (per-photo toggle, see §4).
5. **Single-step Lanczos resize** to the photo box. One step, never iterative.
6. **Unsharp mask.** Downscaling always softens. Starting values: radius 0.8,
   amount 60%, threshold 2, with amount scaled by the downscale factor.
   Exposed as a 0–100 slider, and can be switched off.
7. **Composite onto the frame canvas.**
8. **Strip metadata, embed sRGB.**
9. **Save JPEG:** quality 95, 4:4:4 chroma subsampling, optimized, baseline.
   4:4:4 matters because Instagram recompresses — starting from 4:2:0 compounds
   colour-edge artifacts.

Resampling happens in gamma space (matching Photoshop and Lightroom) rather
than linear light. Linear is more technically correct but renders noticeably
differently from what the user is used to seeing. Possible advanced flag later.

---

## 3. Border model

- Thickness is a **percentage of canvas width**. Default **4%** (43px at 1080).
- Because every Instagram canvas is the same width, this yields an identical
  pixel border on every ratio — portraits and landscapes look identically
  framed side by side in the grid.
- **Per photo**, like the rest of the framing. Consistency across a grid is
  still the goal, but it is achieved by leaving the border alone or by using
  *Apply this framing to all photos*, rather than by making it un-editable.
- The UI caps the control at **15%**. Geometry allows far more -- nearly half
  the width on tall ratios -- but a border that thick is not a photograph any
  more, and allowing it buries the useful 2-8% range in the first tenth of the
  slider. `geometry.max_border_pct` still enforces the real limit.
- Border is drawn *inside* the canvas: output dimensions are always exactly the
  target canvas size, and the photo shrinks to accommodate the frame.
- Colour: pure white `#FFFFFF` default, with a colour picker. Worth trying
  ~`#FAFAFA` — pure white glows against Instagram's dark mode.

---

## 4. Crop vs fit

**Per photo**, edited in the framing panel and shown read-only in the list.
Center-only; no pan or zoom. The default is **fit**.

- **Crop** — center-crop the source to the photo box's ratio, then fill it.
  Uniform border on all four sides. Loses some edges of the photo.
- **Fit** — scale the whole photo to fit inside the photo box. Nothing is lost;
  white fills the remainder, so the mat is thicker on two sides.

Each queue row also overrides the target ratio, defaulting to the global choice.

**Upscale warning:** flag any row whose source is too small to fill the photo
box without enlargement.

---

## 5. Output naming

One template engine, with preset buttons rather than separate modes.

Presets:
- *Append suffix* → `{name}_ig`
- *Custom name* → `{custom}_{n:03}`

Tokens: `{name}` `{custom}` `{n}` (paddable, `{n:03}`) `{ratio}` `{w}` `{h}`
`{date}` `{time}`

Destination: user-specified folder, or the source photo's own folder.

**Collisions:** auto-increment by default (skip / overwrite also available).
Hard refusal if the resolved output path equals the source file.

---

## 6. UI

PySide6. Drag-and-drop a file, several files, or a folder onto the window.

The window is divided by **scope**, not by widget type. Every setting appears
in exactly one place, which is the fix for the original layout's two competing
settings views:

- **Left column -- the batch.** A photo list on top, and beneath it the
  settings that describe the run: output width, JPEG quality, sharpening,
  destination folder, collision policy and the filename template. They sit
  with the list because they apply to everything in it. The **Process**
  button, progress bar and Cancel close the column, for the same reason.
- **Middle -- the preview** of the current photo, with the grid-overlay
  toggle and a line reporting source size, output size, border and the
  resolved filename.
- **Right column -- framing**, which applies to the selected photo(s): aspect
  ratio, crop-vs-fit, border percentage and frame colour. A scope line above
  it names what is being edited ("Applies to 3 selected photos"), and an
  *Apply this framing to all photos* button covers the common case.

**The list is selection only.** Its columns report each photo's framing,
resolved output name and warnings, but nothing in it is editable -- the cells
have `ItemIsEditable` explicitly cleared, not merely edit triggers disabled.

Photos added later inherit whatever the framing panel currently shows, so a
second drop matches the first.

Accepted input: JPEG, PNG, TIFF, WebP. No HEIC, no camera RAW.

## 7. Settings persistence

Last-used settings restored on launch, stored as JSON in the standard per-OS
config location. No named presets for now.

---

## 8. Project structure

```
igprep/
  core/        pure pipeline — no UI imports, unit-testable
    geometry.py    canvas/photo-box math, crop and fit rects
    color.py       ICC handling
    render.py      resize, sharpen, composite, encode
    naming.py      template engine
  gui/         PySide6 app
  tests/       reference-image and geometry tests
```

Keeping `core/` UI-free means the pipeline is testable in isolation, and a CLI
falls out nearly for free if it's ever wanted.

Dependencies: Pillow, PySide6.

---

## 9. Packaging

Source stays fully cross-platform (Windows, macOS, Ubuntu) — nothing
platform-specific in the code. Only **Windows** gets a packaged `.exe` via
PyInstaller. Mac and Linux users run it from Python.

---

## 10. Non-goals

- Camera RAW processing — bring your own edits.
- HEIC input.
- Video, carousels, or scheduling/posting to Instagram.
- Filters, colour grading, or any creative editing.
- Pan/zoom cropping.

---

## 11. Corrections made during implementation

Two things in the original draft were wrong and were fixed once the code made
them checkable:

1. **Grid crop direction.** The draft said a 4:5 post loses its top and bottom
   in the profile grid. It loses its *sides*; see section 1. The overlay draws
   the corrected region.
2. **1.91:1 at 1440 width** is 755px tall, not 754. The ratio is stored as the
   published 540:283 (which gives exactly 1080 x 566) rather than a rounded
   1.91:1, which would give 565 at 1080.

Verified on written files: the border measures exactly 43px on all four sides
at 4% and 1080 wide, for every ratio, with sRGB embedded and 4:4:4 chroma.

---

## 12. Defaults on first run

| Setting | Value | Scope |
|---|---|---|
| Aspect ratio | 3:4 portrait | per photo |
| Fit | Fit the whole photo | per photo |
| Border | 4% (43px at 1080) | per photo |
| Frame colour | #FFFFFF | per photo |
| Output width | 1080 | batch |
| JPEG quality | 95 | batch |
| Sharpening | 30 | batch |

`Settings` holds the batch plus a `Framing` used as the starting point for
newly added photos; each `Job` owns its own `Framing`.

---

## 13. Presets

Two independent named lists, one per scope, sharing `presets.json` in the
config directory:

| List | Control | Captures | Applies to |
|---|---|---|---|
| Framing | top of the right panel | ratio, fit, border, frame colour | the selected photo(s) |
| Output | top of the batch panel | width, quality, sharpening, destination, template, collision | the run |

`custom_name` is excluded: it is content for one batch, not reusable
configuration, and a preset that overwrote the name you just typed would be a
nuisance.

**Applying goes through the normal edit path** -- the bar loads the values into
the panel and emits `changed` -- so multi-select and *Apply to all* need no
special case for presets.

**The combo uses `activated`, not `currentIndexChanged`.** The latter is silent
when you pick the item already selected, which would make re-choosing a preset
to discard your edits do nothing. It also fires only on a deliberate pick, so
rebuilding the list never re-applies anything.

**The modified marker** appends `(modified)` once the panel no longer matches
the selected preset, and *Update* is offered only while it is showing. Because
it compares the panel against the preset, it tracks the photo selection for
free: reselecting the photo a preset was applied to clears it.

Written through on every change, so a crash cannot lose a preset that appeared
to save. Stored as JSON rather than one file per preset, so preset names never
reach the filesystem and need no sanitising.

**An output preset whose folder has since gone** applies everything else,
clears the path and says so in the status bar; Process stays disabled by the
existing validation rather than writing somewhere unexpected.

### The refactor it required

`Framing` was already a value object; the batch output settings were loose
fields on `Settings`. Extracting `OutputSettings` made both preset types the
same shape, so one generic `PresetStore` serves both. `Settings.from_dict`
accepts the old flat form so existing settings files still load.
