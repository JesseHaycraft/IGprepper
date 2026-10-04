"""A long list of files and folders, scrolled by Android itself.

The toolkit builds a widget for every row it is given, which is fine for a
dozen rows and hopeless for a camera folder with thousands. Android's own
list keeps only the rows on screen and reuses them as they scroll off, so
this hands it the rows one at a time as it asks.

Each row is a small picture, a name, and for a photo that can be chosen, a
mark showing whether it has been. Over the list sit a line of text for when
there is nothing to list, and a counter in the bottom corner.

This module only imports on Android.
"""

from __future__ import annotations

from java import cast, dynamic_proxy, jclass

from . import androidui
from .thumbs import Thumbnails

AbsListLayout = jclass("android.widget.AbsListView$LayoutParams")
Color = jclass("android.graphics.Color")
GradientDrawable = jclass("android.graphics.drawable.GradientDrawable")
Gravity = jclass("android.view.Gravity")
ImageView = jclass("android.widget.ImageView")
ItemClick = jclass("android.widget.AdapterView$OnItemClickListener")
LinearLayout = jclass("android.widget.LinearLayout")
LinearLayoutParams = jclass("android.widget.LinearLayout$LayoutParams")
ListAdapter = jclass("android.widget.ListAdapter")
ListView = jclass("android.widget.ListView")
RelativeLayout = jclass("android.widget.RelativeLayout")
RelativeLayoutParams = jclass("android.widget.RelativeLayout$LayoutParams")
ScaleType = jclass("android.widget.ImageView$ScaleType")
TextView = jclass("android.widget.TextView")
TruncateAt = jclass("android.text.TextUtils$TruncateAt")
TypedValue = jclass("android.util.TypedValue")
View = jclass("android.view.View")

ROW_DP = 48
THUMB_DP = 36
MARK_DP = 22
FILL, WRAP = -1, -2  # Android's "as big as the parent" and "as big as needed"

PANEL = "#1D1E21"
TEXT = "#E8EAED"
FAINT = "#7D8388"
ACCENT = "#8AB4F8"
CHECKED_ROW = "#263347"


class _Adapter(dynamic_proxy(ListAdapter)):
    """Answers Android's questions about the list: how long, and what goes
    in row so-and-so."""

    def __init__(self, owner) -> None:
        super().__init__()
        self.owner = owner
        self.observers = []

    def registerDataSetObserver(self, observer) -> None:
        self.observers.append(observer)

    def unregisterDataSetObserver(self, observer) -> None:
        self.observers = [o for o in self.observers if o != observer]

    def changed(self) -> None:
        for observer in list(self.observers):
            observer.onChanged()

    def getCount(self) -> int:
        return len(self.owner.rows)

    def getItem(self, position):
        return None

    def getItemId(self, position) -> int:
        return position

    def hasStableIds(self) -> bool:
        return False

    def getView(self, position, convert, parent):
        return self.owner.row_view(position, convert)

    def getItemViewType(self, position) -> int:
        return 0

    def getViewTypeCount(self) -> int:
        return 1

    def isEmpty(self) -> bool:
        return not self.owner.rows

    def areAllItemsEnabled(self) -> bool:
        return True

    def isEnabled(self, position) -> bool:
        return True

    def getAutofillOptions(self):
        return None


class _Press(dynamic_proxy(ItemClick)):
    def __init__(self, owner) -> None:
        super().__init__()
        self.owner = owner

    def onItemClick(self, parent, view, position, row_id) -> None:
        self.owner.pressed(position)


