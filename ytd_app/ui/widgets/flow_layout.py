"""Responsive wrapping FlowLayout with optional right-aligned trailing widget group."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidget


class FlowLayout(QLayout):
    """QLayout that flows widgets horizontally and wraps cleanly onto new lines when narrow.

    Widgets added with ``trailing=True`` are pushed flush-right when they fit alongside
    the preceding row's items (or on the final row), mimicking ``addStretch(1)`` on wide
    screens while wrapping naturally without clipping on small / high-DPI screens.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        margin: int = 0,
        h_spacing: int = 8,
        v_spacing: int = 6,
    ) -> None:
        super().__init__(parent)
        self._items: list[tuple[QLayoutItem, bool]] = []
        self._pending_trailing = False
        self._h_space = h_spacing
        self._v_space = v_spacing
        if margin >= 0:
            self.setContentsMargins(margin, margin, margin, margin)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append((item, self._pending_trailing))

    def addWidget(self, widget: QWidget, trailing: bool = False) -> None:  # type: ignore[override]
        self._pending_trailing = bool(trailing)
        try:
            super().addWidget(widget)
        finally:
            self._pending_trailing = False
        self.invalidate()

    def setSpacing(self, spacing: int) -> None:  # noqa: N802
        self._h_space = spacing
        super().setSpacing(spacing)

    def setVerticalSpacing(self, spacing: int) -> None:
        self._v_space = spacing
        self.invalidate()

    def setHorizontalSpacing(self, spacing: int) -> None:
        self._h_space = spacing
        self.invalidate()

    def horizontalSpacing(self) -> int:
        return self._h_space

    def verticalSpacing(self) -> int:
        return self._v_space

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index][0]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            item, _trailing = self._items.pop(index)
            return item
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), apply_geometry=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, apply_geometry=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        left, top, right, bottom = self.getContentsMargins()
        max_w = 0
        max_h = 0
        total_w = 0
        visible_cnt = 0
        for item, _trailing in self._items:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            hint = item.sizeHint()
            if visible_cnt > 0:
                total_w += self._h_space
            total_w += hint.width()
            max_w = max(max_w, hint.width())
            max_h = max(max_h, hint.height())
            visible_cnt += 1
        # Report natural single-row width or at least min height for wrapped state
        parent_w = self.parentWidget().width() if self.parentWidget() else 0
        if parent_w > 0:
            h = self.heightForWidth(parent_w)
        else:
            h = max_h + top + bottom
        return QSize(total_w + left + right, h)

    def minimumSize(self) -> QSize:  # noqa: N802
        left, top, right, bottom = self.getContentsMargins()
        max_item_w = 0
        max_item_h = 0
        for item, _trailing in self._items:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            sz = item.minimumSize()
            hint = item.sizeHint()
            max_item_w = max(max_item_w, min(hint.width(), max(sz.width(), hint.width())))
            max_item_h = max(max_item_h, max(sz.height(), hint.height()))
        return QSize(max_item_w + left + right, max_item_h + top + bottom)

    def _item_size(self, item: QLayoutItem, max_avail_w: int) -> QSize:
        hint = item.sizeHint()
        mn = item.minimumSize()
        w = max(mn.width(), hint.width())
        if max_avail_w > 0 and w > max_avail_w:
            w = max(mn.width(), max_avail_w)
            if w > max_avail_w:
                w = max_avail_w
        if item.hasHeightForWidth():
            h = item.heightForWidth(w)
        else:
            h = max(mn.height(), hint.height())
        return QSize(w, h)

    def _do_layout(self, rect: QRect, apply_geometry: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        effective = rect.adjusted(left, top, -right, -bottom)
        avail_w = max(1, effective.width())

        # Collect visible items with their measured sizes
        visible: list[tuple[QLayoutItem, bool, QSize]] = []
        for item, trailing in self._items:
            w = item.widget()
            if w is not None and w.isHidden():
                continue
            visible.append((item, trailing, self._item_size(item, avail_w)))

        if not visible:
            return top + bottom

        # Group items into rows
        rows: list[list[tuple[QLayoutItem, bool, QSize]]] = []
        cur_row: list[tuple[QLayoutItem, bool, QSize]] = []
        cur_w = 0

        for entry in visible:
            _item, _trailing, sz = entry
            needed = sz.width() if not cur_row else cur_w + self._h_space + sz.width()
            if cur_row and needed > avail_w:
                rows.append(cur_row)
                cur_row = [entry]
                cur_w = sz.width()
            else:
                cur_row.append(entry)
                cur_w = needed
        if cur_row:
            rows.append(cur_row)

        y = effective.y()
        for row_idx, row_entries in enumerate(rows):
            # If a wrapped/sole row has 1 Expanding item, give it the full row width
            if len(row_entries) == 1:
                sole_item, sole_tr, sole_sz = row_entries[0]
                sole_w = sole_item.widget()
                if sole_w is not None and sole_w.sizePolicy().horizontalPolicy() in (
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.MinimumExpanding,
                ):
                    expanded_w = avail_w
                    expanded_h = sole_item.heightForWidth(expanded_w) if sole_item.hasHeightForWidth() else sole_sz.height()
                    row_entries = [(sole_item, sole_tr, QSize(expanded_w, expanded_h))]

            row_h = max(sz.height() for _, _, sz in row_entries)
            used_w = sum(sz.width() for _, _, sz in row_entries) + self._h_space * max(0, len(row_entries) - 1)
            extra_gap = max(0, effective.width() - used_w)

            # Find first trailing widget in this row (if any) to absorb extra_gap
            first_trailing_idx = next(
                (i for i, (_it, tr, _sz) in enumerate(row_entries) if tr),
                -1,
            )

            if apply_geometry:
                x = effective.x()
                for i, (item, _tr, sz) in enumerate(row_entries):
                    if i == first_trailing_idx and extra_gap > 0:
                        x += extra_gap
                    item_y = y + (row_h - sz.height()) // 2
                    item.setGeometry(QRect(QPoint(x, item_y), sz))
                    x += sz.width() + self._h_space

            y += row_h
            if row_idx < len(rows) - 1:
                y += self._v_space

        return (y - effective.y()) + top + bottom


class FlowBar(QWidget):
    """QWidget container backed by FlowLayout so QVBoxLayout honors wrapped height cleanly."""

    def __init__(
        self,
        parent: QWidget | None = None,
        h_spacing: int = 8,
        v_spacing: int = 6,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._flow = FlowLayout(self, margin=0, h_spacing=h_spacing, v_spacing=v_spacing)

    def addWidget(self, widget: QWidget, trailing: bool = False) -> None:
        self._flow.addWidget(widget, trailing=trailing)

    def setSpacing(self, h_spacing: int, v_spacing: int | None = None) -> None:
        self._flow.setHorizontalSpacing(h_spacing)
        if v_spacing is not None:
            self._flow.setVerticalSpacing(v_spacing)
        self._flow.invalidate()
        self.updateGeometry()

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._flow.heightForWidth(width)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self._flow.sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self._flow.minimumSize()

