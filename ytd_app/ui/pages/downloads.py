"""Downloads page builder: URL command card, collapsible preview, filter bar, and unified job list."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ..widgets import FolderChip, SegmentedControl, icon_button, tool_button
from ...theme import theme_manager

if TYPE_CHECKING:
    from ..main_window import MainWindow


class PasteAwareLineEdit(QLineEdit):
    """QLineEdit that intercepts Ctrl+V / context-menu Paste when a custom paste handler is set."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.paste_interceptor = None

    def keyPressEvent(self, event) -> None:
        from PyQt6.QtGui import QKeySequence
        if event.matches(QKeySequence.StandardKey.Paste) and callable(self.paste_interceptor):
            if self.paste_interceptor():
                event.accept()
                return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source) -> None:
        if callable(self.paste_interceptor) and source and source.hasText():
            if self.paste_interceptor():
                return
        super().insertFromMimeData(source)


def build_downloads_page(win: MainWindow) -> QWidget:
    page = QWidget()
    page.setObjectName("pageContainer")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(24, 20, 24, 16)
    layout.setSpacing(14)

    # Page Header
    header_row = QHBoxLayout()
    title = QLabel("Tải xuống")
    title.setObjectName("pageTitle")
    header_row.addWidget(title)
    header_row.addStretch(1)
    win.link_status = QLabel("Sẵn sàng")
    win.link_status.setObjectName("mutedLabel")
    header_row.addWidget(win.link_status)
    layout.addLayout(header_row)

    # 1. COMMAND CARD
    command_card = QFrame()
    command_card.setObjectName("surfaceCard")
    cmd_layout = QVBoxLayout(command_card)
    cmd_layout.setContentsMargins(16, 14, 16, 14)
    cmd_layout.setSpacing(10)

    # Row 1: URL Input (single link by default, with embedded Paste action) + Primary Download ("Tải xuống")
    input_row = QHBoxLayout()
    input_row.setSpacing(8)

    win.url_edit = PasteAwareLineEdit()
    win.url_edit.paste_interceptor = win.intercept_main_url_paste
    win.url_edit.setObjectName("urlInput")
    win.url_edit.setClearButtonEnabled(True)
    win.url_edit.setPlaceholderText("Dán liên kết YouTube — video, Shorts hoặc playlist...")
    win.url_edit.returnPressed.connect(win.on_url_enter_pressed)
    win.url_edit.textChanged.connect(win.mark_preview_stale)
    win.batch_url_edit = win.url_edit

    win.paste_action = win.url_edit.addAction(
        icons.icon("clipboard-paste", size=15),
        QLineEdit.ActionPosition.TrailingPosition,
    )
    win.paste_action.setToolTip("Dán liên kết từ Clipboard")
    win.paste_action.triggered.connect(win.paste_from_clipboard)
    theme_manager().changed.connect(
        lambda _m: win.paste_action.setIcon(icons.icon("clipboard-paste", size=15))
    )

    # Keep paste_btn, analyze_btn & queue_btn attributes hidden for backward compatibility
    win.paste_btn = tool_button(
        "Dán",
        win.paste_from_clipboard,
        "Dán liên kết từ Clipboard",
        "ghostButton",
        icon_name="clipboard-paste",
    )
    win.paste_btn.setVisible(False)
    win.paste_btn.setParent(command_card)

    win.analyze_btn = tool_button(
        "Phân tích",
        win.start_analysis,
        "Xem trước thông tin video, chọn luồng codec hoặc chọn từng video trong playlist",
        "secondaryAccentButton",
    )
    win.analyze_btn.setVisible(False)
    win.analyze_btn.setParent(command_card)

    win.queue_btn = tool_button(
        "Hàng đợi",
        win.on_queue_btn_clicked,
        "Thêm liên kết vào danh sách Chờ tải",
        "secondaryAccentButton",
        icon_name="list-plus",
    )
    win.queue_btn.setVisible(False)
    win.queue_btn.setParent(command_card)
    win.batch_queue_btn = win.queue_btn

    input_row.addWidget(win.url_edit, 1)

    win.add_btn = tool_button(
        "Tải xuống",
        win.on_primary_download_clicked,
        "Thêm liên kết đang nhập (nếu có) và bắt đầu chạy tải toàn bộ Hàng đợi ngay lập tức",
        "primaryButton",
        icon_name="download",
    )
    win.batch_download_btn = win.add_btn
    input_row.addWidget(win.add_btn)
    cmd_layout.addLayout(input_row)

    # Row 2: Segmented Video|Audio + Container + Quality/Bitrate + Codec + Options toggle + Right-aligned Multi-line & Auto-capture
    config_row = QHBoxLayout()
    config_row.setSpacing(8)

    win.mode_combo = SegmentedControl()
    win.mode_combo.addItem("Video", "video", icon_name="video")
    win.mode_combo.addItem("Audio", "audio", icon_name="music")
    win.mode_combo.setCurrentIndex(0 if win.settings.default_mode == "video" else 1)
    win.mode_combo.currentIndexChanged.connect(win.mode_changed)
    config_row.addWidget(win.mode_combo)

    win.ext_combo = QComboBox()
    win.ext_combo.setMinimumWidth(86)
    win.ext_combo.setToolTip("Định dạng tệp đầu ra (Container)")
    win.ext_combo.currentIndexChanged.connect(win.on_ext_changed)
    config_row.addWidget(win.ext_combo)

    win.quality_label = QLabel("Chất lượng:")
    win.quality_label.setVisible(False)

    win.quality_combo = QComboBox()
    win.quality_combo.setMinimumWidth(128)
    win.quality_combo.setToolTip("Độ phân giải video mục tiêu")
    for label, value in [
        ("Tốt nhất (Auto)", "best"),
        ("4K (2160p)", "2160"),
        ("2K (1440p)", "1440"),
        ("Full HD (1080p)", "1080"),
        ("HD (720p)", "720"),
        ("SD (480p)", "480"),
        ("360p", "360"),
    ]:
        win.quality_combo.addItem(label, value)
    win.quality_combo.currentIndexChanged.connect(win.schedule_save)
    config_row.addWidget(win.quality_combo)

    win.audio_bitrate_combo = QComboBox()
    win.audio_bitrate_combo.setMinimumWidth(128)
    win.audio_bitrate_combo.setToolTip("Chất lượng âm thanh (Bitrate)")
    for label, value in [
        ("320 kbps (Cao nhất)", "320"),
        ("192 kbps (Chuẩn)", "192"),
        ("128 kbps (Nhẹ)", "128"),
    ]:
        win.audio_bitrate_combo.addItem(label, value)
    ab_idx = win.audio_bitrate_combo.findData(win.settings.default_audio_bitrate)
    win.audio_bitrate_combo.setCurrentIndex(ab_idx if ab_idx >= 0 else 1)
    win.audio_bitrate_combo.currentIndexChanged.connect(win.on_audio_bitrate_changed)
    config_row.addWidget(win.audio_bitrate_combo)

    win.codec_label = QLabel("Codec:")
    win.codec_label.setVisible(False)

    win.codec_combo = QComboBox()
    win.codec_combo.setMinimumWidth(148)
    win.codec_combo.setToolTip(
        "Chọn chuẩn mã hóa Video đầu ra.\n"
        "• H.264 (Mặc định): Tương thích mọi tivi, điện thoại, phần mềm dựng phim.\n"
        "• H.265 (HEVC): Nén cao, giữ nguyên chất lượng với dung lượng nhẹ.\n"
        "• Nếu file tải từ YouTube chưa đúng chuẩn này, ứng dụng tự động chuyển đổi bằng FFmpeg (ưu tiên GPU)."
    )
    for label, value in [
        ("H.264 (Mặc định)", "h264"),
        ("H.265 / HEVC", "h265"),
        ("AV1", "av1"),
        ("VP9", "vp9"),
        ("Giữ gốc (Auto)", "auto"),
    ]:
        win.codec_combo.addItem(label, value)
    c_idx = win.codec_combo.findData(win.settings.default_video_codec)
    win.codec_combo.setCurrentIndex(c_idx if c_idx >= 0 else 0)
    win.codec_combo.currentIndexChanged.connect(win.on_codec_changed)
    config_row.addWidget(win.codec_combo)

    win.mute_btn = tool_button(
        "Âm thanh: Bật",
        None,
        "Đang bật âm thanh (Bấm để chuyển sang chế độ Tắt tiếng / Video-only)",
        "ghostButton",
        icon_name="volume-2",
        icon_size=14,
    )
    win.mute_btn.setCheckable(True)
    win.mute_btn.setChecked(False)
    win.mute_btn.toggled.connect(win.on_mute_toggled)
    config_row.addWidget(win.mute_btn)

    win.more_options_btn = tool_button(
        "Tùy chọn ▾",
        None,
        "Mở tùy chọn cắt đoạn, phụ đề, metadata và tải cả playlist",
        "ghostButton",
        icon_name="sliders-horizontal",
        icon_size=14,
    )
    win.more_options_btn.setCheckable(True)
    win.more_options_btn.toggled.connect(win.on_more_options_toggled)
    config_row.addWidget(win.more_options_btn)

    win.playlist_chip = QPushButton("Playlist")
    win.playlist_chip.setObjectName("ghostButton")
    win.playlist_chip.setCheckable(True)
    win.playlist_chip.setChecked(win.settings.last_playlist)
    win.playlist_chip.setVisible(win.settings.last_playlist)
    win.playlist_chip.setCursor(Qt.CursorShape.PointingHandCursor)
    win.playlist_chip.setToolTip("Đang bật chế độ tải cả Playlist (bấm để tắt)")
    win.playlist_chip.clicked.connect(lambda checked: win.playlist_check.setChecked(checked))
    config_row.addWidget(win.playlist_chip)

    config_row.addStretch(1)

    win.multiline_btn = tool_button(
        "Nhập nhiều dòng...",
        win.open_multiline_dialog,
        "Mở hộp thoại dán hoặc nhập nhiều dòng liên kết YouTube cùng lúc",
        "ghostButton",
        icon_name="list-plus",
        icon_size=14,
    )
    win.batch_multiline_btn = win.multiline_btn
    config_row.addWidget(win.multiline_btn)

    win.auto_capture_btn = tool_button(
        "Tự bắt link: Tắt",
        None,
        "Tự động bắt liên kết YouTube khi bạn sao chép (Copy) vào Clipboard và đưa vào Hàng đợi (Mặc định: Tắt)",
        "ghostButton",
        icon_name="clipboard-paste",
        icon_size=14,
    )
    win.auto_capture_btn.setCheckable(True)
    win.auto_capture_btn.setChecked(False)
    win.auto_capture_btn.toggled.connect(win.on_auto_capture_toggled)
    config_row.addWidget(win.auto_capture_btn)

    # Storage folder chip will be mounted on the bottom statusBar (left-aligned)
    win.folder_chip = FolderChip(win.settings.download_dir, page)
    win.folder_chip.clicked.connect(win.choose_folder)

    cmd_layout.addLayout(config_row)

    # Row 3: Collapsible Advanced Media Options (Clip Trimmer + Subtitles + Metadata + Playlist)
    win.extra_options_frame = QFrame()
    win.extra_options_frame.setVisible(False)
    extra_v = QVBoxLayout(win.extra_options_frame)
    extra_v.setContentsMargins(0, 6, 0, 0)
    extra_v.setSpacing(8)

    divider = QFrame()
    divider.setObjectName("dividerLine")
    extra_v.addWidget(divider)

    extra_row = QHBoxLayout()
    extra_row.setContentsMargins(0, 2, 0, 0)
    extra_row.setSpacing(10)

    extra_row.addWidget(QLabel("Cắt đoạn:"))
    win.clip_start_edit = QLineEdit()
    win.clip_start_edit.setPlaceholderText("00:00")
    win.clip_start_edit.setFixedWidth(74)
    win.clip_start_edit.setToolTip("Thời điểm bắt đầu (VD: 01:15 hoặc 00:02:30)")
    extra_row.addWidget(win.clip_start_edit)

    extra_row.addWidget(QLabel("→"))
    win.clip_end_edit = QLineEdit()
    win.clip_end_edit.setPlaceholderText("05:30")
    win.clip_end_edit.setFixedWidth(74)
    win.clip_end_edit.setToolTip("Thời điểm kết thúc (VD: 05:30)")
    extra_row.addWidget(win.clip_end_edit)

    extra_row.addSpacing(8)
    win.subtitles_check = QCheckBox("Phụ đề (CC):")
    win.subtitles_check.setChecked(win.settings.download_subtitles)
    win.subtitles_check.toggled.connect(win.on_subtitles_toggled)
    extra_row.addWidget(win.subtitles_check)

    win.sub_langs_edit = QLineEdit(win.settings.subtitle_langs or "vi,en")
    win.sub_langs_edit.setPlaceholderText("vi,en")
    win.sub_langs_edit.setFixedWidth(80)
    win.sub_langs_edit.setToolTip("Mã ngôn ngữ phụ đề cách nhau bởi dấu phẩy (VD: vi,en,ja)")
    win.sub_langs_edit.editingFinished.connect(win.on_subtitles_toggled)
    extra_row.addWidget(win.sub_langs_edit)

    extra_row.addSpacing(8)
    win.embed_meta_check = QCheckBox("Nhúng Metadata")
    win.embed_meta_check.setChecked(win.settings.embed_metadata)
    win.embed_meta_check.toggled.connect(win.on_embed_meta_toggled)
    extra_row.addWidget(win.embed_meta_check)

    extra_row.addSpacing(8)
    win.playlist_check = QCheckBox("Tải cả Playlist")
    win.playlist_check.setToolTip("Phân tích và tải toàn bộ Playlist (tối đa 150 video)")
    win.playlist_check.setChecked(win.settings.last_playlist)
    win.playlist_check.toggled.connect(win.on_playlist_toggle)
    extra_row.addWidget(win.playlist_check)

    extra_row.addStretch(1)
    extra_v.addLayout(extra_row)
    cmd_layout.addWidget(win.extra_options_frame)

    layout.addWidget(command_card)

    win.mode_changed()
    q_idx = win.quality_combo.findData(win.settings.last_quality)
    win.quality_combo.setCurrentIndex(q_idx if q_idx >= 0 else 0)

    # 2. COLLAPSIBLE PREVIEW CARD
    win.preview_card = QFrame()
    win.preview_card.setObjectName("previewCard")
    win.preview_card.setVisible(False)
    preview_outer = QVBoxLayout(win.preview_card)
    preview_outer.setContentsMargins(16, 12, 16, 12)
    preview_outer.setSpacing(10)

    preview_header = QHBoxLayout()
    win.preview_badge_title = QLabel("XEM TRƯỚC NỘI DUNG")
    win.preview_badge_title.setObjectName("sectionTitle")
    preview_header.addWidget(win.preview_badge_title)

    win.video_count_label = QLabel("")
    win.video_count_label.setObjectName("metaBadge")
    preview_header.addWidget(win.video_count_label)
    preview_header.addStretch(1)

    win.close_preview_btn = icon_button(
        "x",
        lambda: win.preview_card.setVisible(False),
        "Thu gọn khung xem trước",
    )
    preview_header.addWidget(win.close_preview_btn)
    preview_outer.addLayout(preview_header)

    win.preview_stack = QStackedWidget()
    preview_outer.addWidget(win.preview_stack)

    # Stack Page 0: Single Video Preview
    video_page = QWidget()
    video_page_layout = QVBoxLayout(video_page)
    video_page_layout.setContentsMargins(0, 0, 0, 0)
    video_page_layout.setSpacing(10)

    video_info_row = QHBoxLayout()
    video_info_row.setSpacing(14)

    win.preview_image = QLabel("Thumbnail")
    win.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
    win.preview_image.setFixedSize(176, 99)
    win.preview_image.setObjectName("thumbnail")
    video_info_row.addWidget(win.preview_image)

    meta_col = QVBoxLayout()
    meta_col.setSpacing(6)
    win.preview_title = QLabel("Nhập liên kết để xem thông tin")
    win.preview_title.setWordWrap(True)
    win.preview_title.setObjectName("cardTitle")
    win.preview_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    win.preview_title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    meta_col.addWidget(win.preview_title)

    adv_row = QHBoxLayout()
    win.exact_format_check = QCheckBox("Chọn luồng thủ công từ bảng Format ID")
    win.exact_format_check.setToolTip("Mở bảng danh sách toàn bộ luồng video/audio gốc từ YouTube")
    win.exact_format_check.toggled.connect(win.on_exact_format_toggled)
    adv_row.addWidget(win.exact_format_check)
    adv_row.addStretch(1)

    win.preview_download_btn = tool_button(
        "Tải video này",
        win.add_from_preview,
        "Đưa video đang xem trước vào hàng đợi và tải ngay",
        "primaryButton",
        icon_name="download",
    )
    adv_row.addWidget(win.preview_download_btn)
    meta_col.addLayout(adv_row)

    video_info_row.addLayout(meta_col, 1)
    video_page_layout.addLayout(video_info_row)

    win.formats_table = QTableWidget(0, 8)
    win.formats_table.setHorizontalHeaderLabels([
        "ID", "Đuôi", "Độ phân giải", "FPS", "Video codec", "Audio codec", "Bitrate", "Dung lượng"
    ])
    win.formats_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    win.formats_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    win.formats_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    win.formats_table.verticalHeader().setVisible(False)
    win.formats_table.setAlternatingRowColors(True)
    win.formats_table.setColumnWidth(0, 80)
    win.formats_table.setColumnWidth(1, 65)
    win.formats_table.setColumnWidth(2, 120)
    win.formats_table.setColumnWidth(3, 55)
    win.formats_table.setColumnWidth(4, 130)
    win.formats_table.setColumnWidth(5, 130)
    win.formats_table.setColumnWidth(6, 100)
    win.formats_table.horizontalHeader().setStretchLastSection(True)
    win.formats_table.setFixedHeight(165)
    win.formats_table.setVisible(False)
    video_page_layout.addWidget(win.formats_table)

    win.preview_stack.addWidget(video_page)

    # Stack Page 1: Playlist Preview
    playlist_page = QWidget()
    playlist_page_layout = QVBoxLayout(playlist_page)
    playlist_page_layout.setContentsMargins(0, 0, 0, 0)
    playlist_page_layout.setSpacing(8)

    pl_top_row = QHBoxLayout()
    win.playlist_title_label = QLabel("Playlist")
    win.playlist_title_label.setObjectName("cardTitle")
    pl_top_row.addWidget(win.playlist_title_label, 1)

    pl_top_row.addWidget(tool_button(
        "Chọn tất cả",
        lambda: win.set_all_playlist_items(True),
        "Chọn tất cả video trong playlist",
        "ghostButton",
    ))
    pl_top_row.addWidget(tool_button(
        "Bỏ chọn tất cả",
        lambda: win.set_all_playlist_items(False),
        "Bỏ chọn toàn bộ video",
        "ghostButton",
    ))
    win.playlist_download_btn = tool_button(
        "Tải các video đã chọn",
        win.add_from_preview,
        "Thêm các video được tích chọn vào hàng đợi và tải ngay",
        "primaryButton",
        icon_name="download",
    )
    pl_top_row.addWidget(win.playlist_download_btn)
    playlist_page_layout.addLayout(pl_top_row)

    win.playlist_scroll = QScrollArea()
    win.playlist_scroll.setWidgetResizable(True)
    win.playlist_scroll.setFixedHeight(155)
    win.playlist_list_container = QWidget()
    win.playlist_list_container.setObjectName("scrollContents")
    win.playlist_list_layout = QVBoxLayout(win.playlist_list_container)
    win.playlist_list_layout.setContentsMargins(10, 8, 10, 8)
    win.playlist_list_layout.setSpacing(6)
    win.playlist_scroll.setWidget(win.playlist_list_container)
    playlist_page_layout.addWidget(win.playlist_scroll)

    win.preview_stack.addWidget(playlist_page)
    layout.addWidget(win.preview_card)

    # 3. SHARED QUEUE SECTION (Filter Bar + Unified Job List Card)
    win.queue_section = QWidget(page)
    queue_sec_layout = QVBoxLayout(win.queue_section)
    queue_sec_layout.setContentsMargins(0, 0, 0, 0)
    queue_sec_layout.setSpacing(10)

    filter_bar = QHBoxLayout()
    filter_bar.setSpacing(4)

    win.tab_group = QButtonGroup(win)
    win.tab_group.setExclusive(True)
    win.tab_buttons = {}
    for key, text in [
        ("recent", "Gần đây 0"),
        ("all", "Tất cả 0"),
        ("queued", "Hàng chờ 0"),
        ("active", "Đang tải 0"),
        ("done", "Hoàn tất 0"),
        ("error", "Lỗi 0"),
    ]:
        btn = QPushButton(text)
        btn.setObjectName("tabButton")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if key == "recent":
            btn.setChecked(True)
        btn.clicked.connect(lambda _checked=False, k=key: win.on_filter_pill_clicked(k))
        win.tab_group.addButton(btn)
        win.tab_buttons[key] = btn
        filter_bar.addWidget(btn)

    filter_bar.addStretch(1)

    win.retry_all_btn = tool_button(
        "Tải lại tất cả",
        win.retry_all_visible,
        "Tải lại tất cả các mục trong tab trạng thái đang mở theo cấu hình hiện tại",
        "ghostButton",
        icon_name="rotate-cw",
        icon_size=14,
    )
    filter_bar.addWidget(win.retry_all_btn)

    win.undo_btn = tool_button(
        "Hoàn tác",
        win.undo_last_remove,
        "Hoàn tác thao tác xóa gần nhất để khôi phục lại tác vụ vào hàng đợi",
        "ghostButton",
        icon_name="undo-2",
        icon_size=14,
    )
    win.undo_btn.setEnabled(False)
    filter_bar.addWidget(win.undo_btn)

    win.redo_btn = tool_button(
        "Làm lại",
        win.redo_last_remove,
        "Làm lại thao tác xóa vừa hoàn tác trong tab hiện tại",
        "ghostButton",
        icon_name="redo-2",
        icon_size=14,
    )
    win.redo_btn.setEnabled(False)
    filter_bar.addWidget(win.redo_btn)

    win.clear_all_btn = tool_button(
        "Xóa tất cả",
        win.clear_all_jobs,
        "Xóa tất cả tác vụ khỏi hàng đợi (có thể bấm Hoàn tác để khôi phục)",
        "ghostButton",
        icon_name="trash-2",
        icon_size=14,
    )
    filter_bar.addWidget(win.clear_all_btn)

    win.search_edit = QLineEdit()
    win.search_edit.setObjectName("searchInput")
    win.search_edit.setClearButtonEnabled(True)
    win.search_edit.setPlaceholderText("Tìm kiếm tác vụ...")
    win.search_edit.setFixedWidth(185)
    search_act = win.search_edit.addAction(
        icons.icon("search", size=14),
        QLineEdit.ActionPosition.LeadingPosition,
    )
    theme_manager().changed.connect(
        lambda _m: search_act.setIcon(icons.icon("search", size=14))
    )
    win.search_edit.textChanged.connect(win.apply_job_filters)
    filter_bar.addWidget(win.search_edit)

    win.start_btn = icon_button(
        "play",
        win.toggle_queue_running,
        "Tiếp tục tải / Tạm dừng tất cả tác vụ",
    )
    filter_bar.addWidget(win.start_btn)

    # Hidden compatibility buttons for direct method calls
    win.stop_queue_btn = tool_button("Tạm dừng hết", win.pause_all_active)
    win.stop_queue_btn.setVisible(False)
    win.stop_queue_btn.setParent(page)
    win.resume_all_btn = tool_button("Tiếp tục hết", win.resume_all_paused)
    win.resume_all_btn.setVisible(False)
    win.resume_all_btn.setParent(page)
    win.retry_failed_btn = tool_button("Tải lại lỗi", win.retry_all_failed)
    win.retry_failed_btn.setVisible(False)
    win.retry_failed_btn.setParent(page)
    win.clear_done_btn = tool_button("Dọn mục xong", win.clear_completed_jobs)
    win.clear_done_btn.setVisible(False)
    win.clear_done_btn.setParent(page)

    def open_bulk_menu() -> None:
        menu = QMenu(win)
        a_pause = menu.addAction(icons.icon("pause", size=14), "Tạm dừng tất cả đang chạy")
        a_pause.triggered.connect(win.pause_all_active)
        a_resume = menu.addAction(icons.icon("play", size=14), "Tiếp tục tất cả đang dừng")
        a_resume.triggered.connect(win.resume_all_paused)
        a_retry_vis = menu.addAction(icons.icon("rotate-cw", size=14), "Tải lại tất cả trong mục đang xem")
        a_retry_vis.triggered.connect(win.retry_all_visible)
        a_retry = menu.addAction(icons.icon("rotate-cw", size=14), "Tải lại tất cả mục lỗi")
        a_retry.triggered.connect(win.retry_all_failed)
        menu.addSeparator()
        a_clear = menu.addAction(icons.icon("trash-2", size=14), "Dọn sạch mục đã hoàn tất")
        a_clear.triggered.connect(win.clear_completed_jobs)
        a_clear_all = menu.addAction(icons.icon("trash-2", size=14), "Xóa tất cả hàng đợi")
        a_clear_all.triggered.connect(win.clear_all_jobs)
        if win.deleted_jobs_stack:
            a_undo = menu.addAction(icons.icon("undo-2", size=14), "Hoàn tác lần xóa vừa rồi")
            a_undo.triggered.connect(win.undo_last_remove)
        cur_tab = getattr(win, "current_filter", "recent")
        redo_stack = win.tab_redo_stacks.get(cur_tab, []) if hasattr(win, "tab_redo_stacks") else []
        if redo_stack:
            a_redo = menu.addAction(icons.icon("redo-2", size=14), "Làm lại lần xóa vừa hoàn tác")
            a_redo.triggered.connect(win.redo_last_remove)
        menu.exec(win.bulk_menu_btn.mapToGlobal(QPoint(0, win.bulk_menu_btn.height() + 2)))

    win.bulk_menu_btn = icon_button(
        "ellipsis",
        open_bulk_menu,
        "Thao tác hàng loạt (Tạm dừng hết, Tiếp tục hết, Tải lại lỗi, Dọn mục xong, Xóa tất cả)",
    )
    filter_bar.addWidget(win.bulk_menu_btn)

    queue_sec_layout.addLayout(filter_bar)

    # 4. UNIFIED JOB LIST CARD (scrollable rows inside one bordered container)
    list_card = QFrame()
    list_card.setObjectName("listCard")
    list_card_layout = QVBoxLayout(list_card)
    list_card_layout.setContentsMargins(0, 2, 0, 2)
    list_card_layout.setSpacing(0)

    win.cards_scroll = QScrollArea()
    win.cards_scroll.setWidgetResizable(True)
    win.cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    win.cards_container = QWidget()
    win.cards_container.setObjectName("scrollContents")
    win.cards_layout = QVBoxLayout(win.cards_container)
    win.cards_layout.setContentsMargins(0, 0, 0, 0)
    win.cards_layout.setSpacing(0)

    win.empty_state_frame = QFrame()
    win.empty_state_frame.setStyleSheet("QFrame { background: transparent; border: none; }")
    empty_layout = QVBoxLayout(win.empty_state_frame)
    empty_layout.setContentsMargins(24, 56, 24, 56)
    empty_layout.setSpacing(6)

    win.empty_icon_label = QLabel()
    win.empty_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    empty_layout.addWidget(win.empty_icon_label)

    def _paint_empty_icon(*_args) -> None:
        t = theme_manager().tokens
        win.empty_icon_label.setPixmap(icons.render_svg_pixmap("download", t["muted"], size=28, dpr=2.0))

    _paint_empty_icon()
    theme_manager().changed.connect(_paint_empty_icon)

    win.empty_title_label = QLabel("Chưa có tác vụ tải xuống nào")
    win.empty_title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    win.empty_title_label.setObjectName("cardTitle")

    win.empty_sub_label = QLabel(
        "Dán liên kết YouTube ở khung phía trên và bấm 'Tải xuống'."
    )
    win.empty_sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    win.empty_sub_label.setObjectName("mutedLabel")
    empty_layout.addWidget(win.empty_title_label)
    empty_layout.addWidget(win.empty_sub_label)

    win.cards_layout.addWidget(win.empty_state_frame)
    win.cards_layout.addStretch(1)
    win.cards_scroll.setWidget(win.cards_container)
    list_card_layout.addWidget(win.cards_scroll, 1)

    win.job_table = QTableWidget(0, 8)
    win.job_table.setVisible(False)
    list_card_layout.addWidget(win.job_table)

    queue_sec_layout.addWidget(list_card, 1)

    win.downloads_queue_slot = QVBoxLayout()
    win.downloads_queue_slot.setContentsMargins(0, 0, 0, 0)
    win.downloads_queue_slot.addWidget(win.queue_section, 1)
    layout.addLayout(win.downloads_queue_slot, 1)
    return page