class FileList:
    def __init__(self, holder, loop, log, icon, on_press) -> None:
        """`holder` is the Android view to fill. `icon(name, colour)` gives a
        bitmap. `on_press(entry)` is called when a row is pressed."""
        self.loop, self.log, self.icon, self.on_press = loop, log, icon, on_press
        self.rows: list = []
        self.checked: set[str] = set()
        self.selectable = False
        self.refresh_due = False
        self.thumbs = Thumbnails(loop, self.picture_arrived)
        self.thumb_px = androidui.dp(THUMB_DP)

        context = androidui.activity()
        holder.setBackgroundColor(Color.parseColor(PANEL))

        self.list = ListView(context)
        self.list.setDividerHeight(0)
        self.list.setFastScrollEnabled(True)
        self.adapter = _Adapter(self)
        self.press = _Press(self)
        self.list.setAdapter(self.adapter)
        self.list.setOnItemClickListener(self.press)
        holder.addView(self.list, RelativeLayoutParams(FILL, FILL))

        self.note = TextView(context)
        self.note.setTextColor(Color.parseColor(FAINT))
        self.note.setGravity(Gravity.CENTER)
        self.note.setPadding(androidui.dp(16), 0, androidui.dp(16), 0)
        holder.addView(self.note, RelativeLayoutParams(FILL, FILL))

        self.counter = TextView(context)
        self.counter.setTextColor(Color.parseColor("#0B1B33"))
        self.counter.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13)
        self.counter.setPadding(
            androidui.dp(12), androidui.dp(5), androidui.dp(12), androidui.dp(5)
        )
        pill = GradientDrawable()
        pill.setColor(Color.parseColor(ACCENT))
        pill.setCornerRadius(androidui.dp(16))
        self.counter.setBackground(pill)
        corner = RelativeLayoutParams(WRAP, WRAP)
        corner.addRule(RelativeLayout.ALIGN_PARENT_BOTTOM)
        corner.addRule(RelativeLayout.ALIGN_PARENT_END)
        corner.setMargins(0, 0, androidui.dp(10), androidui.dp(8))
        holder.addView(self.counter, corner)

        self.say(None)
        self.count(None)

    # --- what the list holds --------------------------------------------------

    def show(self, rows: list, fetch=None, *, selectable: bool = False) -> None:
        """A different folder: new rows, back at the top, old pictures dropped.
        `fetch(doc_id)` returns a thumbnail bitmap, or None."""
        self.rows = list(rows)
        self.selectable = selectable
        self.thumbs.start(fetch)
        self.adapter.changed()
        self.list.setSelection(0)

    def update(self, rows: list | None = None) -> None:
        """The same folder, changed: rows added, or marks moved."""
        if rows is not None:
            self.rows = list(rows)
        self.adapter.changed()

    def say(self, text: str | None) -> None:
        """Words in the middle of the list, for when it has nothing to show."""
        self.note.setText(text or "")
        self.note.setVisibility(View.VISIBLE if text else View.GONE)

    def count(self, text: str | None) -> None:
        """The counter in the bottom corner."""
        self.counter.setText(text or "")
        self.counter.setVisibility(View.VISIBLE if text else View.GONE)

    # --- one row ----------------------------------------------------------------

    def new_row(self):
        context = androidui.activity()
        row = LinearLayout(context)
        row.setOrientation(LinearLayout.HORIZONTAL)
        row.setGravity(Gravity.CENTER_VERTICAL)
        row.setPadding(androidui.dp(10), 0, androidui.dp(12), 0)
        row.setLayoutParams(AbsListLayout(FILL, androidui.dp(ROW_DP)))

        picture = ImageView(context)
        side = androidui.dp(THUMB_DP)
        row.addView(picture, LinearLayoutParams(side, side))

        name = TextView(context)
        name.setSingleLine(True)
        # The end of a camera filename is what tells two photos apart.
        name.setEllipsize(TruncateAt.MIDDLE)
        name.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15)
        beside = LinearLayoutParams(0, WRAP, 1.0)
        beside.setMarginStart(androidui.dp(12))
        beside.setMarginEnd(androidui.dp(8))
        row.addView(name, beside)

        mark = ImageView(context)
        side = androidui.dp(MARK_DP)
        row.addView(mark, LinearLayoutParams(side, side))
        return row

    def row_view(self, position: int, convert):
        try:
            row = convert if convert is not None else self.new_row()
            row = cast(LinearLayout, row)
            self.fill(row, self.rows[position])
            return row
        except Exception:
            # Android asked for a row and must be given one.
            self.log.exception("drawing a row of the list")
            return convert if convert is not None else View(androidui.activity())

    def fill(self, row, entry) -> None:
        picture = cast(ImageView, row.getChildAt(0))
        name = cast(TextView, row.getChildAt(1))
        mark = cast(ImageView, row.getChildAt(2))

        name.setText(entry.name)
        usable = entry.is_dir or entry.is_photo
        name.setTextColor(Color.parseColor(TEXT if usable else FAINT))

        thumbnail = None
        if entry.is_photo and entry.has_thumbnail:
            thumbnail = self.thumbs.get(entry.doc_id)
        if thumbnail is not None:
            picture.setScaleType(ScaleType.CENTER_CROP)
            picture.setImageBitmap(thumbnail)
        else:
            kind = "folder" if entry.is_dir else "photo" if entry.is_photo else "file"
            picture.setScaleType(ScaleType.CENTER_INSIDE)
            picture.setImageBitmap(self.icon(kind, TEXT if entry.is_dir else FAINT))

        checked = entry.doc_id in self.checked
        if self.selectable and entry.is_photo:
            mark.setVisibility(View.VISIBLE)
            mark.setImageBitmap(
                self.icon("checked", ACCENT) if checked else self.icon("unchecked", FAINT)
            )
        else:
            mark.setVisibility(View.GONE)
        row.setBackgroundColor(
            Color.parseColor(CHECKED_ROW) if checked else Color.TRANSPARENT
        )

    def pressed(self, position: int) -> None:
        try:
            if 0 <= position < len(self.rows):
                self.on_press(self.rows[position])
        except Exception:
            self.log.exception("answering a press on the list")

    # --- thumbnails ---------------------------------------------------------------

    def picture_arrived(self) -> None:
        # They arrive in bursts; redraw once for each burst, not each picture.
        if not self.refresh_due:
            self.refresh_due = True
            self.loop.call_later(0.12, self.redraw)

    def redraw(self) -> None:
        self.refresh_due = False
        try:
            self.adapter.changed()
        except Exception:
            self.log.exception("redrawing the list")
