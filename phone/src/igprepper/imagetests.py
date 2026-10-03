"""The image pipeline, checked on the device it is running on.

These are the same checks the desktop build was verified with: the output is
the right size, the border is the planned width on all four sides, and the
file is sRGB with full-resolution colour. Run here, they show whether a phone
produces what the desktop does.

Nothing in this module is Android-specific, so it also runs under the desktop
test suite. That is what catches a mistake in the checks themselves before
they are sent to a phone.
"""

from __future__ import annotations

import io
import time

from PIL import Image, ImageDraw, JpegImagePlugin

from igprep.core import color, geometry as g, render
from igprep.core.srgb_profile import SRGB_BYTES

from .fixtures import FIXTURES

WHITE = (255, 255, 255)
# Android's colour engine and the desktop's are different software converting
# through the same profile; agreement to within a few levels is the realistic
# standard, and well inside what the eye can see.
COLOUR_TOLERANCE = 4


def make_test_photo(width: int, height: int) -> Image.Image:
    """A generated scene: sky, a ridge, ground and some fine detail."""
    ramp = Image.linear_gradient("L").resize((width, height))
    image = Image.merge(
        "RGB",
        (
            ramp.point(lambda v: 70 + v * 120 // 255),
            ramp.point(lambda v: 120 + v * 100 // 255),
            ramp.point(lambda v: 190 + v * 50 // 255),
        ),
    )
    draw = ImageDraw.Draw(image)
    horizon = int(height * 0.62)
    draw.rectangle([0, horizon, width, height], fill=(86, 74, 58))
    draw.polygon(
        [
            (0, horizon),
            (int(width * 0.3), horizon - int(height * 0.16)),
            (int(width * 0.62), horizon - int(height * 0.05)),
            (int(width * 0.85), horizon - int(height * 0.12)),
            (width, horizon),
        ],
        fill=(58, 62, 58),
    )
    radius = min(width, height) // 14
    cx, cy = int(width * 0.3), int(height * 0.25)
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(255, 238, 190))
    step = max(8, width // 160)
    for x in range(0, width, step):
        draw.line(
            [(x, horizon + 4), (x + width // 40, height)],
            fill=(112, 98, 80),
            width=max(1, width // 1500),
        )
    return image


def _frame(source: Image.Image, mode: str, ratio: str = "3:4") -> tuple[Image.Image, g.Layout]:
    layout = g.plan(
        source.size, ratio=g.ratio_for(ratio), width=1080, border_pct=4.0, mode=mode
    )
    return render.render(source, layout, frame_color="#FFFFFF", sharpen=30), layout


def _encode(canvas: Image.Image) -> bytes:
    buffer = io.BytesIO()
    render.save_jpeg(canvas, buffer, quality=95)
    return buffer.getvalue()


def _border_widths(canvas: Image.Image) -> tuple[int, int, int, int]:
    """Left, right, top and bottom: pixels of pure frame before the photo."""
    width, height = canvas.size
    mid_x, mid_y = width // 2, height // 2

    def run(points):
        for count, point in enumerate(points):
            if canvas.getpixel(point) != WHITE:
                return count
        return -1

    return (
        run((x, mid_y) for x in range(width)),
        run((width - 1 - x, mid_y) for x in range(width)),
        run((mid_x, y) for y in range(height)),
        run((mid_x, height - 1 - y) for y in range(height)),
    )


def framed_test_jpeg() -> bytes:
    """A finished, framed JPEG -- something real to look at in a file browser."""
    canvas, _ = _frame(make_test_photo(3000, 2000), "crop")
    return _encode(canvas)


# --- the checks ---------------------------------------------------------------

def check_pipeline(log) -> bool:
    """Size, border, colour tag and chroma of a framed test photo."""
    passed = True

    def verdict(label: str, ok: bool, detail: str) -> None:
        nonlocal passed
        passed = passed and ok
        log.write(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}")

    source = make_test_photo(3000, 2000)
    canvas, layout = _frame(source, "crop")
    verdict("Canvas size", canvas.size == (1080, 1440), f"{canvas.size[0]} x {canvas.size[1]}")
    borders = _border_widths(canvas)
    verdict("Border, crop mode", borders == (43, 43, 43, 43),
            f"left/right/top/bottom = {borders}, planned {layout.border}")

    fitted, fit_layout = _frame(source, "fit")
    left, right, top, bottom = _border_widths(fitted)
    verdict("Fit mode keeps the whole photo",
            # An odd number of spare pixels cannot be split evenly, so the
            # two bands may differ by one.
            (left, right) == (43, 43) and abs(top - bottom) <= 1 and top > 43,
            f"sides {left}/{right}, top/bottom {top}/{bottom}")

    data = _encode(canvas)
    with Image.open(io.BytesIO(data)) as saved:
        verdict("Saved size", saved.size == (1080, 1440), f"{saved.size[0]} x {saved.size[1]}")
        verdict("sRGB profile embedded", saved.info.get("icc_profile") == SRGB_BYTES,
                f"{len(saved.info.get('icc_profile') or b'')} bytes")
        sampling = JpegImagePlugin.get_sampling(saved)
        verdict("Full-resolution colour (4:4:4)", sampling == 0, f"sampling code {sampling}")
    log.write(f"Framed JPEG is {len(data) / 1024:.0f} KB")
    return passed


def check_rotation(log) -> bool:
    """Turning and tilting: does the photo land where the arithmetic says?"""
    passed = True

    def verdict(label: str, ok: bool, detail: str) -> None:
        nonlocal passed
        passed = passed and ok
        log.write(f"{'PASS' if ok else 'FAIL'}  {label}: {detail}")

    def framed(source, angle, mode="crop", ratio="1:1"):
        layout = g.plan(
            source.size, ratio=g.ratio_for(ratio), width=1080, border_pct=0,
            mode=mode, placement=g.Placement(angle=angle),
        )
        return render.render(source, layout, frame_color="#FFFFFF", sharpen=0), layout

    scene = make_test_photo(1500, 1000)
    plain, _ = _frame(scene, "crop")
    layout = g.plan(
        scene.size, ratio=g.ratio_for("3:4"), width=1080, border_pct=4.0,
        mode="crop", placement=g.Placement(),
    )
    same = render.render(scene, layout, frame_color="#FFFFFF", sharpen=30)
    verdict("A photo left alone", plain.tobytes() == same.tobytes(),
            "identical to the output before rotation existed")

    # A red corner, to follow round.
    marked = Image.new("RGB", (800, 600), (40, 90, 160))
    marked.paste((230, 30, 30), (0, 0, 200, 150))
    corners = {0: "top left", 90: "top right", 180: "bottom right", -90: "bottom left"}
    for angle, expected in corners.items():
        out, where = framed(marked, angle, mode="fit")
        x0, y0 = where.origin
        w, h = where.scaled
        spots = {
            "top left": (x0 + 20, y0 + 20),
            "top right": (x0 + w - 20, y0 + 20),
            "bottom right": (x0 + w - 20, y0 + h - 20),
            "bottom left": (x0 + 20, y0 + h - 20),
        }
        found = [name for name, at in spots.items() if out.getpixel(at)[0] > 200]
        verdict(f"Turned {angle} degrees", found == [expected],
                f"the top-left corner is now {' and '.join(found) or 'nowhere'}")

    # Anything fetched from beyond the photo's edge would come back black.
    white = Image.new("RGB", (900, 700), WHITE)
    darkest = 255
    for angle in (1, -7, 20, 45, -45, 63, 170):
        out, _ = framed(white, angle)
        darkest = min(darkest, min(low for low, _ in out.getextrema()))
    verdict("No empty corners at any tilt", darkest == 255,
            f"darkest pixel {darkest} of 255")

    # A level line, tilted ten degrees clockwise: its right end drops.
    lined = Image.new("RGB", (2000, 2000), WHITE)
    ImageDraw.Draw(lined).line([(0, 1000), (2000, 1000)], fill=(0, 0, 0), width=9)
    out, _ = framed(lined, 10)

    def line_at(x: int) -> float:
        dark = [y for y in range(out.height) if out.getpixel((x, y))[0] < 128]
        return sum(dark) / len(dark) if dark else -1.0

    left, right = line_at(240), line_at(840)
    # 300 pixels either side of centre, at ten degrees: 52.9 up and down.
    ok = abs(left - (539.5 - 52.9)) < 2.5 and abs(right - (539.5 + 52.9)) < 2.5
    verdict("A 10 degree tilt", ok,
            f"a level line runs from {left:.1f} to {right:.1f}; "
            "exact would be 486.6 to 592.4")
    return passed


def check_colour(log, convert=None) -> bool:
    """Do tagged images come out as the sRGB values the desktop produces?

    `convert` turns image bytes into an sRGB image by some route other than
    the image library's own colour engine -- on a phone, Android's decoder.
    """
    log.write(
        "Colour engine in the image library: "
        + ("present" if color.HAVE_ENGINE else "absent on this device")
    )
    passed = True
    for fixture in FIXTURES:
        routes = []
        if color.HAVE_ENGINE:
            routes.append(("image library", lambda data: color.to_srgb(_open(data))))
        if convert is not None:
            routes.append(("Android", convert))
        if not routes:
            log.write(f"FAIL  {fixture['name']}: no way to convert colour on this device")
            passed = False
            continue

        for route, function in routes:
            try:
                converted = function(fixture["jpeg"])
            except Exception as exc:
                log.write(f"FAIL  {fixture['name']} via {route}: {exc!r}")
                passed = False
                continue
            worst = 0
            for centre, stored, expected in fixture["patches"]:
                got = converted.getpixel(centre)[:3]
                worst = max(worst, max(abs(a - b) for a, b in zip(got, expected)))
                log.write(f"      stored {stored} -> {got}, desktop gives {expected}")
            ok = worst <= COLOUR_TOLERANCE
            passed = passed and ok
            log.write(
                f"{'PASS' if ok else 'FAIL'}  {fixture['name']} via {route}: "
                f"furthest from the desktop by {worst} of 255"
            )
    return passed


def _open(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def check_speed(log, size: tuple[int, int] = (4080, 3072)) -> float:
    """Time a photo of typical phone-camera size through the whole pipeline."""
    megapixels = size[0] * size[1] / 1_000_000
    source = make_test_photo(*size)
    started = time.perf_counter()
    canvas, _ = _frame(source, "crop")
    framed = time.perf_counter()
    data = _encode(canvas)
    finished = time.perf_counter()
    log.write(
        f"A {megapixels:.1f} MP photo: framed in {framed - started:.2f} s, "
        f"saved in {finished - framed:.2f} s ({len(data) / 1024:.0f} KB)"
    )

    layout = g.plan(
        source.size, ratio=g.ratio_for("3:4"), width=1080, border_pct=4.0,
        mode="crop", placement=g.Placement(angle=3),
    )
    tilt_started = time.perf_counter()
    render.render(source, layout, frame_color="#FFFFFF", sharpen=30)
    log.write(
        f"The same photo tilted 3 degrees: framed in "
        f"{time.perf_counter() - tilt_started:.2f} s"
    )
    return finished - started


def run_all(log, convert=None) -> bool:
    log.section("Image pipeline")
    try:
        pipeline_ok = check_pipeline(log)
    except Exception:
        log.exception("checking the pipeline")
        pipeline_ok = False

    log.section("Rotation")
    try:
        rotation_ok = check_rotation(log)
    except Exception:
        log.exception("checking rotation")
        rotation_ok = False

    log.section("Colour conversion")
    try:
        colour_ok = check_colour(log, convert)
    except Exception:
        log.exception("checking colour conversion")
        colour_ok = False

    log.section("Speed")
    try:
        check_speed(log)
    except Exception:
        log.exception("timing the pipeline")

    return pipeline_ok and rotation_ok and colour_ok
