"""Reusable minimal UI building blocks: buttons, folder chip, setting rows, and cards."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ...theme import theme_manager


def tool_button(
    label: str = "",
    callback: Callable | None = None,
    tooltip: str = "",
    object_name: str = "",
    icon_name: str = "",
    icon_size: int = 15,
) -> QPushButton:
    safe_label = label.replace("&", "&&") if "&" in label and "&&" not in label else label
    button = QPushButton(safe_label)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if callback is not None:
        button.clicked.connect(callback)
    if tooltip:
        button.setToolTip(tooltip)
    if object_name:
        button.setObjectName(object_name)
    if icon_name:
        button.setProperty("lucideIcon", icon_name)
        button.setProperty("lucideSize", icon_size)
        _apply_button_icon(button)
        theme_manager().changed.connect(lambda _m, b=button: _apply_button_icon(b))
    return button


def icon_button(
    icon_name: str,
    callback: Callable | None = None,
    tooltip: str = "",
    object_name: str = "iconButton",
    size: int = 15,
    danger: bool = False,
) -> QPushButton:
    btn = QPushButton("")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setObjectName("cardDangerButton" if danger else object_name)
    btn.setFixedSize(28, 28)
    if tooltip:
        btn.setToolTip(tooltip)
    if callback is not None:
        btn.clicked.connect(callback)
    btn.setProperty("lucideIcon", icon_name)
    btn.setProperty("lucideSize", size)
    btn.setProperty("lucideDanger", danger)
    _apply_button_icon(btn)
    theme_manager().changed.connect(lambda _m, b=btn: _apply_button_icon(b))
    return btn


def _apply_button_icon(btn: QPushButton) -> None:
    try:
        icon_name = btn.property("lucideIcon")
        if not icon_name:
            return
        size = int(btn.property("lucideSize") or 15)
        danger = bool(btn.property("lucideDanger"))
        t = theme_manager().tokens
        if btn.objectName() == "primaryButton":
            col = t["on_primary"]
        elif danger or btn.objectName() in ("cardDangerButton", "muteActiveButton"):
            col = t["danger"]
        else:
            col = t["text_secondary"]
        btn.setIcon(icons.icon(str(icon_name), color=col, size=size))
        btn.setIconSize(QSize(size, size))
    except RuntimeError:
        # Widget already deleted
        pass


class FolderChip(QPushButton):
    """Compact clickable chip displaying the active download folder."""

    def __init__(self, initial_path: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("folderChip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._full_path = initial_path
        self.setProperty("lucideIcon", "folder")
        self.setProperty("lucideSize", 14)
        _apply_button_icon(self)
        theme_manager().changed.connect(lambda _m: _apply_button_icon(self))
        self.set_path(initial_path)

    def set_path(self, path_str: str) -> None:
        self._full_path = path_str.strip()
        p = Path(self._full_path) if self._full_path else Path()
        parts = p.parts
        if len(parts) >= 2:
            short = f"{parts[-2]}/{parts[-1]}"
        elif parts:
            short = parts[-1]
        else:
            short = "Chọn thư mục..."
        if len(short) > 36:
            short = f"{p.drive}\\…\\{p.name}" if p.drive else f"…/{p.name}"
        self.setText(f" {short}")
        self.setToolTip(f"Thư mục lưu: {self._full_path}\nBấm để chọn thư mục khác")


class SectionCard(QFrame):
    """Rounded surface card with an optional uppercase section header."""

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("surfaceCard")
        self.body_layout = QVBoxLayout(self)
        self.body_layout.setContentsMargins(16, 14, 16, 14)
        self.body_layout.setSpacing(10)
        if title:
            hdr = QLabel(title.upper())
            hdr.setObjectName("sectionTitle")
            self.body_layout.addWidget(hdr)


class SettingRow(QWidget):
    """Horizontal row: title + optional subtitle on the left, control widget(s) on the right."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        control: QWidget | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-weight: 500;")
        text_col.addWidget(title_lbl)
        if subtitle:
            sub_lbl = QLabel(subtitle)
            sub_lbl.setObjectName("mutedLabel")
            sub_lbl.setWordWrap(True)
            text_col.addWidget(sub_lbl)
        row.addLayout(text_col, 1)

        if control is not None:
            control.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            row.addWidget(control)
