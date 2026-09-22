"""Colour management.

Instagram assumes sRGB and does not reliably honour embedded ICC profiles, so
an AdobeRGB or Display P3 export uploaded as-is comes out visibly flat. The
conversion has to happen here, before anything is resized or encoded.
"""

from __future__ import annotations

import io
import logging

from PIL import Image, ImageCms

log = logging.getLogger(__name__)

_SRGB = ImageCms.createProfile("sRGB")
SRGB_BYTES: bytes = ImageCms.ImageCmsProfile(_SRGB).tobytes()

# Relative colorimetric with black point compensation is what Lightroom and
# Photoshop use for this kind of export, so results match what the user expects.
INTENT = ImageCms.Intent.RELATIVE_COLORIMETRIC
FLAGS = ImageCms.Flags.BLACKPOINTCOMPENSATION

# Modes littlecms can transform directly.
_TRANSFORMABLE = {"RGB", "CMYK", "L"}


def embedded_profile_name(img: Image.Image) -> str | None:
    """Human-readable name of the embedded profile, for display in the UI."""
    raw = img.info.get("icc_profile")
    if not raw:
        return None
    try:
        profile = ImageCms.ImageCmsProfile(io.BytesIO(raw))
        return ImageCms.getProfileDescription(profile).strip() or None
    except Exception:  # malformed profile blobs are common in the wild
        return None


def _split_alpha(img: Image.Image) -> tuple[Image.Image, Image.Image | None]:
    if img.mode == "P":
        img = img.convert("RGBA" if "transparency" in img.info else "RGB")
    if img.mode in ("RGBA", "LA"):
        alpha = img.getchannel("A")
        # RGBA -> RGB drops the alpha channel without compositing, which is
        # what we want: the colour data is preserved for the ICC transform.
        return img.convert("RGB"), alpha
    return img, None


def to_srgb(img: Image.Image) -> Image.Image:
    """Return `img` converted to sRGB, preserving alpha if it had any.

    Falls back to a plain mode conversion when there is no profile or the
    embedded one is unusable -- a broken profile should not fail the job.
    """
    base, alpha = _split_alpha(img)
    raw = img.info.get("icc_profile")

    if raw and base.mode in _TRANSFORMABLE:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(raw))
            converted = ImageCms.profileToProfile(
                base, src, _SRGB,
                renderingIntent=INTENT, outputMode="RGB", flags=FLAGS,
            )
            if converted is not None:
                base = converted
            else:
                base = base.convert("RGB")
        except Exception as exc:
            log.warning("ICC transform failed (%s); assuming sRGB", exc)
            base = base.convert("RGB")
    elif base.mode != "RGB":
        base = base.convert("RGB")

    if alpha is not None:
        base.putalpha(alpha)
    return base


def flatten(img: Image.Image, background: str) -> Image.Image:
    """Composite any transparency onto `background` and return plain RGB.

    Done before resizing so the rest of the pipeline is a single mode, and so
    transparent edges blend into the frame rather than producing dark halos.
    """
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        canvas = Image.new("RGB", img.size, background)
        canvas.paste(img, (0, 0), img)
        return canvas
    return img.convert("RGB")
