"""Generate the colour fixtures the phone app tests itself with.

    python phone/tools/make_fixtures.py

Run on a desktop, where the image library has its colour engine. Each fixture
is a small JPEG tagged with a non-sRGB profile, plus the sRGB values the
desktop pipeline produces from it. The phone has to arrive at the same values
by another route, since its build of the library has no colour engine.

The images are flat generated patches. Nothing here comes from a photograph.
"""

from __future__ import annotations

import base64
import io
import struct
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from igprep.core import color  # noqa: E402

OUTPUT = ROOT / "phone" / "src" / "igprepper" / "fixtures.py"
PATCH = 32

# Primaries already adapted to the D50 white that ICC profiles are defined
# against, and D50 itself. These are the two wide-gamut spaces photographs
# actually arrive in: phones shoot Display P3, cameras offer Adobe RGB.
P3_PRIMARIES = (
    (0.515102, 0.241182, -0.001050),
    (0.291965, 0.692236, 0.041882),
    (0.157153, 0.066574, 0.784378),
)
ADOBE_PRIMARIES = (
    (0.609741, 0.311111, 0.019470),
    (0.205276, 0.625671, 0.060867),
    (0.149185, 0.063217, 0.744568),
)
D50 = (0.9642, 1.0, 0.8249)


def _fixed(value: float) -> bytes:
    return struct.pack(">i", int(round(value * 65536)))


def _xyz(triple) -> bytes:
    return b"XYZ \0\0\0\0" + b"".join(_fixed(v) for v in triple)


def _description(text: str) -> bytes:
    ascii_text = text.encode("ascii") + b"\0"
    return (
        b"desc\0\0\0\0" + struct.pack(">I", len(ascii_text)) + ascii_text
        + b"\0" * 4 + b"\0" * 4          # no Unicode version
        + b"\0" * 2 + b"\0" + b"\0" * 67  # no Macintosh version
    )


def _srgb_curve(points: int = 1024) -> bytes:
    """Display P3 uses the sRGB transfer curve."""
    table = []
    for i in range(points):
        x = i / (points - 1)
        y = x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
        table.append(int(round(y * 65535)))
    return b"curv\0\0\0\0" + struct.pack(">I", points) + struct.pack(f">{points}H", *table)


def _gamma_curve(gamma: float) -> bytes:
    """A pure power curve, stored as a single 8.8 fixed-point number."""
    return b"curv\0\0\0\0" + struct.pack(">IH", 1, int(round(gamma * 256)))


def display_p3_profile() -> bytes:
    return matrix_profile("Display P3 (test)", P3_PRIMARIES, _srgb_curve())


def adobe_rgb_profile() -> bytes:
    return matrix_profile(
        "Adobe RGB (test)", ADOBE_PRIMARIES, _gamma_curve(2.19921875)
    )


def matrix_profile(name: str, primaries, curve: bytes) -> bytes:
    """A minimal ICC v2 matrix profile: three primaries and one tone curve."""
    red, green, blue = primaries
    tags = [
        (b"desc", _description(name)),
        (b"cprt", b"text\0\0\0\0" + b"Public domain test profile\0"),
        (b"wtpt", _xyz(D50)),
        (b"rXYZ", _xyz(red)),
        (b"gXYZ", _xyz(green)),
        (b"bXYZ", _xyz(blue)),
        (b"rTRC", curve),
        (b"gTRC", curve),
        (b"bTRC", curve),
    ]

    table_size = 4 + 12 * len(tags)
    offset = 128 + table_size
    table, body, placed = b"", b"", {}
    for signature, data in tags:
        if data not in placed:  # the three curves share one copy
            padding = (-len(body)) % 4
            body += b"\0" * padding
            placed[data] = (offset + len(body), len(data))
            body += data
        where, size = placed[data]
        table += signature + struct.pack(">II", where, size)

    total = 128 + table_size + len(body)
    header = (
        struct.pack(">I", total)
        + b"\0\0\0\0"                        # no preferred engine
        + struct.pack(">I", 0x02400000)      # version 2.4
        + b"mntr" + b"RGB " + b"XYZ "
        + struct.pack(">6H", 2026, 1, 1, 0, 0, 0)
        + b"acsp" + b"\0" * 4 + b"\0" * 4
        + b"\0" * 4 + b"\0" * 4 + b"\0" * 8
        + struct.pack(">I", 0)               # perceptual by default
        + b"".join(_fixed(v) for v in D50)
        + b"\0" * 4
    )
    header += b"\0" * (128 - len(header))
    return header + struct.pack(">I", len(tags)) + table + body


def build(name: str, profile: bytes, colours) -> dict:
    image = Image.new("RGB", (PATCH * len(colours), PATCH))
    for i, rgb in enumerate(colours):
        image.paste(rgb, (i * PATCH, 0, (i + 1) * PATCH, PATCH))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=100, subsampling=0, icc_profile=profile)
    jpeg = buffer.getvalue()

    decoded = Image.open(io.BytesIO(jpeg))
    decoded.load()
    converted = color.to_srgb(decoded)
    patches = []
    for i in range(len(colours)):
        centre = (i * PATCH + PATCH // 2, PATCH // 2)
        patches.append((centre, decoded.getpixel(centre), converted.getpixel(centre)))
    return {"name": name, "jpeg": jpeg, "patches": patches}


def main() -> None:
    fixtures = [
        build("Display P3", display_p3_profile(),
              [(200, 80, 60), (60, 170, 90), (70, 90, 200), (128, 128, 128)]),
        build("Adobe RGB", adobe_rgb_profile(),
              [(200, 80, 60), (60, 170, 90), (70, 90, 200), (128, 128, 128)]),
    ]

    lines = [
        '"""Colour fixtures for the phone app\'s self-tests.',
        "",
        "Generated by phone/tools/make_fixtures.py -- do not edit by hand.",
        "",
        "Each JPEG is flat generated patches tagged with a non-sRGB profile.",
        "`patches` lists, for each patch: where to sample, the value stored in",
        "the file, and the sRGB value the desktop pipeline converts it to.",
        '"""',
        "",
        "import base64",
        "",
        "FIXTURES = [",
    ]
    for fixture in fixtures:
        encoded = "\n".join(
            textwrap.wrap(base64.b64encode(fixture["jpeg"]).decode(), 72)
        )
        lines += [
            "    {",
            f'        "name": {fixture["name"]!r},',
            '        "jpeg": base64.b64decode("""',
            encoded,
            '"""),',
            '        "patches": [',
        ]
        lines += [f"            {patch!r}," for patch in fixture["patches"]]
        lines += ["        ],", "    },"]
    lines += ["]", ""]
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")

    for fixture in fixtures:
        print(f"{fixture['name']}: {len(fixture['jpeg'])} bytes")
        for centre, stored, expected in fixture["patches"]:
            print(f"   stored {stored}  ->  sRGB {expected}")
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
