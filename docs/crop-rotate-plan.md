# Crop and rotate: plan

Status: **built for the phone. The gestures pass the emulator's checks but
have yet to be judged for smoothness on a real phone. The desktop app does
not have these controls yet.**

Position a photo inside its frame by hand: pinch to zoom, drag to move,
buttons to rotate by 1 degree or by 90. Built first for the phone, but the
arithmetic lives in `igprep/core`, so the desktop app can use it later.

---

## 1. What is stored: a placement per photo

| Value | Meaning | Default |
|---|---|---|
| `angle` | Rotation in whole degrees, clockwise, all the way round | 0 |
| `zoom` | 1.0 is "just fills the frame"; larger zooms in | 1.0 |
| `offset_x`, `offset_y` | Where the frame sits on the photo, -1 to 1, 0 centred | 0, 0 |

Everything is relative, never in pixels, so a placement means the same thing
on the small preview and on the full-size output. The default placement is
exactly today's centre crop, and a test will pin that: default placement must
produce a file identical to what the app writes now.

Ratio, border and frame colour stay as they are. Placement is separate and
belongs to one photo.

There is one angle, and it has no limit: 1 degree steps carry on past 45,
past 90, and round again. Underneath, every angle is treated as some number
of quarter turns plus a tilt of at most 45 degrees either way, because the
quarter turns cost nothing in quality. 44 is a tilt of 44; 46 is a quarter
turn and a tilt of 44 the other way. A test checks the two routes meet
without a seam.

## 2. The rules

- **The frame is always full.** In crop mode the photo always covers the whole
  frame; it cannot be dragged or shrunk far enough to show white.
- **Fine rotation zooms in just enough.** Tilting a photo leaves empty wedges
  at the corners. The minimum zoom grows with the angle so they never show,
  which is how the straighten tool in any photo editor behaves.
- **Zoom stops where blur would start.** You can zoom in until one photo pixel
  maps to one output pixel, and no further. A photo too small to fill the
  frame at all stays at zoom 1 and keeps its existing "will enlarge" warning.
- **90 degree turns are exact.** They rearrange pixels and lose nothing, and
  work in fit mode too.
- **A positioned photo fills the frame.** Fit mode shows the whole photo with
  white around it, so there is nothing to position. A photo that is tilted,
  zoomed or moved is cropped to fill whatever the fit setting says; put back
  as it was, it follows the fit setting again. Nothing is switched, so
  nothing needs switching back.

## 3. The arithmetic

For a frame of width-to-height ratio `a`, a photo `W` by `H` (after quarter
turns), and a tilt of `t` degrees, the largest frame-shaped rectangle that
fits inside the photo has width

    w_max = min( W / (|cos t| + |sin t| / a),  H / (|sin t| + |cos t| / a) )

That is zoom 1. Zoom `z` uses width `w_max / z`. The rectangle may slide until
its tilted outline touches the photo's edge; the two offsets are fractions of
that available travel.

Rendering keeps the existing order and quality:

1. Quarter turns, by rearranging pixels.
2. If tilted: cut out the region needed, rotate it at full resolution, then
   take the frame-shaped rectangle from the middle. Rotating before the
   downscale, not after, is what keeps the result sharp.
3. Lanczos downscale, sharpen, composite, encode: unchanged.

The preview uses the same function at preview size, as it does today.

## 4. The phone screen

- **One finger** drags the photo. **Two fingers** zoom and drag together.
- A row of buttons under the preview: `-90`, `-1`, the current angle, `+1`,
  `+90`. Minus is anticlockwise.
- Pressing the angle puts the photo back: level, centred, not zoomed.
- While rotating, dashed guide lines are drawn over the photo to level it
  against. They stay for 3 seconds after the last press, then go.
- Each photo keeps its own placement as you step through a batch.

While fingers are moving, the preview is redrawn from a smaller copy of the
photo in one quick step, about 20 ms a time, and the pixels are handed
straight to Android rather than through the toolkit. When the fingers lift,
the exact preview is drawn. Both are worked out from the same placement by
the same arithmetic, so the picture does not shift at that moment. (The
first plan was to let Android slide the picture itself while fingers moved.
That would have meant a second copy of the arithmetic, on the Android side,
to keep in step with the first.)

The toolkit's own touch handling reports one finger only, so a listener is
attached directly to Android's view, written the same way the toolkit writes
its own.

Rotating a photo that has been moved keeps the same spot of it in the middle
of the frame, including across 45 degrees, where the quarter turns change.

## 5. Order of work

1. **Core** (desktop, fully tested): placement, the rectangle arithmetic,
   tilted rendering, limits and clamping. Tests include: default placement
   reproduces today's output exactly; a marked image lands where the
   placement says after every turn and tilt; preview and final output agree.
   *Done.*
2. **Phone build A**: the rotation buttons and guide lines, driven by the new
   core. No gestures yet. *Done.*
3. **Phone build B**: one-finger drag and two-finger pinch. *Built.* To be
   tried on the Pixel for smoothness before being called done.
4. **Later**: the same controls in the desktop app.

The build's emulator check presses the buttons, and hands the preview real
one- and two-finger touches made the way Android makes them. What it cannot
judge is how the movement feels.

## 6. Not included

Free-form (non-rectangular) crops, perspective correction, flipping, and
angles finer than a whole degree.
