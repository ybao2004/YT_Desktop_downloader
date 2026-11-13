"""Batch Downloads page builder: Multi-link command card, auto-capture toggle, and multi-line paste dialog."""
from __future__ import annotations

from typing import TYPE_CHECKING
from pathlib import Path

from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from .downloads import PasteAwareLineEdit
from .. import icons
from ..widgets import FolderChip, SegmentedControl, tool_button
from ...engine import extract_youtube_urls
from ...theme import theme_manager

if TYPE_CHECKING:
    from ..main_window import MainWindow


class AppendPastePlainTextEdit(QPlainTextEdit):
    """QPlainTextEdit that appends pasted text on a new line when non-empty and no selection is active."""

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Paste):
            clip_text = QApplication.clipboard().text().strip()
            if clip_text and not self.textCursor().hasSelection():
                existing = self.toPlainText().rstrip()
                if existing:
                    self.setPlainText(existing + "\n" + clip_text)
                else:
                    self.setPlainText(clip_text)
                cursor = self.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                self.setTextCursor(cursor)
                event.accept()
                return
        super().keyPressEvent(event)


class MultiLinkDialog(QDialog):
    """Modal dialog for pasting/accumulating multiple links across multiple pastes before queuing."""

    def __init__(self, win: MainWindow, initial_text: str = "") -> None:
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Thêm nhiều liên kết vào Hàng đợi")
        self.setMinimumSize(640, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        title = QLabel("Danh sách liên kết YouTube")
        title.setObjectName("cardTitle")
        top_row.addWidget(title)
        top_row.addStretch(1)

        self.stats_label = QLabel("0 liên kết hợp lệ")
        self.stats_label.setObjectName("metaBadge")
        top_row.addWidget(self.stats_label)
        layout.addLayout(top_row)

        hint = QLabel(
            "Dán 1 lần nhiều liên kết hoặc bấm 'Dán thêm' nhiều lần liên tiếp. "
            "Ứng dụng tự động bỏ qua văn bản không phải link và lọc bỏ các link trùng lặp."
        )
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.editor = AppendPastePlainTextEdit()
        self.editor.setPlaceholderText(
            "https://www.youtube.com/watch?v=...\n"
            "https://youtu.be/...\n"
            "https://www.youtube.com/shorts/..."
        )
        if initial_text.strip():
            self.editor.setPlainText(initial_text.strip())
        self.editor.textChanged.connect(self._update_stats)
        layout.addWidget(self.editor, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.append_paste_btn = tool_button(
            "Dán thêm",
            self._append_from_clipboard,
            "Dán nối tiếp nội dung từ Clipboard xuống dòng mới",
            "secondaryAccentButton",
            icon_name="clipboard-paste",
            icon_size=14,
        )
        btn_row.addWidget(self.append_paste_btn)

        self.clean_btn = tool_button(
            "Lọc sạch & Khử trùng",
            self._clean_in_place,
            "Loại bỏ dòng rác và giữ lại duy nhất các liên kết YouTube không trùng lặp",
            "ghostButton",
            icon_name="sparkles",
            icon_size=14,
        )
        btn_row.addWidget(self.clean_btn)

        self.clear_btn = tool_button(
            "Xóa trắng",
            self.editor.clear,
            "Xóa toàn bộ nội dung trong khung soạn thảo",
            "ghostButton",
            icon_name="trash-2",
            icon_size=14,
        )
        btn_row.addWidget(self.clear_btn)

        btn_row.addStretch(1)

        cancel_btn = tool_button("Đóng", self.reject, "Đóng hộp thoại", "ghostButton")
        btn_row.addWidget(cancel_btn)

        self.submit_btn = tool_button(
            "Đưa vào Hàng đợi",
            self.accept,
            "Đưa toàn bộ liên kết hợp lệ vào Hàng đợi ở trạng thái Chờ tải",
            "primaryButton",
            icon_name="list-plus",
            icon_size=14,
        )
        btn_row.addWidget(self.submit_btn)

        layout.addLayout(btn_row)
        self._update_stats()

    def _append_from_clipboard(self) -> None:
        clip_text = QApplication.clipboard().text().strip()
        if not clip_text:
            return
        existing = self.editor.toPlainText().rstrip()
        if existing:
            self.editor.setPlainText(existing + "\n" + clip_text)
        else:
            self.editor.setPlainText(clip_text)
        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)

    def _clean_in_place(self) -> None:
        urls, _dups, _inv = extract_youtube_urls(self.editor.toPlainText())
        self.editor.setPlainText("\n".join(urls))

    def _update_stats(self) -> None:
        urls, dups, inv = extract_youtube_urls(self.editor.toPlainText())
        parts = [f"{len(urls)} hợp lệ"]
        if dups > 0:
            parts.append(f"{dups} trùng")
        if inv > 0:
            parts.append(f"{inv} bỏ qua")
        self.stats_label.setText(" · ".join(parts))
        self.submit_btn.setText(f"Đưa vào Hàng đợi ({len(urls)})" if urls else "Đưa vào Hàng đợi")
        self.submit_btn.setEnabled(bool(urls))

    def raw_text(self) -> str:
        return self.editor.toPlainText()


def parse_and_normalize_netscape_cookies(raw_text: str) -> tuple[str, int]:
    """Validate and normalize pasted Netscape `cookies.txt` content (or a pasted file path).

    Returns:
        (normalized_netscape_text, valid_cookie_line_count)
    """
    cleaned_input = (raw_text or "").strip()
    if not cleaned_input:
        return "", 0

    # If user pasted a direct path to an existing file on disk, read its content
    if "\n" not in cleaned_input and len(cleaned_input) < 520:
        candidate_path_str = cleaned_input.strip("\"'")
        try:
            candidate_path = Path(candidate_path_str).expanduser()
            if candidate_path.is_file():
                cleaned_input = candidate_path.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            pass

    out_lines: list[str] = ["# Netscape HTTP Cookie File"]
    valid_count = 0

    for raw_line in cleaned_input.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#") and not line.upper().startswith("#HTTPONLY_"):
            continue
        if "\t" in line:
            parts = line.split("\t")
            if len(parts) >= 7:
                out_lines.append("\t".join(parts[:7]))
                valid_count += 1
                continue
        # Fallback if tabs were converted to spaces when copying
        ws_parts = line.split(None, 6)
        if (
            len(ws_parts) == 7
            and ws_parts[1].upper() in ("TRUE", "FALSE")
            and ws_parts[3].upper() in ("TRUE", "FALSE")
        ):
            out_lines.append("\t".join(ws_parts))
            valid_count += 1

    if valid_count == 0:
        return "", 0
    return "\n".join(out_lines) + "\n", valid_count


class CookieVerifyDialog(QDialog):
    """Modal dialog allowing the user to directly paste Netscape `cookies.txt` content
    (or pick a `cookies.txt` file) when automatic YouTube bot verification fails.
    """

    def __init__(self, win: MainWindow, error_reason: str = "") -> None:
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Xác minh chống Bot YouTube — Dán cookies.txt")
        self.setMinimumSize(660, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        title = QLabel("Xác minh tài khoản YouTube (cookies.txt)")
        title.setObjectName("cardTitle")
        top_row.addWidget(title)
        top_row.addStretch(1)

        self.stats_label = QLabel("0 dòng cookie hợp lệ")
        self.stats_label.setObjectName("metaBadge")
        top_row.addWidget(self.stats_label)
        layout.addLayout(top_row)

        reason_prefix = (
            "YouTube yêu cầu xác minh chống Bot trên mạng này và phần mềm đã thử hết các phương án tự động.\n"
            if error_reason
            else ""
        )
        hint = QLabel(
            f"{reason_prefix}"
            "Hãy mở YouTube trên trình duyệt, dùng tiện ích 'Get cookies.txt LOCALLY' bấm Copy (hoặc Export) "
            "rồi dán trực tiếp nội dung cookies.txt vào khung bên dưới. Phần mềm sẽ tự lưu và tải lại ngay."
        )
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t1799999999\tSID\t...\n"
            ".youtube.com\tTRUE\t/\tTRUE\t1799999999\t__Secure-3PSID\t...\n\n"
            "(Bạn có thể dán trực tiếp nội dung cookies.txt hoặc dán đường dẫn tới tệp cookies.txt vào đây)"
        )

        # Pre-load existing cookies.txt if present
        existing_cookie_file = getattr(win.settings, "cookie_file", "").strip()
        if existing_cookie_file:
            try:
                p = Path(existing_cookie_file).expanduser()
                if p.is_file():
                    self.editor.setPlainText(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                pass

        self.editor.textChanged.connect(self._update_stats)
        layout.addWidget(self.editor, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.paste_btn = tool_button(
            "Dán từ Clipboard",
            self._paste_from_clipboard,
            "Dán nội dung cookies.txt vừa sao chép từ Clipboard",
            "secondaryAccentButton",
            icon_name="clipboard-paste",
            icon_size=14,
        )
        btn_row.addWidget(self.paste_btn)

        self.browse_btn = tool_button(
            "Chọn tệp .txt...",
            self._browse_cookie_file,
            "Chọn tệp cookies.txt có sẵn trên máy tính",
            "ghostButton",
            icon_name="folder-open",
            icon_size=14,
        )
        btn_row.addWidget(self.browse_btn)

        self.ext_btn = tool_button(
            "Tiện ích lấy Cookie",
            self._open_extension_page,
            "Mở trang tiện ích 'Get cookies.txt LOCALLY' trên Chrome/Edge Web Store",
            "ghostButton",
            icon_name="external-link",
            icon_size=14,
        )
        btn_row.addWidget(self.ext_btn)

        self.clear_btn = tool_button(
            "Xóa trắng",
            self.editor.clear,
            "Xóa nội dung trong khung",
            "ghostButton",
            icon_name="trash-2",
            icon_size=14,
        )
        btn_row.addWidget(self.clear_btn)

        btn_row.addStretch(1)

        cancel_btn = tool_button("Đóng", self.reject, "Đóng hộp thoại", "ghostButton")
        btn_row.addWidget(cancel_btn)

        self.submit_btn = tool_button(
            "Lưu Cookie & Tải lại ngay",
            self.accept,
            "Lưu nội dung vào cookies.txt và tự động tải lại các mục bị lỗi",
            "primaryButton",
            icon_name="check",
            icon_size=14,
        )
        btn_row.addWidget(self.submit_btn)

        layout.addLayout(btn_row)
        self._update_stats()

    def _paste_from_clipboard(self) -> None:
        clip = QApplication.clipboard().text().strip()
        if clip:
            self.editor.setPlainText(clip)

    def _browse_cookie_file(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn tệp cookies.txt", "", "Netscape cookies (*.txt);;All files (*)"
        )
        if path:
            try:
                content = Path(path).read_text(encoding="utf-8", errors="replace")
                self.editor.setPlainText(content)
            except Exception:
                self.editor.setPlainText(path)

    def _open_extension_page(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(
            QUrl("https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc")
        )

    def _update_stats(self) -> None:
        _norm, count = parse_and_normalize_netscape_cookies(self.editor.toPlainText())
        if count > 0:
            self.stats_label.setText(f"{count} dòng cookie hợp lệ")
            self.submit_btn.setEnabled(True)
        else:
            self.stats_label.setText("Chưa có cookie hợp lệ (định dạng Netscape)")
            self.submit_btn.setEnabled(False)

    def normalized_cookies(self) -> tuple[str, int]:
        return parse_and_normalize_netscape_cookies(self.editor.toPlainText())


def build_batch_page(win: MainWindow) -> QWidget:
    page = QWidget()
    page.setObjectName("pageContainer")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(24, 20, 24, 16)
    layout.setSpacing(14)

    # Page Header
    header_row = QHBoxLayout()
    header_row.setSpacing(10)
    title = QLabel("Tải hàng loạt")
    title.setObjectName("pageTitle")
    header_row.addWidget(title)

    win.batch_link_status = QLabel("Sẵn sàng — Dán nhiều liên kết để đưa vào hàng đợi chờ tải")
    win.batch_link_status.setObjectName("mutedLabel")
    header_row.addWidget(win.batch_link_status)
    header_row.addStretch(1)

    win.auto_capture_btn = tool_button(
        "Tự bắt link: Tắt",
        None,
        "Khi bật, mọi liên kết YouTube bạn Copy (Ctrl+C) sẽ tự động đưa vào Hàng đợi ở trạng thái Chờ tải",
        "ghostButton",
        icon_name="link",
        icon_size=14,
    )
    win.auto_capture_btn.setCheckable(True)
    win.auto_capture_btn.setChecked(False)
    win.auto_capture_btn.toggled.connect(win.on_auto_capture_toggled)
    header_row.addWidget(win.auto_capture_btn)

    win.batch_multiline_btn = tool_button(
        "Nhập nhiều dòng...",
        win.open_multi_link_dialog,
        "Mở hộp thoại dán nhiều dòng liên kết, dán nối tiếp nhiều lần và lọc trùng",
        "ghostButton",
        icon_name="list-plus",
        icon_size=14,
    )
    header_row.addWidget(win.batch_multiline_btn)

    layout.addLayout(header_row)

    # 1. COMMAND CARD (Matches Downloads page UI, with 'Hàng đợi' in place of 'Phân tích')
    command_card = QFrame()
    command_card.setObjectName("surfaceCard")
    cmd_layout = QVBoxLayout(command_card)
    cmd_layout.setContentsMargins(16, 14, 16, 14)
    cmd_layout.setSpacing(10)

    # Row 1: URL Input (with embedded Paste action) + Queue ("Hàng đợi") + Primary Download ("Tải xuống")
    input_row = QHBoxLayout()
    input_row.setSpacing(8)

    win.batch_url_edit = PasteAwareLineEdit()
    win.batch_url_edit.setObjectName("urlInput")
    win.batch_url_edit.setClearButtonEnabled(True)
    win.batch_url_edit.setPlaceholderText(
        "Dán 1 hoặc nhiều liên kết YouTube cùng lúc — tự động lọc trùng và đưa vào Hàng đợi..."
    )
    win.batch_url_edit.paste_interceptor = win.intercept_batch_url_paste
    win.batch_url_edit.returnPressed.connect(win.on_batch_queue_clicked)

    win.batch_paste_action = win.batch_url_edit.addAction(
        icons.icon("clipboard-paste", size=15),
        QLineEdit.ActionPosition.TrailingPosition,
    )
    win.batch_paste_action.setToolTip("Dán (1 hoặc nhiều) liên kết từ Clipboard vào Hàng đợi")
    win.batch_paste_action.triggered.connect(win.paste_to_batch_queue)
    theme_manager().changed.connect(
        lambda _m: win.batch_paste_action.setIcon(icons.icon("clipboard-paste", size=15))
    )

    input_row.addWidget(win.batch_url_edit, 1)

    win.batch_queue_btn = tool_button(
        "Hàng đợi",
        win.on_batch_queue_clicked,
        "Đưa liên kết hợp lệ vào Hàng đợi ở trạng thái Chờ tải (chưa tải ngay cho đến khi bấm Tải xuống)",
        "secondaryAccentButton",
        icon_name="list-plus",
    )
    input_row.addWidget(win.batch_queue_btn)

    win.batch_download_btn = tool_button(
        "Tải xuống",
        win.on_batch_download_clicked,
        "Bắt đầu tải xuống tất cả các mục đang chờ trong Hàng đợi",
        "primaryButton",
        icon_name="download",
    )
    input_row.addWidget(win.batch_download_btn)
    cmd_layout.addLayout(input_row)

    # Row 2: Format Config Row (Synchronized with main format controls)
    config_row = QHBoxLayout()
    config_row.setSpacing(8)

    win.batch_mode_combo = SegmentedControl()
    win.batch_mode_combo.addItem("Video", "video", icon_name="video")
    win.batch_mode_combo.addItem("Audio", "audio", icon_name="music")
    win.batch_mode_combo.setCurrentIndex(win.mode_combo.currentIndex())
    win.batch_mode_combo.currentIndexChanged.connect(win.on_batch_mode_changed)
    config_row.addWidget(win.batch_mode_combo)

    win.batch_ext_combo = QComboBox()
    win.batch_ext_combo.setMinimumWidth(86)
    win.batch_ext_combo.setToolTip("Định dạng tệp đầu ra (Container)")
    win.batch_ext_combo.currentIndexChanged.connect(win.on_batch_ext_changed)
    config_row.addWidget(win.batch_ext_combo)

    win.batch_quality_combo = QComboBox()
    win.batch_quality_combo.setMinimumWidth(128)
    win.batch_quality_combo.setToolTip("Độ phân giải video mục tiêu")
    for label, value in [
        ("Tốt nhất (Auto)", "best"),
        ("4K (2160p)", "2160"),
        ("2K (1440p)", "1440"),
        ("Full HD (1080p)", "1080"),
        ("HD (720p)", "720"),
        ("SD (480p)", "480"),
        ("360p", "360"),
    ]:
        win.batch_quality_combo.addItem(label, value)
    win.batch_quality_combo.setCurrentIndex(win.quality_combo.currentIndex())
    win.batch_quality_combo.currentIndexChanged.connect(win.on_batch_quality_changed)
    config_row.addWidget(win.batch_quality_combo)

    win.batch_audio_bitrate_combo = QComboBox()
    win.batch_audio_bitrate_combo.setMinimumWidth(128)
    win.batch_audio_bitrate_combo.setToolTip("Chất lượng âm thanh (Bitrate)")
    for label, value in [
        ("320 kbps (Cao nhất)", "320"),
        ("192 kbps (Chuẩn)", "192"),
        ("128 kbps (Nhẹ)", "128"),
    ]:
        win.batch_audio_bitrate_combo.addItem(label, value)
    win.batch_audio_bitrate_combo.setCurrentIndex(win.audio_bitrate_combo.currentIndex())
    win.batch_audio_bitrate_combo.currentIndexChanged.connect(win.on_batch_audio_bitrate_changed)
    config_row.addWidget(win.batch_audio_bitrate_combo)

    win.batch_codec_combo = QComboBox()
    win.batch_codec_combo.setMinimumWidth(148)
    win.batch_codec_combo.setToolTip("Chọn chuẩn mã hóa Video đầu ra (H.264, H.265, AV1, VP9, Auto)")
    for label, value in [
        ("H.264 (Mặc định)", "h264"),
        ("H.265 / HEVC", "h265"),
        ("AV1", "av1"),
        ("VP9", "vp9"),
        ("Giữ gốc (Auto)", "auto"),
    ]:
        win.batch_codec_combo.addItem(label, value)
    win.batch_codec_combo.setCurrentIndex(win.codec_combo.currentIndex())
    win.batch_codec_combo.currentIndexChanged.connect(win.on_batch_codec_changed)
    config_row.addWidget(win.batch_codec_combo)

    win.batch_more_options_btn = tool_button(
        "Tùy chọn ▾",
        None,
        "Mở tùy chọn cắt đoạn, phụ đề và nhúng metadata",
        "ghostButton",
        icon_name="sliders-horizontal",
        icon_size=14,
    )
    win.batch_more_options_btn.setCheckable(True)
    win.batch_more_options_btn.toggled.connect(win.on_batch_more_options_toggled)
    config_row.addWidget(win.batch_more_options_btn)

    config_row.addStretch(1)

    win.batch_folder_chip = FolderChip(win.settings.download_dir, command_card)
    win.batch_folder_chip.clicked.connect(win.choose_folder)
    config_row.addWidget(win.batch_folder_chip)

    cmd_layout.addLayout(config_row)

    # Row 3: Collapsible Advanced Media Options
    win.batch_extra_options_frame = QFrame()
    win.batch_extra_options_frame.setVisible(False)
    extra_v = QVBoxLayout(win.batch_extra_options_frame)
    extra_v.setContentsMargins(0, 6, 0, 0)
    extra_v.setSpacing(8)

    divider = QFrame()
    divider.setObjectName("dividerLine")
    extra_v.addWidget(divider)

    extra_row = QHBoxLayout()
    extra_row.setContentsMargins(0, 2, 0, 0)
    extra_row.setSpacing(10)

    extra_row.addWidget(QLabel("Cắt đoạn:"))
    win.batch_clip_start_edit = QLineEdit()
    win.batch_clip_start_edit.setPlaceholderText("00:00")
    win.batch_clip_start_edit.setFixedWidth(74)
    win.batch_clip_start_edit.textChanged.connect(win.clip_start_edit.setText)
    extra_row.addWidget(win.batch_clip_start_edit)

    extra_row.addWidget(QLabel("→"))
    win.batch_clip_end_edit = QLineEdit()
    win.batch_clip_end_edit.setPlaceholderText("05:30")
    win.batch_clip_end_edit.setFixedWidth(74)
    win.batch_clip_end_edit.textChanged.connect(win.clip_end_edit.setText)
    extra_row.addWidget(win.batch_clip_end_edit)

    extra_row.addSpacing(8)
    win.batch_subtitles_check = QCheckBox("Phụ đề (CC):")
    win.batch_subtitles_check.setChecked(win.settings.download_subtitles)
    win.batch_subtitles_check.toggled.connect(win.subtitles_check.setChecked)
    extra_row.addWidget(win.batch_subtitles_check)

    win.batch_sub_langs_edit = QLineEdit(win.settings.subtitle_langs or "vi,en")
    win.batch_sub_langs_edit.setPlaceholderText("vi,en")
    win.batch_sub_langs_edit.setFixedWidth(80)
    win.batch_sub_langs_edit.textChanged.connect(win.sub_langs_edit.setText)
    extra_row.addWidget(win.batch_sub_langs_edit)

    extra_row.addSpacing(8)
    win.batch_embed_meta_check = QCheckBox("Nhúng Metadata")
    win.batch_embed_meta_check.setChecked(win.settings.embed_metadata)
    win.batch_embed_meta_check.toggled.connect(win.embed_meta_check.setChecked)
    extra_row.addWidget(win.batch_embed_meta_check)

    extra_row.addStretch(1)
    extra_v.addLayout(extra_row)
    cmd_layout.addWidget(win.batch_extra_options_frame)

    layout.addWidget(command_card)

    win.sync_batch_format_controls()

    win.batch_queue_slot = QVBoxLayout()
    win.batch_queue_slot.setContentsMargins(0, 0, 0, 0)
    layout.addLayout(win.batch_queue_slot, 1)
    return page
