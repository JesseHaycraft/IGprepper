"""A long list of files and folders, scrolled by Android itself.

The toolkit builds a widget for every row it is given, which is fine for a
dozen rows and hopeless for a camera folder with thousands. Android's own
list keeps only the rows on screen and reuses them as they scroll off, so
this hands it the rows one at a time as it asks.

The same files can be shown two ways. As a list, each row is a mark (for a
photo that can be chosen, showing whether it has been), a small picture and
a name. As tiles, two across, each is a large picture with the mark in its
corner and the name beneath. Over either sit a line of text for when there
is nothing to show, and a counter in the bottom right corner. In the list
the marks are on the left, so that the counter never sits on top of one.

This module only imports on Android.
"""

from __future__ import annotations

from java import cast, dynamic_proxy, jclass
from PIL import Image, ImageOps

from ... import palette
from ...thumbs import Thumbnails
from . import ui

AbsListLayout = jclass("android.widget.AbsListView$LayoutParams")
Color = jclass("android.graphics.Color")
FrameLayout = jclass("android.widget.FrameLayout")
FrameLayoutParams = jclass("android.widget.FrameLayout$LayoutParams")
GradientDrawable = jclass("android.graphics.drawable.GradientDrawable")
Gravity = jclass("android.view.Gravity")
GridView = jclass("android.widget.GridView")
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
COLUMNS = 2
TILE_GAP_DP = 6
# Tiles are wide, but a picture this many pixels across is plenty for one,
# and a great deal less to keep in memory than a full-width one.
TILE_THUMB_PX = 300
# How many pictures to keep to hand: small ones are cheap, large ones not.
KEEP_SMALL, KEEP_LARGE = 400, 80
TILE_EDGE_DP = 3        # the band round a tile that colours when it is checked
TILE_UNMEASURED_DP = 150  # a tile's height before Android has measured the columns
FILL, WRAP = -1, -2  # Android's "as big as the parent" and "as big as needed"

# The colours as Android wants them, worked out once: rows are redrawn
# constantly while a list scrolls.
TEXT = Color.parseColor(palette.TEXT)
FAINT = Color.parseColor(palette.FAINT)
ACCENT = Color.parseColor(palette.ACCENT)
CHECKED_ROW = Color.parseColor(palette.CHECKED_ROW)


