"""Activity log page builder."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..widgets import FlowBar, tool_button
from ...theme import density_metrics, theme_manager

if TYPE_CHECKING:
    from ..main_window import MainWindow


def build_log_page(win: MainWindow) -> QWidget:
    page = QWidget()
    page.setObjectName("pageContainer")
    layout = QVBoxLayout(page)
    m = density_metrics(theme_manager().ui_scale)
    layout.setContentsMargins(m["page_margin_x"], m["page_margin_top"], m["page_margin_x"], m["page_margin_bot"])
    layout.setSpacing(max(8, m["page_spacing"] - 2))

    header_bar = FlowBar(page, h_spacing=8, v_spacing=6)
    title = QLabel("Nhật ký")
    title.setObjectName("pageTitle")
    header_bar.addWidget(title)

    sub = QLabel("Hoạt động chi tiết từ yt-dlp và FFmpeg")
    sub.setObjectName("mutedLabel")
    header_bar.addWidget(sub)

    header_bar.addWidget(
        tool_button(
            "Sao chép",
            lambda: QApplication.clipboard().setText(win.log_box.toPlainText()),
            "Sao chép toàn bộ nội dung nhật ký vào Clipboard",
            "secondaryAccentButton",
            icon_name="copy",
            icon_size=14,
        ),
        trailing=True,
    )
    header_bar.addWidget(
        tool_button(
            "Xóa",
            lambda: win.log_box.clear(),
            "Xóa trắng khung nhật ký",
            "secondaryAccentButton",
            icon_name="trash-2",
            icon_size=14,
        ),
        trailing=True,
    )
    layout.addWidget(header_bar)

    win.log_box = QPlainTextEdit()
    win.log_box.setReadOnly(True)
    win.log_box.setMaximumBlockCount(600)
    win.log_box.setPlaceholderText(
        "Nhật ký phân tích liên kết, tải xuống và chuyển đổi Codec FFmpeg sẽ hiển thị tại đây..."
    )
    layout.addWidget(win.log_box, 1)

    def _apply_density(scale: float) -> None:
        dm = density_metrics(scale)
        layout.setContentsMargins(dm["page_margin_x"], dm["page_margin_top"], dm["page_margin_x"], dm["page_margin_bot"])
        layout.setSpacing(max(8, dm["page_spacing"] - 2))

    theme_manager().density_changed.connect(_apply_density)
    return page
