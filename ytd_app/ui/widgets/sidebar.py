"""Left navigation sidebar with stacked 'YouTube / Downloader' branding."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ...theme import theme_manager
from ...version import APP_VERSION


class Sidebar(QFrame):
    """Narrow left navigation rail (208px) with stacked brand title and page links."""

    page_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(208)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 18, 12, 14)
        layout.setSpacing(4)

        # Brand Header: "YouTube" on top, "Downloader" on second line, left-aligned
        brand_box = QWidget(self)
        brand_layout = QHBoxLayout(brand_box)
        brand_layout.setContentsMargins(8, 0, 8, 12)
        brand_layout.setSpacing(10)

        self.brand_icon = QLabel()
        self.brand_icon.setFixedSize(28, 28)
        self.brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_layout.addWidget(self.brand_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        title_stack = QVBoxLayout()
        title_stack.setContentsMargins(0, 0, 0, 0)
        title_stack.setSpacing(0)

        self.brand_top_label = QLabel("YouTube")
        self.brand_top_label.setObjectName("brandTop")
        self.brand_top_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.brand_bottom_label = QLabel("Downloader")
        self.brand_bottom_label.setObjectName("brandBottom")
        self.brand_bottom_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        title_stack.addWidget(self.brand_top_label)
        title_stack.addWidget(self.brand_bottom_label)
        brand_layout.addLayout(title_stack, 1)

        layout.addWidget(brand_box)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, tuple[QPushButton, str]] = {}

        primary_items = [
            ("downloads", "Tải xuống", "download"),
            ("hardware", "Phần cứng", "cpu"),
            ("log", "Nhật ký", "scroll-text"),
        ]
        for key, text, icon_name in primary_items:
            btn = self._make_nav_button(key, text, icon_name)
            layout.addWidget(btn)

        layout.addStretch(1)

        secondary_items = [
            ("guide", "Hướng dẫn", "book-open"),
            ("settings", "Cài đặt", "settings"),
        ]
        for key, text, icon_name in secondary_items:
            btn = self._make_nav_button(key, text, icon_name)
            if key == "settings":
                btn_layout = QHBoxLayout(btn)
                btn_layout.setContentsMargins(0, 0, 10, 0)
                btn_layout.addStretch(1)
                self.update_dot = QLabel()
                self.update_dot.setFixedSize(8, 8)
                self.update_dot.setStyleSheet("background-color: #EF4444; border-radius: 4px;")
                self.update_dot.setVisible(False)
                btn_layout.addWidget(self.update_dot, 0, Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(btn)

        self.settings_btn = self.nav_buttons["settings"][0]

        self.version_label = QLabel(f"Phiên bản v{APP_VERSION}")
        self.version_label.setObjectName("versionLabel")
        layout.addWidget(self.version_label)

        self.nav_buttons["downloads"][0].setChecked(True)
        self._refresh_icons()
        theme_manager().changed.connect(self._refresh_icons)

    def _make_nav_button(self, key: str, label: str, icon_name: str) -> QPushButton:
        btn = QPushButton(f"  {label}", self)
        btn.setObjectName("navItem")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIconSize(QSize(16, 16))
        btn.clicked.connect(lambda _checked=False, k=key: self._on_clicked(k))
        self.nav_group.addButton(btn)
        self.nav_buttons[key] = (btn, icon_name)
        return btn

    def _on_clicked(self, key: str) -> None:
        self._refresh_icons()
        self.page_requested.emit(key)

    def set_active_page(self, key: str) -> None:
        target = "downloads" if key in ("all", "active", "done", "error", "downloads") else key
        entry = self.nav_buttons.get(target)
        if entry is not None:
            btn, _ic = entry
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)
            self._refresh_icons()

    def set_downloads_badge(self, active_count: int) -> None:
        btn, _ic = self.nav_buttons["downloads"]
        if active_count > 0:
            btn.setText(f"  Tải xuống  ({active_count})")
        else:
            btn.setText("  Tải xuống")

    def set_update_badge(self, version_str: str) -> None:
        btn, _ic = self.nav_buttons["settings"]
        btn.setText("  Cài đặt")
        if hasattr(self, "update_dot"):
            self.update_dot.setVisible(bool(version_str))
        if version_str:
            btn.setToolTip(f"Có bản cập nhật mới v{version_str}! Bấm để vào mục Cài đặt → Cập nhật")
        else:
            btn.setToolTip("")

    def _refresh_icons(self, *_args) -> None:
        t = theme_manager().tokens
        self.brand_icon.setPixmap(
            icons.render_svg_pixmap("download", t["text"], size=20, dpr=2.0)
        )
        for _key, (btn, icon_name) in self.nav_buttons.items():
            col = t["text"] if btn.isChecked() else t["muted"]
            btn.setIcon(icons.icon(icon_name, color=col, size=16))