class _Adapter(dynamic_proxy(ListAdapter)):
    """Answers Android's questions about the list: how long, and what goes
    in place so-and-so. There is one for the list and one for the tiles."""

    def __init__(self, owner, tiles: bool) -> None:
        super().__init__()
        self.owner, self.tiles = owner, tiles
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
        return self.owner.item_view(position, convert, self.tiles)

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
        """`holder` is the empty box on screen to fill. `icon(name, colour)`
        gives a bitmap. `on_press(entry)` is called when a row or tile is
        pressed."""
        holder = ui.native(holder)
        self.loop, self.log, self.icon, self.on_press = loop, log, icon, on_press
        self.rows: list = []
        self.checked: set[str] = set()
        self.selectable = False
        self.tiles = False
        self.refresh_due = False
        self.thumbs = Thumbnails(loop, self.picture_arrived)

        context = ui.activity()
        holder.setBackgroundColor(Color.parseColor(palette.PANEL))
        self.press = _Press(self)

        self.list = ListView(context)
        self.list.setDividerHeight(0)
        self.list.setFastScrollEnabled(True)
        self.list_adapter = _Adapter(self, tiles=False)
        self.list.setAdapter(self.list_adapter)
        self.list.setOnItemClickListener(self.press)
        holder.addView(self.list, RelativeLayoutParams(FILL, FILL))

        gap = ui.dp(TILE_GAP_DP)
        self.grid = GridView(context)
        self.grid.setNumColumns(COLUMNS)
        self.grid.setHorizontalSpacing(gap)
        self.grid.setVerticalSpacing(gap)
        self.grid.setPadding(gap, gap, gap, gap)
        self.grid.setClipToPadding(False)
        self.grid.setFastScrollEnabled(True)
        self.grid_adapter = _Adapter(self, tiles=True)
        self.grid.setAdapter(self.grid_adapter)
        self.grid.setOnItemClickListener(self.press)
        holder.addView(self.grid, RelativeLayoutParams(FILL, FILL))

        self.note = TextView(context)
        self.note.setTextColor(FAINT)
        self.note.setGravity(Gravity.CENTER)
        self.note.setPadding(ui.dp(16), 0, ui.dp(16), 0)
        holder.addView(self.note, RelativeLayoutParams(FILL, FILL))

        self.counter = TextView(context)
        self.counter.setTextColor(Color.parseColor(palette.ON_ACCENT))
        self.counter.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13)
        self.counter.setPadding(
            ui.dp(12), ui.dp(5), ui.dp(12), ui.dp(5)
        )
        pill = GradientDrawable()
        pill.setColor(ACCENT)
        pill.setCornerRadius(ui.dp(16))
        self.counter.setBackground(pill)
        corner = RelativeLayoutParams(WRAP, WRAP)
        corner.addRule(RelativeLayout.ALIGN_PARENT_BOTTOM)
        corner.addRule(RelativeLayout.ALIGN_PARENT_END)
        corner.setMargins(0, 0, ui.dp(10), ui.dp(8))
        holder.addView(self.counter, corner)

        self.arrange()
        self.say(None)
        self.count(None)

    # --- what is shown ----------------------------------------------------------

    @property
    def view(self):
        """Whichever of the two is on screen."""
        return self.grid if self.tiles else self.list

    @property
    def adapter(self):
        return self.grid_adapter if self.tiles else self.list_adapter

    @property
    def thumb_px(self) -> int:
        return TILE_THUMB_PX if self.tiles else ui.dp(THUMB_DP)

    def arrange(self) -> None:
        self.list.setVisibility(View.GONE if self.tiles else View.VISIBLE)
        self.grid.setVisibility(View.VISIBLE if self.tiles else View.GONE)

    def show(
        self, rows: list, fetch=None, *, selectable: bool = False, tiles: bool = False
    ) -> None:
        """A different folder, or the same one shown the other way: new
        rows, back at the top, old pictures dropped. `fetch(doc_id, pixels)`
        returns a thumbnail bitmap that many pixels square, or None."""
        self.rows = list(rows)
        self.selectable = selectable
        self.tiles = tiles
        self.arrange()
        side = self.thumb_px
        self.thumbs.start(
            None if fetch is None else (lambda key: fetch(key, side)),
            keep=KEEP_LARGE if tiles else KEEP_SMALL,
        )
        self.adapter.changed()
        self.view.setSelection(0)

    def update(self, rows: list) -> None:
        """The same folder, changed: rows added, or marks moved."""
        self.rows = list(rows)
        self.adapter.changed()

    def seed(self, doc_id: str, picture: Image.Image) -> None:
        """Give a file its picture directly, without asking the storage app:
        for a photo this app has just written and so already has."""
        side = self.thumb_px
        square = ImageOps.fit(picture.convert("RGB"), (side, side))
        self.thumbs.put(doc_id, ui.bitmap(square))

    def say(self, text: str | None) -> None:
        """Words in the middle, for when there is nothing to show."""
        self.note.setText(text or "")
        self.note.setVisibility(View.VISIBLE if text else View.GONE)

    def count(self, text: str | None) -> None:
        """The counter in the bottom corner."""
        self.counter.setText(text or "")
        self.counter.setVisibility(View.VISIBLE if text else View.GONE)

    # --- one row, or one tile -----------------------------------------------------

    def item_view(self, position: int, convert, tiles: bool):
        try:
            if tiles:
                tile = cast(LinearLayout, convert) if convert is not None else self.new_tile()
                self.fill_tile(tile, self.rows[position])
                return tile
            row = cast(LinearLayout, convert) if convert is not None else self.new_row()
            self.fill_row(row, self.rows[position])
            return row
        except Exception:
            # Android asked for a view and must be given one. A fresh, empty
            # one of the right kind, so that it can be filled next time round.
            self.log.exception("drawing an entry of the list")
            return self.new_tile() if tiles else self.new_row()

    def describe(self, entry, name, picture) -> bool:
        """Put an entry's name and picture into a row or a tile. Returns
        whether it is checked."""
        name.setText(entry.name)
        name.setTextColor(TEXT if entry.is_dir or entry.is_photo else FAINT)

        thumbnail = self.thumbs.get(entry.doc_id) if entry.is_photo else None
        if thumbnail is not None:
            picture.setScaleType(ScaleType.CENTER_CROP)
            picture.setImageBitmap(thumbnail)
        else:
            kind = "folder" if entry.is_dir else "photo" if entry.is_photo else "file"
            picture.setScaleType(ScaleType.CENTER_INSIDE)
            picture.setImageBitmap(
                self.icon(kind, palette.TEXT if entry.is_dir else palette.FAINT)
            )
        return entry.doc_id in self.checked

    def new_row(self):
        context = ui.activity()
        row = LinearLayout(context)
        row.setOrientation(LinearLayout.HORIZONTAL)
        row.setGravity(Gravity.CENTER_VERTICAL)
        row.setPadding(ui.dp(10), 0, ui.dp(12), 0)
        row.setLayoutParams(AbsListLayout(FILL, ui.dp(ROW_DP)))

        mark = ImageView(context)
        side = ui.dp(MARK_DP)
        before = LinearLayoutParams(side, side)
        before.setMarginEnd(ui.dp(10))
        row.addView(mark, before)

        picture = ImageView(context)
        side = ui.dp(THUMB_DP)
        row.addView(picture, LinearLayoutParams(side, side))

        name = TextView(context)
        name.setSingleLine(True)
        # The end of a camera filename is what tells two photos apart.
        name.setEllipsize(TruncateAt.MIDDLE)
        name.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15)
        beside = LinearLayoutParams(0, WRAP, 1.0)
        beside.setMarginStart(ui.dp(12))
        beside.setMarginEnd(ui.dp(8))
        row.addView(name, beside)
        return row

    def fill_row(self, row, entry) -> None:
        mark = cast(ImageView, row.getChildAt(0))
        picture = cast(ImageView, row.getChildAt(1))
        name = cast(TextView, row.getChildAt(2))

        checked = self.describe(entry, name, picture)
        if self.selectable and entry.is_photo:
            mark.setVisibility(View.VISIBLE)
            mark.setImageBitmap(
                self.icon("checked", palette.ACCENT) if checked
                else self.icon("unchecked", palette.FAINT)
            )
        else:
            # Where photos can be chosen, other rows keep the space, so that
            # every picture and name lines up.
            mark.setVisibility(View.INVISIBLE if self.selectable else View.GONE)
        row.setBackgroundColor(CHECKED_ROW if checked else Color.TRANSPARENT)

    def new_tile(self):
        context = ui.activity()
        tile = LinearLayout(context)
        tile.setOrientation(LinearLayout.VERTICAL)
        edge = ui.dp(TILE_EDGE_DP)
        tile.setPadding(edge, edge, edge, edge)
        tile.setLayoutParams(AbsListLayout(FILL, WRAP))

        frame = FrameLayout(context)
        frame.setBackgroundColor(Color.parseColor(palette.TILE))
        tile.addView(frame, LinearLayoutParams(FILL, ui.dp(TILE_UNMEASURED_DP)))

        picture = ImageView(context)
        frame.addView(picture, FrameLayoutParams(FILL, FILL))

        mark = ImageView(context)
        # A dark disc behind the mark, so it shows on a pale photo.
        disc = GradientDrawable()
        disc.setShape(GradientDrawable.OVAL)
        disc.setColor(Color.parseColor(palette.SCRIM))
        mark.setBackground(disc)
        inset = ui.dp(2)
        mark.setPadding(inset, inset, inset, inset)
        side = ui.dp(MARK_DP + 6)
        corner = FrameLayoutParams(side, side)
        corner.gravity = Gravity.TOP | Gravity.START
        corner.setMargins(ui.dp(6), ui.dp(6), 0, 0)
        frame.addView(mark, corner)

        name = TextView(context)
        name.setSingleLine(True)
        name.setEllipsize(TruncateAt.MIDDLE)
        name.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13)
        name.setPadding(ui.dp(2), ui.dp(4), ui.dp(2), ui.dp(2))
        tile.addView(name, LinearLayoutParams(FILL, WRAP))
        return tile

    def tile_side(self) -> int:
        """How wide Android has made each column, which is how tall the
        picture in it should be: square."""
        column = self.grid.getColumnWidth()
        if column <= 0:
            gap = ui.dp(TILE_GAP_DP)
            column = (self.grid.getWidth() - gap * (COLUMNS + 1)) // COLUMNS
        if column <= 0:
            column = ui.dp(TILE_UNMEASURED_DP)
        return column - 2 * ui.dp(TILE_EDGE_DP)

    def fill_tile(self, tile, entry) -> None:
        frame = cast(FrameLayout, tile.getChildAt(0))
        name = cast(TextView, tile.getChildAt(1))
        picture = cast(ImageView, frame.getChildAt(0))
        mark = cast(ImageView, frame.getChildAt(1))

        side = self.tile_side()
        shape = frame.getLayoutParams()
        if shape.height != side:
            shape.height = side
            frame.setLayoutParams(shape)

        checked = self.describe(entry, name, picture)
        if self.selectable and entry.is_photo:
            mark.setVisibility(View.VISIBLE)
            mark.setImageBitmap(
                self.icon("checked", palette.ACCENT) if checked
                else self.icon("unchecked", palette.TEXT)
            )
        else:
            mark.setVisibility(View.GONE)
        tile.setBackgroundColor(ACCENT if checked else Color.TRANSPARENT)

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
