"""The parts of the screen the toolkit has no word for.

Icons beside button labels, a pop-up that asks for a name, the brief message
at the bottom of the screen, a line of text that keeps its end in view, a
handle to drag, an outline for an opened menu; and what the phone tells the
app: its Back gesture, being returned to, what it is. Each is done the way
Android apps ordinarily do it, by speaking to Android directly.

Everything the two screens need from Android beyond storage, images and the
file list is here, behind a name that says what it is for. That list of
names is what a version for another kind of phone would have to supply.

This module only imports on Android.
"""

from __future__ import annotations

import io

from java import dynamic_proxy, jclass
from org.beeware.android import MainActivity
from PIL import Image

from ... import palette

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


def native(widget):
    """Android's own view behind one of the toolkit's widgets. Given a view,
    it is handed straight back."""
    return getattr(getattr(widget, "_impl", None), "native", widget)


_density: float | None = None


def dp(value: float) -> int:
    """Density-independent units to this screen's pixels."""
    global _density
    if _density is None:
        # Asked once: it is the same every time, and this is called for
        # every row of a list as it scrolls.
        _density = float(activity().getResources().getDisplayMetrics().density)
    return int(round(value * _density))


def bitmap(image: Image.Image):
    """A picture Android can put in a view."""
    data = io.BytesIO()
    image.save(data, "PNG")
    raw = data.getvalue()
    return BitmapFactory.decodeByteArray(raw, 0, len(raw))


