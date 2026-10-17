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

from ..widgets import tool_button

if TYPE_CHECKING:
    from ..main_window import MainWindow


def build_log_page(win: MainWindow) -> QWidget:
    page = QWidget()
    page.setObjectName("pageContainer")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(24, 20, 24, 16)
    layout.setSpacing(12)

    header = QHBoxLayout()
    title = QLabel("Nhật ký")
    title.setObjectName("pageTitle")
    header.addWidget(title)

    sub = QLabel("Hoạt động chi tiết từ yt-dlp và FFmpeg")
    sub.setObjectName("mutedLabel")
    header.addSpacing(8)
    header.addWidget(sub)
    header.addStretch(1)

    header.addWidget(
        tool_button(
            "Sao chép",
            lambda: QApplication.clipboard().setText(win.log_box.toPlainText()),
            "Sao chép toàn bộ nội dung nhật ký vào Clipboard",
            "secondaryAccentButton",
            icon_name="copy",
            icon_size=14,
        )
    )
    header.addWidget(
        tool_button(
            "Xóa",
            lambda: win.log_box.clear(),
            "Xóa trắng khung nhật ký",
            "secondaryAccentButton",
            icon_name="trash-2",
            icon_size=14,
        )
    )
    layout.addLayout(header)

    win.log_box = QPlainTextEdit()
    win.log_box.setReadOnly(True)
    win.log_box.setMaximumBlockCount(600)
    win.log_box.setPlaceholderText(
        "Nhật ký phân tích liên kết, tải xuống và chuyển đổi Codec FFmpeg sẽ hiển thị tại đây..."
    )
    layout.addWidget(win.log_box, 1)
    return page
