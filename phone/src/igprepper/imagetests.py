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
    return finished - started


def run_all(log, convert=None) -> bool:
    log.section("Image pipeline")
    try:
        pipeline_ok = check_pipeline(log)
    except Exception:
        log.exception("checking the pipeline")
        pipeline_ok = False

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

    return pipeline_ok and colour_ok
