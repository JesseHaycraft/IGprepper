"""Fingers on the preview, as Android reports them.

The toolkit's own touch handling knows about one finger. Pinching needs two,
so this listens to Android's view directly, the way the toolkit attaches its
own listeners.

This module only imports on Android.
"""

from __future__ import annotations

from android.view import View
from java import dynamic_proxy, jarray, jclass
from PIL import Image

Bitmap = jclass("android.graphics.Bitmap")
BitmapConfig = jclass("android.graphics.Bitmap$Config")
ByteBuffer = jclass("java.nio.ByteBuffer")
InputDevice = jclass("android.view.InputDevice")
MotionEvent = jclass("android.view.MotionEvent")
PointerCoords = jclass("android.view.MotionEvent$PointerCoords")
PointerProperties = jclass("android.view.MotionEvent$PointerProperties")
RectF = jclass("android.graphics.RectF")
SystemClock = jclass("android.os.SystemClock")

CHANGED, MOVED, ENDED = "changed", "moved", "ended"
_KINDS = {
    MotionEvent.ACTION_DOWN: CHANGED,
    MotionEvent.ACTION_POINTER_DOWN: CHANGED,
    MotionEvent.ACTION_POINTER_UP: CHANGED,
    MotionEvent.ACTION_MOVE: MOVED,
    MotionEvent.ACTION_UP: ENDED,
    MotionEvent.ACTION_CANCEL: ENDED,
}


class Listener(dynamic_proxy(View.OnTouchListener)):
    """Calls `handler(kind, points)` with the fingers still on the view."""

    def __init__(self, handler, on_error) -> None:
        super().__init__()
        self.handler = handler
        self.on_error = on_error

    def onTouch(self, view, event) -> bool:
        try:
            action = event.getActionMasked()
            kind = _KINDS.get(action)
            if kind is not None:
                # The finger being lifted is still listed in its own event.
                lifted = (
                    event.getActionIndex()
                    if action == MotionEvent.ACTION_POINTER_UP else -1
                )
                points = [
                    (float(event.getX(i)), float(event.getY(i)))
                    for i in range(event.getPointerCount())
                    if i != lifted
                ]
                self.handler(kind, points[:2])
        except Exception:
            self.on_error()
        # Claiming the touch is what keeps the rest of it coming.
        return True


def shown_at(view) -> tuple[float, float, float]:
    """Where the picture sits inside its view: centre x, centre y, width.

    The view is usually larger than the picture, which is scaled to fit and
    centred. Android has already worked out where; this asks it.
    """
    drawable = view.getDrawable()
    rect = RectF(0, 0, drawable.getIntrinsicWidth(), drawable.getIntrinsicHeight())
    view.getImageMatrix().mapRect(rect)
    return (
        rect.centerX() + view.getPaddingLeft(),
        rect.centerY() + view.getPaddingTop(),
        rect.width(),
    )


class Canvas:
    """Puts pictures on a view quickly, for redrawing as a finger moves.

    The toolkit's own route encodes each picture as a file and has Android
    decode it again, which is too slow to follow a finger. This copies the
    pixels straight across, into the same bitmap each time.
    """

    def __init__(self) -> None:
        self.bitmap = None

    def show(self, view, image: Image.Image) -> None:
        if self.bitmap is None or (
            self.bitmap.getWidth(), self.bitmap.getHeight()
        ) != image.size:
            self.bitmap = Bitmap.createBitmap(
                image.width, image.height, BitmapConfig.ARGB_8888
            )
        # ARGB_8888 is stored as R, G, B, A in memory, despite the name.
        pixels = image.convert("RGBA").tobytes()
        self.bitmap.copyPixelsFromBuffer(ByteBuffer.wrap(pixels))
        view.setImageBitmap(self.bitmap)


# --- for the build's own check -------------------------------------------------

def send(view, action: int, points, down_time: int) -> None:
    """Hand the view a touch as Android would, with any number of fingers."""
    properties, coords = [], []
    for number, (x, y) in enumerate(points):
        prop = PointerProperties()
        prop.id = number
        prop.toolType = MotionEvent.TOOL_TYPE_FINGER
        properties.append(prop)
        coord = PointerCoords()
        coord.x, coord.y = float(x), float(y)
        coord.pressure, coord.size = 1.0, 1.0
        coords.append(coord)
    event = MotionEvent.obtain(
        down_time, SystemClock.uptimeMillis(), action, len(points),
        jarray(PointerProperties)(properties), jarray(PointerCoords)(coords),
        0, 0, 1.0, 1.0, 0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0,
    )
    try:
        view.dispatchTouchEvent(event)
    finally:
        event.recycle()


def second_finger(action: int) -> int:
    """`action`, said of the second finger rather than the first."""
    return action | (1 << MotionEvent.ACTION_POINTER_INDEX_SHIFT)


def now() -> int:
    return SystemClock.uptimeMillis()
