"""Auto-saving Settings page builder inside the main workspace stack."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..widgets import SectionCard, SegmentedControl, SettingRow, tool_button
from ...theme import progress_bar_qss, status_badge_qss, theme_manager
from ...updater import UpdateInfo, launch_staged_updater
from ...version import APP_VERSION, DEFAULT_GITHUB_REPO, app_data_dir, default_download_dir
from ...workers import UpdateCheckWorker, UpdateDownloadWorker, YtDlpUpdateWorker

if TYPE_CHECKING:
    from ..main_window import MainWindow


def build_settings_page(win: MainWindow) -> QWidget:
    outer_page = QWidget()
    outer_page.setObjectName("pageContainer")
    outer_v = QVBoxLayout(outer_page)
    outer_v.setContentsMargins(24, 20, 24, 16)
    outer_v.setSpacing(12)

    header = QHBoxLayout()
    title = QLabel("Cài đặt")
    title.setObjectName("pageTitle")
    header.addWidget(title)
    sub = QLabel("Mọi thay đổi được tự động lưu ngay lập tức")
    sub.setObjectName("mutedLabel")
    header.addSpacing(8)
    header.addWidget(sub)
    header.addStretch(1)
    outer_v.addLayout(header)

    # Sub-tabs Navigation using SegmentedControl
    win.settings_sub_segment = SegmentedControl()
    win.settings_sub_segment.addItem("Chung", 0, icon_name="sliders-horizontal")
    win.settings_sub_segment.addItem("Cập nhật", 1, icon_name="refresh-cw")
    win.settings_sub_segment.addItem("Giới thiệu", 2, icon_name="info")
    outer_v.addWidget(win.settings_sub_segment)

    win.settings_stack = QStackedWidget()

    # -------------------------------------------------------------
    # TAB 1: CÀI ĐẶT CHUNG (Theme, Tải xuống, Mã hóa, Hệ thống)
    # -------------------------------------------------------------
    tab_general_scroll = QScrollArea()
    tab_general_scroll.setWidgetResizable(True)
    tab_general_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    general_content = QWidget()
    general_content.setObjectName("scrollContents")
    v_general = QVBoxLayout(general_content)
    v_general.setContentsMargins(0, 0, 8, 12)
    v_general.setSpacing(14)

    # -------------------------------------------------------------
    # TAB 2: CẬP NHẬT (Môi trường runtime & Cập nhật ứng dụng/yt-dlp)
    # -------------------------------------------------------------
    tab_update_scroll = QScrollArea()
    tab_update_scroll.setWidgetResizable(True)
    tab_update_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    update_content = QWidget()
    update_content.setObjectName("scrollContents")
    v_update = QVBoxLayout(update_content)
    v_update.setContentsMargins(0, 0, 8, 12)
    v_update.setSpacing(14)

    # -------------------------------------------------------------
    # TAB 3: GIỚI THIỆU
    # -------------------------------------------------------------
    tab_about_scroll = QScrollArea()
    tab_about_scroll.setWidgetResizable(True)
    tab_about_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    about_content = QWidget()
    about_content.setObjectName("scrollContents")
    v_about = QVBoxLayout(about_content)
    v_about.setContentsMargins(0, 0, 8, 12)
    v_about.setSpacing(14)

    win.settings_sub_segment.currentIndexChanged.connect(win.settings_stack.setCurrentIndex)

    # ==================================================================
    # 1. GIAO DIỆN (SÁNG / TỐI / HỆ THỐNG)
    # ==================================================================
    theme_card = SectionCard("Giao diện")
    win.theme_segment = SegmentedControl()
    win.theme_segment.addItem("Theo hệ thống", "system", icon_name="monitor")
    win.theme_segment.addItem("Sáng", "light", icon_name="sun")
    win.theme_segment.addItem("Tối", "dark", icon_name="moon")
    t_idx = win.theme_segment.findData(win.settings.theme_mode)
    win.theme_segment.setCurrentIndex(t_idx if t_idx >= 0 else 0)
    win.theme_segment.currentIndexChanged.connect(win.on_theme_preference_changed)

    theme_card.body_layout.addWidget(
        SettingRow(
            "Chế độ màu",
            "Tự động đồng bộ theo Windows hoặc cố định giao diện Sáng / Tối",
            win.theme_segment,
        )
    )
    v_general.addWidget(theme_card)

    # ==================================================================
    # 2. TẢI XUỐNG & LƯU TRỮ
    # ==================================================================
    dl_card = SectionCard("Tải xuống & Lưu trữ")

    folder_box = QWidget()
    folder_row = QHBoxLayout(folder_box)
    folder_row.setContentsMargins(0, 0, 0, 0)
    folder_row.setSpacing(6)
    win.folder_edit = QLineEdit(win.settings.download_dir)
    win.folder_edit.setMinimumWidth(280)
    win.folder_edit.setPlaceholderText("Thư mục lưu file tải về")
    win.folder_edit.editingFinished.connect(win.on_folder_edited)
    win.folder_edit.textChanged.connect(win.on_folder_text_changed)
    folder_row.addWidget(win.folder_edit, 1)
    folder_row.addWidget(
        tool_button("Chọn...", win.choose_folder, "Chọn thư mục lưu file", icon_name="folder")
    )
    folder_row.addWidget(
        tool_button(
            "Mặc định",
            win.reset_default_folder,
            f"Đặt về mặc định: {default_download_dir()}",
            icon_name="rotate-cw",
        )
    )
    folder_row.addWidget(
        tool_button(
            "Mở",
            win.open_download_folder,
            "Mở thư mục tải xuống trong File Explorer",
            icon_name="folder-open",
        )
    )
    dl_card.body_layout.addWidget(
        SettingRow("Thư mục lưu tải xuống", "Nơi lưu các tập tin video và âm thanh", folder_box)
    )

    win.quick_download_check = QCheckBox("Bật tải nhanh 1-click")
    win.quick_download_check.setChecked(win.settings.quick_download)
    win.quick_download_check.toggled.connect(win.on_quick_download_toggle)
    dl_card.body_layout.addWidget(
        SettingRow(
            "Tải nhanh 1-click",
            "Khi bật, bấm 'Tải xuống' hoặc nhấn Enter sẽ đưa thẳng video đơn vào hàng đợi mà không cần phân tích trước",
            win.quick_download_check,
        )
    )

    win.id_suffix_check = QCheckBox("Thêm mã ID vào tên file")
    win.id_suffix_check.setChecked(getattr(win.settings, "append_id_suffix", False))
    win.id_suffix_check.toggled.connect(win.on_id_suffix_toggled)
    dl_card.body_layout.addWidget(
        SettingRow(
            "Hậu tố mã ID video",
            "Mặc định tắt (lấy tên gốc). Bật nếu muốn thêm [id] vào cuối tên file để tránh trùng lặp",
            win.id_suffix_check,
        )
    )

    win.concurrent_spin = QSpinBox()
    win.concurrent_spin.setRange(1, 5)
    win.concurrent_spin.setValue(win.settings.max_concurrent)
    win.concurrent_spin.setFixedWidth(72)
    win.concurrent_spin.valueChanged.connect(win.concurrent_changed)
    dl_card.body_layout.addWidget(
        SettingRow(
            "Số tác vụ tải đồng thời",
            "Số lượng video tối đa được tải song song cùng lúc (1 – 5)",
            win.concurrent_spin,
        )
    )

    win.fragments_spin = QSpinBox()
    win.fragments_spin.setRange(1, 8)
    win.fragments_spin.setValue(win.settings.fragment_connections)
    win.fragments_spin.setFixedWidth(72)
    win.fragments_spin.valueChanged.connect(win.on_fragments_changed)
    dl_card.body_layout.addWidget(
        SettingRow(
            "Kết nối phân mảnh mỗi video",
            "Số luồng tải song song các mảnh của một video (1 – 8, khuyên dùng 4 để tăng tốc tối đa)",
            win.fragments_spin,
        )
    )

    win.browser_cookie_combo = QComboBox()
    win.browser_cookie_combo.setMinimumWidth(310)
    for b_label, b_val in [
        ("Tự động khi YouTube hỏi xác minh Bot (Khuyên dùng)", "auto"),
        ("Không dùng", ""),
        ("Firefox (Hoạt động cả khi đang mở trình duyệt)", "firefox"),
        ("Microsoft Edge", "edge"),
        ("Brave", "brave"),
        ("Google Chrome", "chrome"),
        ("Opera", "opera"),
        ("Vivaldi", "vivaldi"),
    ]:
        win.browser_cookie_combo.addItem(b_label, b_val)
    bc_idx = win.browser_cookie_combo.findData(getattr(win.settings, "cookies_from_browser", "auto"))
    win.browser_cookie_combo.setCurrentIndex(bc_idx if bc_idx >= 0 else 0)
    win.browser_cookie_combo.currentIndexChanged.connect(win.on_browser_cookie_changed)
    dl_card.body_layout.addWidget(
        SettingRow(
            "Lấy Cookie từ trình duyệt",
            "Tự động vượt lỗi 'Sign in to confirm you're not a bot' bằng tài khoản YouTube đã đăng nhập trên trình duyệt",
            win.browser_cookie_combo,
        )
    )

    cookie_box = QWidget()
    cookie_row = QHBoxLayout(cookie_box)
    cookie_row.setContentsMargins(0, 0, 0, 0)
    cookie_row.setSpacing(6)
    win.cookie_edit = QLineEdit(win.settings.cookie_file)
    win.cookie_edit.setMinimumWidth(220)
    win.cookie_edit.setPlaceholderText("Đường dẫn cookies.txt (Netscape format - tùy chọn)")
    win.cookie_edit.editingFinished.connect(win.on_cookie_edited)
    cookie_row.addWidget(win.cookie_edit, 1)
    cookie_row.addWidget(
        tool_button(
            "Dán cookies.txt...",
            lambda: win.open_cookie_paste_dialog(),
            "Dán trực tiếp nội dung cookies.txt vào phần mềm",
            "secondaryAccentButton",
            icon_name="clipboard-paste",
            icon_size=14,
        )
    )
    cookie_row.addWidget(
        tool_button("Chọn...", lambda: win.browse_cookie(win.cookie_edit), "Chọn tệp cookies.txt")
    )
    cookie_row.addWidget(
        tool_button("Xóa", win.clear_cookie_file, "Xóa đường dẫn cookies")
    )
    dl_card.body_layout.addWidget(
        SettingRow(
            "Tệp cookies.txt (Dán hoặc chọn tệp)",
            "Ưu tiên dùng tệp cookies.txt để xác minh tài khoản hoặc tự dán khi YouTube chặn Bot",
            cookie_box,
        )
    )

    v_general.addWidget(dl_card)

    # ==================================================================
    # 3. MÃ HÓA VIDEO (GPU / CPU)
    # ==================================================================
    codec_card = SectionCard("Mã hóa video (FFmpeg)")
    win.hw_accel_combo = QComboBox()
    win.hw_accel_combo.setMinimumWidth(310)
    for label, val in [
        ("Tự động (Ưu tiên GPU NVENC / QSV / AMF → CPU)", "auto"),
        ("NVIDIA NVENC (h264_nvenc / hevc_nvenc)", "nvenc"),
        ("Intel QuickSync (h264_qsv / hevc_qsv)", "qsv"),
        ("AMD AMF (h264_amf / hevc_amf)", "amf"),
        ("Chỉ dùng CPU (libx264 / libx265)", "cpu"),
    ]:
        win.hw_accel_combo.addItem(label, val)
    h_idx = win.hw_accel_combo.findData(win.settings.hw_accel)
    win.hw_accel_combo.setCurrentIndex(h_idx if h_idx >= 0 else 0)
    win.hw_accel_combo.currentIndexChanged.connect(win.on_hw_accel_changed)

    codec_card.body_layout.addWidget(
        SettingRow(
            "Tăng tốc phần cứng khi đổi Codec",
            "Bộ mã hóa ưu tiên khi chuyển đổi sang H.264 / H.265 / AV1 / VP9",
            win.hw_accel_combo,
        )
    )
    v_general.addWidget(codec_card)

    # ==================================================================
    # 4. HỆ THỐNG & DỮ LIỆU
    # ==================================================================
    sys_card = SectionCard("Hệ thống")

    win.keep_history_check = QCheckBox("Giữ lịch sử")
    win.keep_history_check.setChecked(win.settings.keep_history)
    win.keep_history_check.toggled.connect(win.on_system_flags_changed)
    sys_card.body_layout.addWidget(
        SettingRow(
            "Lưu lịch sử tải xuống",
            "Giữ lại danh sách các mục đã tải qua những lần khởi động lại ứng dụng",
            win.keep_history_check,
        )
    )

    win.notify_check = QCheckBox("Thông báo")
    win.notify_check.setChecked(win.settings.notify_on_complete)
    win.notify_check.toggled.connect(win.on_system_flags_changed)
    sys_card.body_layout.addWidget(
        SettingRow(
            "Thông báo khi hoàn tất hàng đợi",
            "Phát âm báo nhẹ và thông báo khay hệ thống khi toàn bộ hàng đợi tải xong",
            win.notify_check,
        )
    )

    appdata_box = QWidget()
    appdata_row = QHBoxLayout(appdata_box)
    appdata_row.setContentsMargins(0, 0, 0, 0)
    appdata_row.setSpacing(6)
    app_data_edit = QLineEdit(str(app_data_dir()))
    app_data_edit.setReadOnly(True)
    app_data_edit.setMinimumWidth(260)
    appdata_row.addWidget(app_data_edit, 1)
    appdata_row.addWidget(
        tool_button(
            "Mở thư mục",
            win.open_app_data_folder,
            "Mở thư mục dữ liệu ứng dụng",
            icon_name="folder-open",
        )
    )
    sys_card.body_layout.addWidget(
        SettingRow(
            "Thư mục dữ liệu ứng dụng",
            "Chứa tệp cấu hình, lịch sử tải và gói cập nhật",
            appdata_box,
        )
    )
    v_general.addWidget(sys_card)
    v_general.addStretch(1)

    # ==================================================================
    # 5. MÔI TRƯỜNG THỰC THI & CẬP NHẬT
    # ==================================================================
    env_card = SectionCard("Môi trường & Cập nhật")

    env_top = QHBoxLayout()
    env_sub = QLabel("Trạng thái FFmpeg, FFprobe, Deno Runtime và lõi yt-dlp")
    env_sub.setObjectName("mutedLabel")
    env_top.addWidget(env_sub)
    env_top.addStretch(1)
    win.env_status_badge = QLabel("")
    env_top.addWidget(win.env_status_badge)
    env_card.body_layout.addLayout(env_top)

    win.env_info_box = QPlainTextEdit()
    win.env_info_box.setReadOnly(True)
    win.env_info_box.setFixedHeight(92)
    env_card.body_layout.addWidget(win.env_info_box)

    _last_env_report: dict | None = None

    def refresh_env_panel(force_recheck: bool = True) -> None:
        nonlocal _last_env_report
        if force_recheck or _last_env_report is None:
            _last_env_report = win.check_environment(show_dialog=False)
        rep = _last_env_report
        missing_tools = [n for n in ("ffmpeg", "deno", "ejs") if not rep.get(n)]
        mode = theme_manager().mode
        if not missing_tools:
            win.env_status_badge.setText("● Đầy đủ thành phần")
            win.env_status_badge.setStyleSheet(status_badge_qss("done", mode))
        else:
            win.env_status_badge.setText("● Thiếu: " + ", ".join(missing_tools))
            win.env_status_badge.setStyleSheet(status_badge_qss("paused", mode))
        win.env_info_box.setPlainText(
            f"• Lõi yt-dlp     : v{rep.get('yt_dlp_version', '')}   |   yt-dlp-ejs: {'Đã tích hợp' if rep.get('ejs') else 'Chưa có'}\n"
            f"• FFmpeg         : {rep.get('ffmpeg') or 'CHƯA TÌM THẤY'}\n"
            f"• FFprobe        : {rep.get('ffprobe') or 'CHƯA TÌM THẤY'}\n"
            f"• Deno Runtime   : {rep.get('deno') or 'CHƯA TÌM THẤY'}"
        )

    win.refresh_env_panel = refresh_env_panel
    theme_manager().changed.connect(lambda _m: refresh_env_panel(force_recheck=False))

    win.auto_update_check = QCheckBox("Tự kiểm tra khi khởi động")
    win.auto_update_check.setChecked(win.settings.auto_check_updates)
    win.auto_update_check.toggled.connect(win.on_system_flags_changed)
    win.auto_update_check_tab = win.auto_update_check

    env_card.body_layout.addWidget(
        SettingRow(
            "Tự động kiểm tra bản cập nhật mới",
            "Mặc định bật: tự động kiểm tra phiên bản mới từ GitHub Releases ngay khi mở ứng dụng",
            win.auto_update_check,
        )
    )

    win.upd_status_lbl = QLabel(
        f"Phiên bản hiện tại: v{APP_VERSION}. Bấm 'Kiểm tra cập nhật' để kiểm tra bản phát hành mới."
    )
    win.upd_status_lbl.setObjectName("mutedLabel")
    win.upd_status_lbl.setWordWrap(True)
    env_card.body_layout.addWidget(win.upd_status_lbl)

    upd_btn_row = QHBoxLayout()
    btn_recheck_env = tool_button(
        "Kiểm tra lại môi trường",
        refresh_env_panel,
        icon_name="refresh-cw",
        icon_size=14,
    )
    btn_install_tools = tool_button(
        "Tự động cài FFmpeg & Deno",
        lambda: win.ensure_runtime_tools_async(force=False),
        "Tự động tải và cài đặt FFmpeg + Deno vào thư mục dữ liệu ứng dụng",
        "secondaryAccentButton",
        icon_name="cpu",
        icon_size=14,
    )
    btn_ytdlp = tool_button(
        "Cập nhật lõi yt-dlp",
        lambda: None,
        "Nâng cấp nóng gói yt-dlp lên phiên bản mới nhất",
        "secondaryAccentButton",
        icon_name="sparkles",
        icon_size=14,
    )
    btn_check = tool_button(
        "Kiểm tra cập nhật",
        lambda: None,
        "Kiểm tra phiên bản ứng dụng mới trên GitHub Releases",
        "secondaryAccentButton",
        icon_name="refresh-cw",
        icon_size=14,
    )
    btn_install = tool_button(
        "Tải & Cập nhật ngay",
        lambda: None,
        "Tải và áp dụng bản cập nhật mới",
        "primaryButton",
        icon_name="download",
        icon_size=14,
    )
    btn_install.setEnabled(False)
    upd_btn_row.addWidget(btn_recheck_env)
    upd_btn_row.addWidget(btn_install_tools)
    upd_btn_row.addWidget(btn_ytdlp)
    upd_btn_row.addWidget(btn_check)
    upd_btn_row.addWidget(btn_install)
    upd_btn_row.addStretch(1)
    env_card.body_layout.addLayout(upd_btn_row)

    win.upd_pbar = QProgressBar()
    win.upd_pbar.setRange(0, 100)
    win.upd_pbar.setValue(0)
    win.upd_pbar.setTextVisible(False)
    win.upd_pbar.setFixedHeight(6)
    win.upd_pbar.setVisible(False)
    win.upd_pbar.setStyleSheet(progress_bar_qss("downloading", theme_manager().mode))
    env_card.body_layout.addWidget(win.upd_pbar)

    win.upd_notes_box = QPlainTextEdit()
    win.upd_notes_box.setReadOnly(True)
    win.upd_notes_box.setMinimumHeight(180)
    win.upd_notes_box.setPlaceholderText("Ghi chú phát hành và tiến trình cập nhật sẽ hiển thị tại đây...")
    env_card.body_layout.addWidget(win.upd_notes_box)

    latest_holder: dict[str, UpdateInfo | None] = {"info": None}

    def apply_update_check_result(info: UpdateInfo) -> None:
        latest_holder["info"] = info
        win.upd_notes_box.setPlainText(
            f"Phiên bản hiện tại: v{info.current_version}\n"
            f"Phiên bản mới nhất: v{info.latest_version}\n"
            f"Nguồn: {info.source}\n\n"
            f"Ghi chú phát hành:\n{info.release_notes}"
        )
        win.upd_notes_box.moveCursor(QTextCursor.MoveOperation.Start)
        if info.has_update:
            win.upd_status_lbl.setText(
                f"Có phiên bản mới v{info.latest_version}! Bấm 'Tải & Cập nhật ngay' để nâng cấp."
            )
            btn_install.setEnabled(bool(info.download_url or info.html_url))
            if hasattr(win, "sidebar"):
                win.sidebar.set_update_badge(info.latest_version)
            if hasattr(win, "settings_sub_segment"):
                win.settings_sub_segment.setItemBadgeDot(
                    1, True, f"Có bản cập nhật mới v{info.latest_version}!"
                )
        else:
            win.upd_status_lbl.setText(
                f"Bạn đang sử dụng phiên bản mới nhất (v{info.current_version})."
            )
            btn_install.setEnabled(False)
            if hasattr(win, "sidebar"):
                win.sidebar.set_update_badge("")
            if hasattr(win, "settings_sub_segment"):
                win.settings_sub_segment.setItemBadgeDot(1, False)

    win.apply_update_check_result = apply_update_check_result

    def do_check() -> None:
        btn_check.setEnabled(False)
        win.upd_status_lbl.setText("Đang kết nối máy chủ kiểm tra phiên bản mới...")
        w = UpdateCheckWorker("")

        def on_checked(info: UpdateInfo) -> None:
            btn_check.setEnabled(True)
            apply_update_check_result(info)

        def on_failed(err: str) -> None:
            btn_check.setEnabled(True)
            win.upd_status_lbl.setText(f"Không kiểm tra được phiên bản từ xa: {err}")

        w.signals.checked.connect(on_checked)
        w.signals.failed.connect(on_failed)
        win.analyze_pool.start(w)

    def do_install() -> None:
        info = latest_holder["info"]
        if not info:
            return
        if not info.download_url and info.html_url:
            QDesktopServices.openUrl(QUrl(info.html_url))
            return
        btn_install.setEnabled(False)
        btn_check.setEnabled(False)
        win.upd_pbar.setVisible(True)
        win.upd_pbar.setValue(5)
        dl_worker = UpdateDownloadWorker(info)

        def on_prog(pct: float, msg: str) -> None:
            pct_int = round(pct)
            win.upd_pbar.setValue(pct_int)
            win.upd_status_lbl.setText(f"{msg} ({pct_int}%)" if "%" not in msg else msg)

        def on_staged(script_path: str) -> None:
            win.upd_pbar.setValue(100)
            win.upd_status_lbl.setText("Đã sẵn sàng áp dụng bản cập nhật! Ứng dụng sẽ tự khởi động lại.")
            ans = QMessageBox.question(
                win,
                "Khởi động lại để hoàn tất cập nhật",
                f"Gói cập nhật v{info.latest_version} đã tải xong.\n"
                "Đóng ứng dụng và tự động nâng cấp ngay bây giờ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ans == QMessageBox.StandardButton.Yes:
                if hasattr(win, "trigger_update_and_close"):
                    win.trigger_update_and_close(Path(script_path))
                else:
                    launch_staged_updater(Path(script_path))
                    win.close()

        def on_err(err: str) -> None:
            btn_install.setEnabled(True)
            btn_check.setEnabled(True)
            win.upd_status_lbl.setText(f"Lỗi tải cập nhật: {err}")

        dl_worker.signals.progress.connect(on_prog)
        dl_worker.signals.staged.connect(on_staged)
        dl_worker.signals.failed.connect(on_err)
        win.analyze_pool.start(dl_worker)

    def do_ytdlp_update() -> None:
        btn_ytdlp.setEnabled(False)
        win.upd_status_lbl.setText("Đang tải và cập nhật lõi yt-dlp mới nhất...")
        yw = YtDlpUpdateWorker()

        def on_done(ok: bool, msg: str) -> None:
            btn_ytdlp.setEnabled(True)
            win.upd_status_lbl.setText(msg)
            win.upd_notes_box.appendPlainText(msg)
            refresh_env_panel()

        yw.signals.ytdlp_done.connect(on_done)
        win.analyze_pool.start(yw)

    btn_check.clicked.connect(do_check)
    btn_install.clicked.connect(do_install)
    btn_ytdlp.clicked.connect(do_ytdlp_update)

    v_update.addWidget(env_card)
    v_update.addStretch(1)

    # ==================================================================
    # 6. GIỚI THIỆU PHẦN MỀM
    # ==================================================================
    about_card = SectionCard("Giới thiệu")
    about_title = QLabel(f"YouTube Desktop Downloader v{APP_VERSION}")
    about_title.setObjectName("cardTitle")
    about_card.body_layout.addWidget(about_title)

    about_desc = QLabel(
        "Ứng dụng tải xuống và chuẩn hóa Codec video/âm thanh YouTube tốc độ cao cho Windows. "
        "Hỗ trợ tự động chuyển đổi H.264 / H.265 / AV1 / VP9 tăng tốc phần cứng GPU (NVENC, QuickSync, AMF), "
        "cắt đoạn media, nhúng phụ đề & metadata, đóng gói Portable 1 file .exe duy nhất."
    )
    about_desc.setObjectName("mutedLabel")
    about_desc.setWordWrap(True)
    about_card.body_layout.addWidget(about_desc)

    credits_lbl = QLabel("Thiết kế giao diện sử dụng bộ phông chữ Inter (SIL OFL) và biểu tượng Lucide (MIT License).")
    credits_lbl.setObjectName("mutedLabel")
    about_card.body_layout.addWidget(credits_lbl)

    about_btns = QHBoxLayout()
    about_btns.addWidget(
        tool_button(
            "Mở trang GitHub dự án",
            lambda: QDesktopServices.openUrl(QUrl(f"https://github.com/{DEFAULT_GITHUB_REPO}")),
            f"https://github.com/{DEFAULT_GITHUB_REPO}",
            "secondaryAccentButton",
            icon_name="external-link",
            icon_size=14,
        )
    )
    about_btns.addWidget(
        tool_button(
            "Mở thư mục tải xuống",
            win.open_download_folder,
            icon_name="folder-open",
            icon_size=14,
        )
    )
    about_btns.addWidget(
        tool_button(
            "Mở thư mục dữ liệu",
            win.open_app_data_folder,
            icon_name="folder",
            icon_size=14,
        )
    )
    about_btns.addStretch(1)
    about_card.body_layout.addLayout(about_btns)

    v_about.addWidget(about_card)
    v_about.addStretch(1)

    # Wrap contents into scroll areas
    tab_general_scroll.setWidget(general_content)
    tab_update_scroll.setWidget(update_content)
    tab_about_scroll.setWidget(about_content)

    win.settings_stack.addWidget(tab_general_scroll)
    win.settings_stack.addWidget(tab_update_scroll)
    win.settings_stack.addWidget(tab_about_scroll)

    outer_v.addWidget(win.settings_stack, 1)
    return outer_page
