"""The parts of the screen the toolkit has no word for.

Icons beside button labels, a pop-up that asks for a name, the brief message
at the bottom of the screen, and the phone's own Back gesture. Each is done
the way Android apps ordinarily do it, by speaking to Android directly.

This module only imports on Android.
"""

from __future__ import annotations

import io

from java import dynamic_proxy, jclass
from org.beeware.android import MainActivity
from PIL import Image

AlertDialog = jclass("android.app.AlertDialog")
BitmapDrawable = jclass("android.graphics.drawable.BitmapDrawable")
BitmapFactory = jclass("android.graphics.BitmapFactory")
Build = jclass("android.os.Build")
DialogInterface = jclass("android.content.DialogInterface")
EditText = jclass("android.widget.EditText")
FrameLayout = jclass("android.widget.FrameLayout")
Gravity = jclass("android.view.Gravity")
ImageSpan = jclass("android.text.style.ImageSpan")
InsetDrawable = jclass("android.graphics.drawable.InsetDrawable")
InputType = jclass("android.text.InputType")
SpannableString = jclass("android.text.SpannableString")
Spanned = jclass("android.text.Spanned")
Toast = jclass("android.widget.Toast")
TruncateAt = jclass("android.text.TextUtils$TruncateAt")
WindowLayout = jclass("android.view.WindowManager$LayoutParams")

# Stands in the text where an icon is to be drawn.
_PLACEHOLDER = "￼"
# About the height of a line of button text. An icon is told it is this
# tall, however tall it is drawn.
_LINE_DP = 13
# The phone's Back gesture can only be intercepted from Android 13.
_MIN_SDK_FOR_BACK = 33


def activity():
    return MainActivity.singletonThis


def dp(value: float) -> int:
    """Density-independent units to this screen's pixels."""
    density = activity().getResources().getDisplayMetrics().density
    return int(round(value * density))


def drawable(image: Image.Image, size_dp: float):
    """An icon Android can draw, `size_dp` across."""
    data = io.BytesIO()
    image.save(data, "PNG")
    raw = data.getvalue()
    bitmap = BitmapFactory.decodeByteArray(raw, 0, len(raw))
    picture = BitmapDrawable(activity().getResources(), bitmap)
    side = dp(size_dp)
    # An icon taller than the text beside it makes Android grow the line
    # upwards to hold it, which leaves the words sitting low. So the icon
    # claims no more height than the text has, and overhangs that evenly
    # above and below: drawn full size, centred on the words.
    overhang = max(0, (side - dp(_LINE_DP)) // 2)
    result = InsetDrawable(picture, 0, -overhang, 0, -overhang)
    result.setBounds(0, 0, side, side - 2 * overhang)
    return result


def plain_button(native) -> None:
    """Labels as written, not in capitals, and no wider than they need be.

    Capitals are how Android buttons used to look. They also discard any
    icon placed in the label.
    """
    native.setAllCaps(False)
    native.setMinWidth(0)
    native.setMinimumWidth(0)
    # Android's side padding is generous enough that three labelled buttons
    # do not fit across a phone.
    native.setPadding(
        dp(10), native.getPaddingTop(), dp(10), native.getPaddingBottom()
    )


def label(native, text: str, icon=None, after: bool = False) -> None:
    """Set a button's label, with an icon before it if one is given, or
    `after` it.

    The icon is placed in the text itself, so it stays beside the words
    rather than at the far edge of a wide button.
    """
    if icon is None:
        native.setText(text)
        return
    if not text:
        written, at = _PLACEHOLDER, 0
    elif after:
        written, at = f"{text}  {_PLACEHOLDER}", len(text) + 2
    else:
        written, at = f"{_PLACEHOLDER}  {text}", 0
    content = SpannableString(written)
    content.setSpan(
        ImageSpan(icon, ImageSpan.ALIGN_CENTER), at, at + 1,
        Spanned.SPAN_EXCLUSIVE_EXCLUSIVE,
    )
    native.setText(content)


def bitmap(image: Image.Image):
    """A picture Android can put in a view."""
    data = io.BytesIO()
    image.save(data, "PNG")
    raw = data.getvalue()
    return BitmapFactory.decodeByteArray(raw, 0, len(raw))


def align_start(native) -> None:
    """For rows in a list: text at the leading edge, on one line."""
    native.setGravity(Gravity.START | Gravity.CENTER_VERTICAL)
    native.setSingleLine(True)
    native.setEllipsize(TruncateAt.END)


def toast(text: str) -> None:
    """A brief message at the bottom of the screen that needs no answer."""
    Toast.makeText(activity(), text, Toast.LENGTH_LONG).show()


class _Click(dynamic_proxy(DialogInterface.OnClickListener)):
    def __init__(self, action) -> None:
        super().__init__()
        self.action = action

    def onClick(self, dialog, which) -> None:
        self.action()


def ask_for_text(title: str, hint: str, confirm: str, on_confirm):
    """A pop-up with one text field, as a file manager's "New folder" has.

    Returns the dialog and its field, which the build's own check uses to
    fill it in and press the button.
    """
    field = EditText(activity())
    field.setHint(hint)
    field.setSingleLine(True)
    field.setInputType(
        InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
    )
    holder = FrameLayout(activity())
    holder.setPadding(dp(24), dp(8), dp(24), 0)
    holder.addView(field)

    builder = AlertDialog.Builder(activity())
    builder.setTitle(title)
    builder.setView(holder)
    builder.setPositiveButton(
        confirm, _Click(lambda: on_confirm(str(field.getText())))
    )
    builder.setNegativeButton("Cancel", None)
    dialog = builder.create()
    # Bring the keyboard up with the dialog: there is nothing else to do in it.
    dialog.getWindow().setSoftInputMode(WindowLayout.SOFT_INPUT_STATE_VISIBLE)
    dialog.show()
    field.requestFocus()
    return dialog, field


def press_confirm(dialog) -> None:
    dialog.getButton(DialogInterface.BUTTON_POSITIVE).performClick()


class BackButton:
    """Lets a screen answer the phone's Back gesture itself.

    Without this, Back closes the app from any screen, taking unsaved work
    with it. Android allows it to be intercepted from version 13; on older
    phones this does nothing and Back behaves as before.
    """

    def __init__(self, action) -> None:
        self.callback = None
        self.listening = False
        if Build.VERSION.SDK_INT < _MIN_SDK_FOR_BACK:
            return
        try:
            interface = jclass("android.window.OnBackInvokedCallback")

            class Callback(dynamic_proxy(interface)):
                def onBackInvoked(self) -> None:
                    action()

            self.callback = Callback()
        except Exception:
            # Back then behaves as it always did, which is no worse.
            self.callback = None

    @property
    def available(self) -> bool:
        return self.callback is not None

    def listen(self, on: bool) -> None:
        if self.callback is None or on == self.listening:
            return
        dispatcher = activity().getOnBackInvokedDispatcher()
        if on:
            priority = jclass("android.window.OnBackInvokedDispatcher").PRIORITY_DEFAULT
            dispatcher.registerOnBackInvokedCallback(priority, self.callback)
        else:
            dispatcher.unregisterOnBackInvokedCallback(self.callback)
        self.listening = on
