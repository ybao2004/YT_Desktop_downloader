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
from ...theme import density_metrics, theme_manager
from ...version import APP_VERSION


class Sidebar(QFrame):
    """Responsive left navigation rail with stacked brand title, page links, and icon-rail fallback."""

    page_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self._icon_only: bool = False
        self._active_count: int = 0
        self._update_version: str = ""
        self._nav_labels: dict[str, str] = {}
        self.setFixedWidth(density_metrics(theme_manager().ui_scale)["sidebar_w"])

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 18, 12, 14)
        self._layout.setSpacing(4)

        # Brand Header: "YouTube" on top, "Downloader" on second line, left-aligned
        brand_box = QWidget(self)
        self._brand_layout = QHBoxLayout(brand_box)
        self._brand_layout.setContentsMargins(8, 0, 8, 12)
        self._brand_layout.setSpacing(10)

        self.brand_icon = QLabel()
        self.brand_icon.setFixedSize(28, 28)
        self.brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._brand_layout.addWidget(self.brand_icon, 0, Qt.AlignmentFlag.AlignVCenter)

        self._title_stack_widget = QWidget(brand_box)
        title_stack = QVBoxLayout(self._title_stack_widget)
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
        self._brand_layout.addWidget(self._title_stack_widget, 1)

        self._layout.addWidget(brand_box)

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
            self._layout.addWidget(btn)

        self._layout.addStretch(1)

        secondary_items = [
            ("guide", "Hướng dẫn", "book-open"),
            ("settings", "Cài đặt", "settings"),
        ]
        for key, text, icon_name in secondary_items:
            btn = self._make_nav_button(key, text, icon_name)
            if key == "settings":
                self._settings_btn_layout = QHBoxLayout(btn)
                self._settings_btn_layout.setContentsMargins(0, 0, 10, 0)
                self._settings_btn_layout.addStretch(1)
                self.update_dot = QLabel()
                self.update_dot.setFixedSize(8, 8)
                self.update_dot.setStyleSheet("background-color: #EF4444; border-radius: 4px;")
                self.update_dot.setVisible(False)
                self._settings_btn_layout.addWidget(self.update_dot, 0, Qt.AlignmentFlag.AlignVCenter)
            self._layout.addWidget(btn)

        self.settings_btn = self.nav_buttons["settings"][0]

        self.version_label = QLabel(f"Phiên bản v{APP_VERSION}")
        self.version_label.setObjectName("versionLabel")
        self._layout.addWidget(self.version_label)

        self.nav_buttons["downloads"][0].setChecked(True)
        self._refresh_icons()
        theme_manager().changed.connect(self._refresh_icons)

    def _make_nav_button(self, key: str, label: str, icon_name: str) -> QPushButton:
        self._nav_labels[key] = label
        btn = QPushButton(f"  {label}", self)
        btn.setObjectName("navItem")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIconSize(QSize(16, 16))
        btn.setToolTip(label)
        btn.clicked.connect(lambda _checked=False, k=key: self._on_clicked(k))
        self.nav_group.addButton(btn)
        self.nav_buttons[key] = (btn, icon_name)
        return btn

    def apply_responsive_mode(self, ui_scale: float = 1.0, icon_only: bool = False) -> None:
        self._icon_only = bool(icon_only)
        m = density_metrics(ui_scale)
        if self._icon_only:
            self.setFixedWidth(58)
            self._layout.setContentsMargins(8, 12, 8, 10)
            self._brand_layout.setContentsMargins(6, 0, 6, 8)
            self._title_stack_widget.setVisible(False)
            self.version_label.setVisible(False)
            if hasattr(self, "_settings_btn_layout"):
                self._settings_btn_layout.setContentsMargins(0, 4, 4, 0)
            for key, (btn, _ic) in self.nav_buttons.items():
                btn.setText("")
                btn.setStyleSheet("text-align: center; padding: 7px 0px;")
                if key == "downloads" and self._active_count > 0:
                    btn.setToolTip(f"Tải xuống ({self._active_count})")
                elif key == "settings" and self._update_version:
                    btn.setToolTip(f"Có bản cập nhật mới v{self._update_version}! Bấm để vào Cài đặt → Cập nhật")
                else:
                    btn.setToolTip(self._nav_labels.get(key, ""))
        else:
            self.setFixedWidth(m["sidebar_w"])
            pad_x = 10 if ui_scale < 0.96 else 12
            pad_y = 14 if ui_scale < 0.96 else 18
            self._layout.setContentsMargins(pad_x, pad_y, pad_x, max(10, pad_y - 4))
            self._brand_layout.setContentsMargins(6 if ui_scale < 0.96 else 8, 0, 6, 10 if ui_scale < 0.96 else 12)
            self._title_stack_widget.setVisible(True)
            self.version_label.setVisible(True)
            if hasattr(self, "_settings_btn_layout"):
                self._settings_btn_layout.setContentsMargins(0, 0, 10, 0)
            for key, (btn, _ic) in self.nav_buttons.items():
                btn.setStyleSheet("")
            self.set_downloads_badge(self._active_count)
            self.set_update_badge(self._update_version)

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
        self._active_count = int(active_count)
        btn, _ic = self.nav_buttons["downloads"]
        if self._icon_only:
            btn.setText("")
            btn.setToolTip(f"Tải xuống ({active_count})" if active_count > 0 else "Tải xuống")
            return
        if active_count > 0:
            btn.setText(f"  Tải xuống  ({active_count})")
        else:
            btn.setText("  Tải xuống")

    def set_update_badge(self, version_str: str) -> None:
        self._update_version = version_str or ""
        btn, _ic = self.nav_buttons["settings"]
        btn.setText("" if self._icon_only else "  Cài đặt")
        if hasattr(self, "update_dot"):
            self.update_dot.setVisible(bool(version_str))
        if version_str:
            btn.setToolTip(f"Có bản cập nhật mới v{version_str}! Bấm để vào mục Cài đặt → Cập nhật")
        else:
            btn.setToolTip("Cài đặt" if self._icon_only else "")

    def _refresh_icons(self, *_args) -> None:
        t = theme_manager().tokens
        self.brand_icon.setPixmap(
            icons.render_svg_pixmap("download", t["text"], size=20, dpr=2.0)
        )
        for _key, (btn, icon_name) in self.nav_buttons.items():
            col = t["text"] if btn.isChecked() else t["muted"]
            btn.setIcon(icons.icon(icon_name, color=col, size=16))
