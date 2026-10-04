"""The pieces of the screen the toolkit has no word for, pretended.

Each does nothing but note that it was asked. For tests: `toasts` is every
brief message shown, `labels` what each button was last made to say,
`asking` the pop-up waiting for a name (`answer()` types one and presses its
button), and `heights` how tall a test wants a piece of the screen to be.
"""

from __future__ import annotations

toasts: list[str] = []
labels: dict[int, tuple[str, object, bool]] = {}
heights: dict[int, int] = {}
handles: list = []
returns: list = []
asking: tuple | None = None
bars_darkened = False


def reset() -> None:
    global asking, bars_darkened
    toasts.clear(), labels.clear(), heights.clear(), handles.clear(), returns.clear()
    asking, bars_darkened = None, False


def dp(value: float) -> int:
    return int(round(value * 2))


def bitmap(image):
    return image


def drawable(image, size_dp: float):
    return image


def plain_button(button) -> None:
    pass


def label(button, text: str, icon=None, after: bool = False) -> None:
    labels[id(button)] = (text, icon, after)


def said(button) -> str:
    """What a button was last made to say."""
    return labels[id(button)][0]


def toast(text: str) -> None:
    toasts.append(text)


def ask_for_text(title: str, hint: str, confirm: str, on_confirm):
    global asking
    asking = (title, on_confirm)
    return asking


def answer(text: str) -> None:
    """Type `text` into the pop-up that is waiting and press its button."""
    global asking
    _, on_confirm = asking
    asking = None
    on_confirm(text)


class BackButton:
    def __init__(self, action) -> None:
        self.action = action
        self.listening = False
        self.available = True

    def listen(self, on: bool) -> None:
        self.listening = on


class _Text:
    def __init__(self) -> None:
        self.text = ""


def end_showing_text(holder, colour: str, size_sp: float):
    return _Text()


def set_text(view, text: str) -> None:
    view.text = text


def height(widget) -> int:
    return heights.get(id(widget), 300)


class _Handle:
    def __init__(self, on_start, on_move, on_end) -> None:
        self.on_start, self.on_move, self.on_end = on_start, on_move, on_end

    def drag(self, down: float) -> None:
        """A finger put on the handle, moved `down` pixels, and lifted."""
        self.on_start()
        self.on_move(down)
        self.on_end()


def drag_handle(holder, on_start, on_move, on_end, on_error):
    handle = _Handle(on_start, on_move, on_end)
    handles.append(handle)
    return handle


def outline_dropdown(spinner, colour: str) -> None:
    pass


class Returns:
    def __init__(self, action, on_error) -> None:
        self.action = action
        returns.append(self)


def darken_system_bars() -> None:
    global bars_darkened
    bars_darkened = True


def launched_with(flag: str) -> bool:
    return False


def device() -> list[str]:
    return ["Not a phone: the pretend platform"]


def self_test():
    return None
