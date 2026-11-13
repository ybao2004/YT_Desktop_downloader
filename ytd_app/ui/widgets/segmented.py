"""Segmented toggle control with QComboBox-compatible API."""
from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from .. import icons
from ...theme import theme_manager


class SegmentedControl(QFrame):
    """Minimal pill/segment selector compatible with QComboBox methods used in MainWindow."""

    currentIndexChanged = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("segmentedFrame")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._items: list[tuple[str, Any, QPushButton, str]] = []
        self._dots: dict[int, QLabel] = {}
        self._current_index: int = -1
        theme_manager().changed.connect(self._refresh_icons)

    def addItem(self, label: str, userData: Any = None, icon_name: str = "") -> None:
        idx = len(self._items)
        safe_label = label.replace("&", "&&") if "&" in label and "&&" not in label else label
        btn = QPushButton(safe_label, self)
        btn.setObjectName("segmentButton")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon_name:
            btn.setIcon(icons.icon(icon_name, size=14))
            btn.setIconSize(QSize(14, 14))
        btn.clicked.connect(lambda _checked=False, i=idx: self.setCurrentIndex(i))
        self._group.addButton(btn, idx)
        self._layout.addWidget(btn)
        self._items.append((label, userData, btn, icon_name))
        if self._current_index == -1:
            self._current_index = 0
            btn.setChecked(True)
            self._refresh_icons()

    def setItemBadgeDot(self, index: int, visible: bool, tooltip: str = "") -> None:
        if not (0 <= index < len(self._items)):
            return
        _label, _data, btn, _ic = self._items[index]
        dot = self._dots.get(index)
        if dot is None and visible:
            btn_layout = QHBoxLayout(btn)
            btn_layout.setContentsMargins(0, 0, 10, 0)
            btn_layout.addStretch(1)
            dot = QLabel(btn)
            dot.setFixedSize(8, 8)
            dot.setStyleSheet("background-color: #EF4444; border-radius: 4px;")
            btn_layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
            self._dots[index] = dot
        if dot is not None:
            dot.setVisible(visible)
        btn.setToolTip(tooltip if visible else "")

    def count(self) -> int:
        return len(self._items)

    def currentIndex(self) -> int:
        return self._current_index

    def currentData(self) -> Any:
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index][1]
        return None

    def currentText(self) -> str:
        if 0 <= self._current_index < len(self._items):
            return self._items[self._current_index][0]
        return ""

    def findData(self, data: Any) -> int:
        for idx, (_label, item_data, _btn, _ic) in enumerate(self._items):
            if item_data == data:
                return idx
        return -1

    def setCurrentIndex(self, index: int) -> None:
        if not (0 <= index < len(self._items)):
            return
        changed = index != self._current_index
        self._current_index = index
        for idx, (_label, _data, btn, _ic) in enumerate(self._items):
            btn.blockSignals(True)
            btn.setChecked(idx == index)
            btn.blockSignals(False)
        self._refresh_icons()
        if changed and not self.signalsBlocked():
            self.currentIndexChanged.emit(index)

    def _refresh_icons(self, *_args) -> None:
        t = theme_manager().tokens
        for idx, (_label, _data, btn, icon_name) in enumerate(self._items):
            if icon_name:
                col = t["text"] if idx == self._current_index else t["muted"]
                btn.setIcon(icons.icon(icon_name, color=col, size=14))