def drawable(image: Image.Image, size_dp: float):
    """An icon Android can draw, `size_dp` across."""
    picture = BitmapDrawable(activity().getResources(), bitmap(image))
    side = dp(size_dp)
    # An icon taller than the text beside it makes Android grow the line
    # upwards to hold it, which leaves the words sitting low. So the icon
    # claims no more height than the text has, and overhangs that evenly
    # above and below: drawn full size, centred on the words.
    overhang = max(0, (side - dp(_LINE_DP)) // 2)
    result = InsetDrawable(picture, 0, -overhang, 0, -overhang)
    result.setBounds(0, 0, side, side - 2 * overhang)
    return result


def plain_button(button) -> None:
    """Labels as written, not in capitals, and no wider than they need be.

    Capitals are how Android buttons used to look. They also discard any
    icon placed in the label.
    """
    view = native(button)
    view.setAllCaps(False)
    view.setMinWidth(0)
    view.setMinimumWidth(0)
    # Android's side padding is generous enough that three labelled buttons
    # do not fit across a phone.
    view.setPadding(dp(10), view.getPaddingTop(), dp(10), view.getPaddingBottom())


def label(button, text: str, icon=None, after: bool = False) -> None:
    """Set a button's label, with an icon before it if one is given, or
    `after` it.

    The icon is placed in the text itself, so it stays beside the words
    rather than at the far edge of a wide button.
    """
    view = native(button)
    if icon is None:
        view.setText(text)
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
    view.setText(content)


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


# --- pieces of the two screens -------------------------------------------------

Color = jclass("android.graphics.Color")
GradientDrawable = jclass("android.graphics.drawable.GradientDrawable")
MotionEvent = jclass("android.view.MotionEvent")
RelativeLayout = jclass("android.widget.RelativeLayout")
RelativeLayoutParams = jclass("android.widget.RelativeLayout$LayoutParams")
TextView = jclass("android.widget.TextView")
TypedValue = jclass("android.util.TypedValue")
View = jclass("android.view.View")

_FILL = -1  # Android's "as big as the parent"


def end_showing_text(holder, colour: str, size_sp: float):
    """A line of text that keeps its end in view.

    Short text sits at the left. Text too long for the space loses its
    beginning, marked with an ellipsis, so that the end is always there to
    read: for a path, the end is the part that says where you are.

    The toolkit's own label cannot do this. It insists on being as wide as
    its text, and pushes the rest of the screen off the edge.
    """
    text = TextView(activity())
    text.setSingleLine(True)
    text.setEllipsize(TruncateAt.START)
    text.setGravity(Gravity.START | Gravity.CENTER_VERTICAL)
    text.setTextColor(Color.parseColor(colour))
    text.setTextSize(TypedValue.COMPLEX_UNIT_SP, size_sp)
    native(holder).addView(text, RelativeLayoutParams(_FILL, _FILL))
    return text


def set_text(view, text: str) -> None:
    view.setText(text)


def height(widget) -> int:
    """How tall a piece of the screen is at the moment, in its pixels."""
    return int(native(widget).getHeight())


class _Drag(dynamic_proxy(View.OnTouchListener)):
    def __init__(self, on_start, on_move, on_end, on_error) -> None:
        super().__init__()
        self.on_start, self.on_move, self.on_end = on_start, on_move, on_end
        self.on_error = on_error
        self.origin = 0.0

    def onTouch(self, view, event) -> bool:
        try:
            action = event.getActionMasked()
            # Measured against the screen, not the handle: the handle moves.
            y = float(event.getRawY())
            if action == MotionEvent.ACTION_DOWN:
                self.origin = y
                self.on_start()
            elif action == MotionEvent.ACTION_MOVE:
                self.on_move(y - self.origin)
            elif action in (MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL):
                self.on_end()
        except Exception:
            self.on_error()
        return True


def drag_handle(holder, on_start, on_move, on_end, on_error):
    """Make `holder` a handle to drag up and down, with a grip drawn on it
    like the one on a sheet that slides up from the bottom of the screen.

    `on_move` is given how far down the finger is from where it began.
    Returns the listener, which the caller must keep hold of.
    """
    grip = View(activity())
    bar = GradientDrawable()
    bar.setColor(Color.parseColor(palette.GRIP))
    bar.setCornerRadius(dp(2))
    grip.setBackground(bar)
    middle = RelativeLayoutParams(dp(44), dp(4))
    middle.addRule(RelativeLayout.CENTER_IN_PARENT)
    holder = native(holder)
    holder.addView(grip, middle)

    listener = _Drag(on_start, on_move, on_end, on_error)
    holder.setOnTouchListener(listener)
    return listener


def outline_dropdown(spinner, colour: str) -> None:
    """Give a drop-down's opened menu an edge of its own.

    Android draws the opened menu flat against the screen, in the same
    lettering as whatever lies beside it, so the two run together.
    """
    panel = GradientDrawable()
    panel.setColor(Color.parseColor(palette.MENU))
    panel.setStroke(dp(1.5), Color.parseColor(colour))
    panel.setCornerRadius(dp(8))
    spinner = native(spinner)
    spinner.setPopupBackgroundDrawable(panel)
    spinner.setDropDownVerticalOffset(dp(6))


class Returns:
    """Tells the app when it has been come back to, from another app or from
    the home screen. What was on screen may be out of date by then."""

    def __init__(self, action, on_error) -> None:
        interface = jclass("android.app.Application$ActivityLifecycleCallbacks")

        class Callbacks(dynamic_proxy(interface)):
            def onActivityResumed(self, activity_) -> None:
                try:
                    action()
                except Exception:
                    # Android is the caller: nothing may escape back to it.
                    on_error()

            # The rest of what Android reports is of no interest here, but
            # every one has to be answered.
            def onActivityCreated(self, activity_, state) -> None: ...
            def onActivityStarted(self, activity_) -> None: ...
            def onActivityPaused(self, activity_) -> None: ...
            def onActivityStopped(self, activity_) -> None: ...
            def onActivitySaveInstanceState(self, activity_, state) -> None: ...
            def onActivityDestroyed(self, activity_) -> None: ...
            def onActivityPreCreated(self, activity_, state) -> None: ...
            def onActivityPostCreated(self, activity_, state) -> None: ...
            def onActivityPreStarted(self, activity_) -> None: ...
            def onActivityPostStarted(self, activity_) -> None: ...
            def onActivityPreResumed(self, activity_) -> None: ...
            def onActivityPostResumed(self, activity_) -> None: ...
            def onActivityPrePaused(self, activity_) -> None: ...
            def onActivityPostPaused(self, activity_) -> None: ...
            def onActivityPreStopped(self, activity_) -> None: ...
            def onActivityPostStopped(self, activity_) -> None: ...
            def onActivityPreSaveInstanceState(self, activity_, state) -> None: ...
            def onActivityPostSaveInstanceState(self, activity_, state) -> None: ...
            def onActivityPreDestroyed(self, activity_) -> None: ...
            def onActivityPostDestroyed(self, activity_) -> None: ...

        self.callbacks = Callbacks()
        activity().registerActivityLifecycleCallbacks(self.callbacks)


# --- what the phone says about itself ------------------------------------------

def darken_system_bars() -> None:
    """The strips above and below the app, which the theme leaves light."""
    window = activity().getWindow()
    window.setStatusBarColor(Color.BLACK)
    window.setNavigationBarColor(Color.BLACK)


def launched_with(flag: str) -> bool:
    """Whether the app was started with a named switch set, as the build's
    own check starts it."""
    try:
        return bool(activity().getIntent().getBooleanExtra(flag, False))
    except Exception:
        return False


def device() -> list[str]:
    """What the phone is, for the head of the log."""
    return [
        f"Android {Build.VERSION.RELEASE} (API {Build.VERSION.SDK_INT})",
        f"Model: {Build.MANUFACTURER} {Build.MODEL}",
    ]


def self_test():
    """The build's own check, if the app was started to run it; else None."""
    if not launched_with("selftest"):
        return None
    from . import selftest

    return selftest.run
