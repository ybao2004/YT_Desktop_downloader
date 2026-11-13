"""Main application window coordinating sidebar navigation, pages, workers, and queue execution."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import hashlib
from pathlib import Path
from uuid import uuid4

from PyQt6.QtCore import QByteArray, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl
from PyQt6.QtGui import QCloseEvent, QDesktopServices, QKeyEvent, QPixmap
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTableWidgetItem,
    QTextEdit,
    QWidget,
)

from . import icons
from .app import load_bundled_fonts
from .pages import (
    CookieVerifyDialog,
    MultiLinkDialog,
    build_downloads_page,
    build_guide_page,
    build_hardware_page,
    build_log_page,
    build_settings_page,
)
from .widgets import STATUS_TEXT, JobRow, Sidebar, tool_button
from .win_effects import apply_title_bar_theme
from ..engine import (
    CODEC_LABELS,
    environment_report,
    extract_youtube_urls,
    extract_youtube_video_id,
    is_youtube_url,
    parse_timestamp_seconds,
    send_to_trash,
)
from ..hw_monitor import HardwareMonitor, HardwareProfile, format_rate
from ..models import Job, Settings, timestamp
from ..storage import Storage
from ..theme import build_palette, build_stylesheet, theme_manager, tokens_for
from ..updater import UpdateInfo
from ..version import APP_VERSION, app_data_dir, default_download_dir, is_frozen
from ..workers import (
    AnalyzeWorker,
    DownloadControl,
    DownloadWorker,
    HardwareProfileWorker,
    RuntimeBootstrapWorker,
    TranscodeWorker,
    UpdateCheckWorker,
)

JobCardWidget = JobRow


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        load_bundled_fonts()
        from .splash import get_app_icon
        icon = get_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)

        # Resolve Storage through package namespace first so patch("ytd_app.ui.Storage") works
        from .. import ui as _ui_pkg

        storage_cls = getattr(_ui_pkg, "Storage", Storage)
        self.storage = storage_cls()
        self.settings = self.storage.load_settings()
        self.jobs: list[Job] = self.storage.load_jobs()[-500:]
        self.jobs_by_id: dict[str, Job] = {j.job_id: j for j in self.jobs}
        self.rows: dict[str, int] = {}
        self.job_cards: dict[str, JobRow] = {}
        self.thumb_cache: dict[str, QPixmap] = {}
        self.playlist_checkboxes: list[tuple[QCheckBox, dict]] = []
        self.active: dict[str, tuple[DownloadWorker | TranscodeWorker, DownloadControl]] = {}
        self.tab_undo_stacks: dict[str, list[list[tuple[int, Job]]]] = {
            k: [] for k in ("recent", "all", "queued", "active", "done", "error")
        }
        self.tab_redo_stacks: dict[str, list[list[tuple[int, Job]]]] = {
            k: [] for k in ("recent", "all", "queued", "active", "done", "error")
        }
        self.selected_job_ids: set[str] = set()
        self.last_selected_job_id: str | None = None
        self.session_job_ids: set[str] = set()
        self.auto_capture_enabled: bool = False
        self._last_captured_clipboard: str = ""

        self.analyze_pool = QThreadPool(self)
        self.analyze_pool.setMaxThreadCount(3)
        self.analyze_pool.setExpiryTimeout(1500)
        self.download_pool = QThreadPool(self)
        self.download_pool.setMaxThreadCount(5)
        self.download_pool.setExpiryTimeout(1500)

        self.analyze_key = ""
        self.analyze_url = ""
        self.analyze_playlist = False
        self.analyzer: AnalyzeWorker | None = None
        self.preview: dict | None = None
        self.preview_url = ""
        self.preview_playlist = False
        self.pending_add = False
        self.queue_running = False
        self.closing_after_cancel = False
        self.current_filter = "recent"

        self.hw_monitor = HardwareMonitor()
        self.hw_profile: HardwareProfile | None = None

        self.network = QNetworkAccessManager(self)
        self.thumbnail_reply = None
        self.pending_thumbnail = ""
        self.active_thumbnail_replies: set[QNetworkReply] = set()
        self._inflight_thumbnail_urls: set[str] = set()
        self._thumbnail_cache_dir: Path = app_data_dir() / "thumbnails"
        try:
            self._thumbnail_cache_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(900)
        self.save_timer.timeout.connect(self.save_all)

        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.setInterval(1500)
        self.telemetry_timer.timeout.connect(self.refresh_hardware_telemetry)

        self.setWindowTitle(f"YouTube Desktop Downloader v{APP_VERSION}")
        self.resize(1240, 800)
        self.setMinimumSize(980, 620)

        self.setup_tray_icon()
        self.make_ui()
        QApplication.clipboard().dataChanged.connect(self._on_clipboard_data_changed)

        if self.settings.last_geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(self.settings.last_geometry.encode("ascii")))
                if self.width() < 980:
                    self.resize(1240, max(self.height(), 760))
            except (ValueError, TypeError):
                pass

        for job in self.jobs:
            self.insert_job_row(job, batch_init=True)

        self.refresh_stats()

        # Defer non-critical environment inspection & hardware telemetry to background
        QTimer.singleShot(150, self._post_startup_background_tasks)

        self.statusBar().showMessage(
            f"Sẵn sàng · Mặc định Codec {CODEC_LABELS.get(self.settings.default_video_codec, 'H.264')}"
        )

    def _post_startup_background_tasks(self) -> None:
        """Run background checks and warm up yt-dlp after UI is responsive."""
        try:
            self.check_environment(show_dialog=False)
        except Exception:
            pass
        try:
            self.start_hardware_monitoring()
        except Exception:
            pass
        if getattr(self.settings, "auto_check_updates", True):
            QTimer.singleShot(2400, lambda: self.check_remote_update_silent())

        # Background warm-up of yt-dlp module on thread pool
        from ..engine import _get_yt_dlp

        class _WarmupWorker(QRunnable):
            def run(self):
                try:
                    _get_yt_dlp()
                except Exception:
                    pass

        self.analyze_pool.start(_WarmupWorker())

    def setup_tray_icon(self) -> None:
        self.tray_icon: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            tray = QSystemTrayIcon(self)
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
            tray.setIcon(icon)
            tray.setToolTip(f"YouTube Desktop Downloader v{APP_VERSION}")
            self.tray_icon = tray

    def make_ui(self) -> None:
        tm = theme_manager()
        resolved_mode = tm.apply(self.settings.theme_mode)
        self.setStyleSheet(build_stylesheet(tokens_for(resolved_mode)))
        apply_title_bar_theme(self, resolved_mode == "dark")
        tm.changed.connect(self._on_theme_mode_changed)

        root = QWidget()
        root.setObjectName("rootContainer")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Left Navigation Sidebar
        self.sidebar = Sidebar(root)
        self.sidebar.page_requested.connect(self.switch_workspace_tab)
        self.settings_btn = self.sidebar.settings_btn
        outer.addWidget(self.sidebar)

        # Right Workspace Stack:
        # 0 = Downloads, 1 = Log, 2 = Hardware, 3 = Guide, 4 = Settings
        self.workspace_stack = QStackedWidget(root)
        outer.addWidget(self.workspace_stack, 1)

        # Build Settings page first so folder_edit / quick_download_check / concurrent_spin exist,
        # then insert pages in exact stack order 0..4
        page_settings = build_settings_page(self)
        page_downloads = build_downloads_page(self)
        page_log = build_log_page(self)
        page_hardware = build_hardware_page(self)
        page_guide = build_guide_page(self)

        self.page_downloads = page_downloads
        self.workspace_stack.addWidget(page_downloads)  # 0
        self.workspace_stack.addWidget(page_log)        # 1
        self.workspace_stack.addWidget(page_hardware)   # 2
        self.workspace_stack.addWidget(page_guide)      # 3
        self.workspace_stack.addWidget(page_settings)   # 4

        # Status Bar: Left-aligned storage folder chip + transient status text,
        # Right-aligned queue summary + subtle telemetry text items
        self.stats_label = QLabel("")
        self.stats_label.setObjectName("statBarItem")

        self.pill_cpu = QLabel("CPU --%")
        self.pill_cpu.setObjectName("statBarItem")
        self.pill_cpu.setToolTip("Mức sử dụng vi xử lý (CPU)")

        self.pill_gpu = QLabel("GPU Sẵn sàng")
        self.pill_gpu.setObjectName("statBarItem")
        self.pill_gpu.setToolTip("Mức sử dụng GPU / Bộ mã hóa phần cứng")

        self.pill_ram = QLabel("RAM --%")
        self.pill_ram.setObjectName("statBarItem")
        self.pill_ram.setToolTip("Mức sử dụng bộ nhớ RAM")

        self.pill_disk = QLabel("Trống -- GB")
        self.pill_disk.setObjectName("statBarItem")
        self.pill_disk.setToolTip("Dung lượng trống tại ổ đĩa lưu tải xuống")

        self.pill_net = QLabel("↓ 0 KB/s")
        self.pill_net.setObjectName("statBarItem")
        self.pill_net.setToolTip("Băng thông tải xuống mạng toàn hệ thống")

        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        sb.addWidget(self.folder_chip)
        self.status_msg_label = QLabel("")
        self.status_msg_label.setObjectName("statBarItem")
        sb.addWidget(self.status_msg_label, 1)
        self._status_msg_timer = QTimer(self)
        self._status_msg_timer.setSingleShot(True)
        self._status_msg_timer.timeout.connect(lambda: self.status_msg_label.setText(""))
        sb.showMessage = self._show_status_bar_message

        sb.addPermanentWidget(self.stats_label)
        for pill in (self.pill_cpu, self.pill_gpu, self.pill_ram, self.pill_disk, self.pill_net):
            sb.addPermanentWidget(pill)

        # Hidden compatibility references
        self.env_pill_btn = tool_button("FFmpeg & Deno", lambda: self.check_environment(True))
        self.env_pill_btn.setParent(root)
        self.env_pill_btn.setVisible(False)
        self.update_btn = tool_button("Cập nhật", self.open_updater_dialog)
        self.update_btn.setParent(root)
        self.update_btn.setVisible(False)
        self._update_undo_redo_buttons()

    @property
    def deleted_jobs_stack(self) -> list[list[tuple[int, Job]]]:
        current = getattr(self, "current_filter", "recent")
        return self.tab_undo_stacks.setdefault(current, [])

    @deleted_jobs_stack.setter
    def deleted_jobs_stack(self, val: list[list[tuple[int, Job]]]) -> None:
        current = getattr(self, "current_filter", "recent")
        self.tab_undo_stacks[current] = val

    def _show_status_bar_message(self, message: str, timeout: int = 0) -> None:
        if hasattr(self, "status_msg_label"):
            self.status_msg_label.setText(str(message or ""))
            if timeout and timeout > 0:
                self._status_msg_timer.start(int(timeout))
            else:
                self._status_msg_timer.stop()

    def _on_theme_mode_changed(self, resolved_mode: str) -> None:
        t = tokens_for(resolved_mode)
        self.setPalette(build_palette(t))
        self.setStyleSheet(build_stylesheet(t))
        apply_title_bar_theme(self, resolved_mode == "dark")
        self._update_queue_toggle_icon()

    # ------------------------------------------------------------------
    # Hardware Monitoring
    # ------------------------------------------------------------------
    def start_hardware_monitoring(self) -> None:
        worker = HardwareProfileWorker()
        worker.signals.ready.connect(self.on_hardware_profile_ready)
        self.analyze_pool.start(worker)
        self.refresh_hardware_telemetry()
        self.telemetry_timer.start()

    def on_hardware_profile_ready(self, profile: HardwareProfile) -> None:
        self.hw_profile = profile
        self.hw_cpu_name_label.setText(
            f"CPU: {profile.cpu_name} ({profile.cpu_cores} nhân / {profile.cpu_threads} luồng)"
        )
        gpu_str = ", ".join(profile.gpu_names)
        self.hw_gpu_name_label.setText(f"GPU: {gpu_str}")
        self.hw_os_ram_label.setText(
            f"Hệ thống: {profile.os_name}  ·  Tổng RAM: {profile.ram_total_gb:.1f} GB"
        )

        enc_parts = []
        for codec, encs in profile.working_encoders.items():
            if encs:
                enc_parts.append(f"{codec.upper()}: {', '.join(encs)}")
        enc_summary = "  |  ".join(enc_parts) if enc_parts else "Chưa phát hiện FFmpeg"
        self.hw_encoders_label.setText(f"Bộ mã hóa khả dụng: {enc_summary}")

        has_gpu_enc = any(
            any(k in e for k in ("nvenc", "qsv", "amf"))
            for encs in profile.working_encoders.values()
            for e in encs
        )
        if "Sẵn sàng" in self.pill_gpu.text():
            self.pill_gpu.setText("GPU NVENC/QSV" if has_gpu_enc else "GPU CPU Mode")

    def refresh_hardware_telemetry(self) -> None:
        dl_dir = self.folder_edit.text().strip() if hasattr(self, "folder_edit") else self.settings.download_dir
        m = self.hw_monitor.sample_metrics(dl_dir)

        self.pill_cpu.setText(f"CPU {m.cpu_percent:.0f}%")
        if m.gpu_percent is not None:
            self.pill_gpu.setText(f"GPU {m.gpu_percent:.0f}%")
        self.pill_ram.setText(f"RAM {m.ram_percent:.0f}%")
        self.pill_disk.setText(f"Trống {m.disk_free_gb:.1f} GB")
        self.pill_net.setText(f"↓ {format_rate(m.net_down_bps)}")

        if hasattr(self, "metric_cpu"):
            self.metric_cpu.set_metric(
                f"{m.cpu_percent:.0f}%",
                f"{m.cpu_percent:.1f}% đang sử dụng",
                m.cpu_percent,
            )
            if m.gpu_percent is not None:
                mem_txt = f" · VRAM {m.gpu_mem_percent:.0f}%" if m.gpu_mem_percent is not None else ""
                self.metric_gpu.set_metric(
                    f"{m.gpu_percent:.0f}%",
                    f"{m.gpu_percent:.1f}%{mem_txt}",
                    m.gpu_percent,
                )
            else:
                self.metric_gpu.set_metric(
                    "Sẵn sàng",
                    "Tăng tốc phần cứng FFmpeg",
                    0.0,
                )
            self.metric_ram.set_metric(
                f"{m.ram_percent:.0f}%",
                f"{m.ram_used_gb:.1f} / {m.ram_total_gb:.1f} GB",
                m.ram_percent,
            )
            self.metric_disk.set_metric(
                f"{m.disk_free_gb:.1f} GB",
                f"Trống {m.disk_free_gb:.1f} / {m.disk_total_gb:.1f} GB ({m.disk_percent:.0f}% đã dùng)",
                m.disk_percent,
            )
            # Normalize network rate against 25 MB/s ceiling for sparkline visualization
            net_pct = min(100.0, (m.net_down_bps / (25.0 * 1024.0 * 1024.0)) * 100.0)
            self.metric_net.set_metric(
                f"↓ {format_rate(m.net_down_bps)}",
                f"↓ Tải xuống: {format_rate(m.net_down_bps)}   ·   ↑ Tải lên: {format_rate(m.net_up_bps)}",
                net_pct,
            )

    # ------------------------------------------------------------------
    # Logging & Option Toggles
    # ------------------------------------------------------------------
    def log(self, msg: str) -> None:
        if hasattr(self, "log_box"):
            ts = datetime.now().strftime("%H:%M:%S")
            text = str(msg)
            lines = text.splitlines()
            if not lines:
                self.log_box.appendPlainText(f"[{ts}]")
            else:
                for line in lines:
                    self.log_box.appendPlainText(f"[{ts}] {line}")

    def intercept_main_url_paste(self) -> bool:
        text = QApplication.clipboard().text().strip()
        if not text:
            return False
        urls, _dups, _inv = extract_youtube_urls(text)
        if urls:
            self.paste_from_clipboard()
            return True
        return False

    def intercept_batch_url_paste(self) -> bool:
        text = QApplication.clipboard().text().strip()
        if not text:
            return False
        urls, _dups, _inv = extract_youtube_urls(text)
        if urls:
            self.paste_to_batch_queue()
            return True
        return False

    def paste_from_clipboard(self) -> None:
        text = QApplication.clipboard().text().strip()
        if not text:
            self.statusBar().showMessage("Clipboard hiện đang trống.", 4000)
            return

        urls, _dups, _inv = extract_youtube_urls(text)
        if urls:
            playlist_enabled = hasattr(self, "playlist_check") and self.playlist_check.isChecked()
            is_single_playlist = len(urls) == 1 and (playlist_enabled or "list=" in urls[0].lower())
            if is_single_playlist and not getattr(self.settings, "quick_download", False):
                self.url_edit.setText(urls[0])
                self.start_analysis(add_after=True, auto_start=False)
                self.url_edit.clear()
            else:
                self.enqueue_batch_urls(text, source_label="Dán vào Hàng đợi", auto_start=False)
                self.url_edit.clear()
        else:
            first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
            self.url_edit.setText(first_line)
            self.link_status.setText("Nội dung vừa dán chưa phải URL YouTube")

    def paste_to_batch_queue(self) -> None:
        self.paste_from_clipboard()

    def on_auto_capture_toggled(self, checked: bool) -> None:
        self.auto_capture_enabled = bool(checked)
        if hasattr(self, "auto_capture_btn"):
            self.auto_capture_btn.blockSignals(True)
            self.auto_capture_btn.setChecked(self.auto_capture_enabled)
            self.auto_capture_btn.setText("Tự bắt link: Bật" if self.auto_capture_enabled else "Tự bắt link: Tắt")
            self.auto_capture_btn.blockSignals(False)
        if self.auto_capture_enabled:
            self._last_captured_clipboard = QApplication.clipboard().text().strip()
            self.link_status.setText("Đang bật Tự bắt link — Copy (Ctrl+C) liên kết YouTube để tự thêm vào Hàng đợi")
            self.statusBar().showMessage("Đã bật chế độ Tự bắt link từ Clipboard.", 4000)
        else:
            self.link_status.setText("Sẵn sàng")
            self.statusBar().showMessage("Đã tắt chế độ Tự bắt link từ Clipboard.", 4000)

    def _on_clipboard_data_changed(self) -> None:
        if not self.auto_capture_enabled:
            return
        text = QApplication.clipboard().text().strip()
        if not text or text == self._last_captured_clipboard:
            return
        self._last_captured_clipboard = text
        urls, _dups, _inv = extract_youtube_urls(text)
        if urls:
            self.enqueue_batch_urls(text, source_label="Tự bắt link", auto_start=False)

    def open_multiline_dialog(self, initial_text: str = "") -> None:
        if isinstance(initial_text, bool):
            initial_text = ""
        if not initial_text and hasattr(self, "url_edit"):
            initial_text = self.url_edit.text().strip()
        dlg = MultiLinkDialog(self, initial_text=initial_text)
        if dlg.exec() == MultiLinkDialog.DialogCode.Accepted:
            raw = dlg.raw_text()
            if raw.strip():
                self.enqueue_batch_urls(raw, source_label="Nhập nhiều dòng", auto_start=False)
                self.url_edit.clear()

    def open_multi_link_dialog(self, initial_text: str = "") -> None:
        self.open_multiline_dialog(initial_text=initial_text)

    def on_url_enter_pressed(self) -> None:
        self.on_primary_download_clicked()

    def on_playlist_toggle(self) -> None:
        checked = self.playlist_check.isChecked()
        self.settings.last_playlist = checked
        if hasattr(self, "playlist_chip"):
            self.playlist_chip.blockSignals(True)
            self.playlist_chip.setChecked(checked)
            self.playlist_chip.setVisible(checked)
            self.playlist_chip.blockSignals(False)
        self.mark_preview_stale()
        self.schedule_save()

    def on_quick_download_toggle(self) -> None:
        self.settings.quick_download = self.quick_download_check.isChecked()
        self.schedule_save()

    def on_id_suffix_toggled(self, checked: bool) -> None:
        self.settings.append_id_suffix = bool(checked)
        self.schedule_save()

    def on_codec_changed(self) -> None:
        self.settings.default_video_codec = self.codec_combo.currentData() or "h264"
        self.sync_batch_format_controls()
        self.schedule_save()

    def on_mute_toggled(self, checked: bool) -> None:
        if hasattr(self, "mute_btn"):
            from .widgets.common import _apply_button_icon
            if checked:
                self.mute_btn.setObjectName("muteActiveButton")
                self.mute_btn.setText("Đang tắt tiếng")
                self.mute_btn.setProperty("lucideIcon", "volume-x")
                self.mute_btn.setProperty("lucideDanger", True)
                self.mute_btn.setToolTip("Đang tắt tiếng: Lưu video không âm thanh (Bấm để bật lại âm thanh)")
                self.statusBar().showMessage("Đã bật chế độ Tắt tiếng: Video mới sẽ được lưu không có âm thanh.", 4000)
            else:
                self.mute_btn.setObjectName("ghostButton")
                self.mute_btn.setText("Âm thanh: Bật")
                self.mute_btn.setProperty("lucideIcon", "volume-2")
                self.mute_btn.setProperty("lucideDanger", False)
                self.mute_btn.setToolTip("Đang bật âm thanh (Bấm để chuyển sang chế độ Tắt tiếng / Video-only)")
                self.statusBar().showMessage("Đã tắt chế độ Tắt tiếng: Video mới sẽ có đầy đủ âm thanh.", 3000)
            self.mute_btn.style().unpolish(self.mute_btn)
            self.mute_btn.style().polish(self.mute_btn)
            _apply_button_icon(self.mute_btn)

    def on_audio_bitrate_changed(self) -> None:
        self.settings.default_audio_bitrate = self.audio_bitrate_combo.currentData() or "192"
        self.sync_batch_format_controls()
        self.schedule_save()

    def on_more_options_toggled(self, checked: bool) -> None:
        self.extra_options_frame.setVisible(checked)
        self.more_options_btn.setText("Tùy chọn ▴" if checked else "Tùy chọn ▾")

    def on_batch_more_options_toggled(self, checked: bool) -> None:
        if hasattr(self, "batch_extra_options_frame"):
            self.batch_extra_options_frame.setVisible(checked)
            self.batch_more_options_btn.setText("Tùy chọn ▴" if checked else "Tùy chọn ▾")

    def on_subtitles_toggled(self) -> None:
        self.settings.download_subtitles = self.subtitles_check.isChecked()
        self.settings.subtitle_langs = self.sub_langs_edit.text().strip() or "vi,en"
        self.schedule_save()

    def on_embed_meta_toggled(self) -> None:
        self.settings.embed_metadata = self.embed_meta_check.isChecked()
        self.schedule_save()

    def on_exact_format_toggled(self, checked: bool) -> None:
        self.formats_table.setVisible(checked)

    def mode_changed(self) -> None:
        mode = self.mode_combo.currentData()
        self.settings.default_mode = mode
        previous = self.ext_combo.blockSignals(True)
        self.ext_combo.clear()
        if mode == "video":
            for ext in ("mp4", "mkv", "webm"):
                self.ext_combo.addItem(ext.upper(), ext)
            stored_ext = self.settings.default_video_ext
        else:
            for ext in ("mp3", "m4a", "flac", "original"):
                self.ext_combo.addItem(ext.upper() if ext != "original" else "Gốc (Original)", ext)
            stored_ext = self.settings.default_audio_ext
        idx = self.ext_combo.findData(stored_ext)
        self.ext_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.ext_combo.blockSignals(previous)

        is_video = mode == "video"
        self.quality_label.setText("Chất lượng:" if is_video else "Bitrate:")
        self.quality_combo.setVisible(is_video)
        self.audio_bitrate_combo.setVisible(not is_video)
        self.codec_combo.setVisible(is_video)
        if hasattr(self, "mute_btn"):
            self.mute_btn.setVisible(is_video)
        self.sync_batch_format_controls()
        self.schedule_save()

    def on_ext_changed(self) -> None:
        if self.mode_combo.currentData() == "video":
            self.settings.default_video_ext = self.ext_combo.currentData()
        else:
            self.settings.default_audio_ext = self.ext_combo.currentData()
        self.sync_batch_format_controls()
        self.schedule_save()

    def sync_batch_format_controls(self) -> None:
        if not hasattr(self, "batch_mode_combo"):
            return
        mode = self.mode_combo.currentData()
        is_video = mode == "video"

        self.batch_mode_combo.blockSignals(True)
        self.batch_mode_combo.setCurrentIndex(self.mode_combo.currentIndex())
        self.batch_mode_combo.blockSignals(False)

        self.batch_ext_combo.blockSignals(True)
        self.batch_ext_combo.clear()
        for i in range(self.ext_combo.count()):
            self.batch_ext_combo.addItem(self.ext_combo.itemText(i), self.ext_combo.itemData(i))
        self.batch_ext_combo.setCurrentIndex(self.ext_combo.currentIndex())
        self.batch_ext_combo.blockSignals(False)

        self.batch_quality_combo.blockSignals(True)
        self.batch_quality_combo.setCurrentIndex(self.quality_combo.currentIndex())
        self.batch_quality_combo.setVisible(is_video)
        self.batch_quality_combo.blockSignals(False)

        self.batch_audio_bitrate_combo.blockSignals(True)
        self.batch_audio_bitrate_combo.setCurrentIndex(self.audio_bitrate_combo.currentIndex())
        self.batch_audio_bitrate_combo.setVisible(not is_video)
        self.batch_audio_bitrate_combo.blockSignals(False)

        self.batch_codec_combo.blockSignals(True)
        self.batch_codec_combo.setCurrentIndex(self.codec_combo.currentIndex())
        self.batch_codec_combo.setVisible(is_video)
        self.batch_codec_combo.blockSignals(False)

        if hasattr(self, "batch_folder_chip") and hasattr(self, "folder_edit"):
            self.batch_folder_chip.set_path(self.folder_edit.text().strip())

    def on_batch_mode_changed(self) -> None:
        self.mode_combo.setCurrentIndex(self.batch_mode_combo.currentIndex())

    def on_batch_ext_changed(self) -> None:
        self.ext_combo.setCurrentIndex(self.batch_ext_combo.currentIndex())

    def on_batch_quality_changed(self) -> None:
        self.quality_combo.setCurrentIndex(self.batch_quality_combo.currentIndex())

    def on_batch_audio_bitrate_changed(self) -> None:
        self.audio_bitrate_combo.setCurrentIndex(self.batch_audio_bitrate_combo.currentIndex())

    def on_batch_codec_changed(self) -> None:
        self.codec_combo.setCurrentIndex(self.batch_codec_combo.currentIndex())

    def mark_preview_stale(self) -> None:
        if hasattr(self, "exact_format_check"):
            self.exact_format_check.setChecked(False)
        url = self.url_edit.text().strip()
        if not url:
            self.link_status.setText("Sẵn sàng")
        elif is_youtube_url(url):
            if "list=" in url.lower() and not self.playlist_check.isChecked():
                self.link_status.setText("URL có Playlist · Bật 'Tải cả Playlist' trong Tùy chọn nếu muốn tải trọn bộ")
            else:
                self.link_status.setText("URL hợp lệ · Sẵn sàng tải")
        else:
            self.link_status.setText("URL chưa hợp lệ")

    # ------------------------------------------------------------------
    # URL Analysis & Preview
    # ------------------------------------------------------------------
    def start_analysis(self, *args, add_after: bool = False, auto_start: bool = True) -> None:
        url = self.url_edit.text().strip()
        if not is_youtube_url(url):
            QMessageBox.warning(self, "URL không hợp lệ", "Vui lòng dán liên kết YouTube hợp lệ.")
            return
        self.pending_add = add_after
        self._pending_auto_start = auto_start
        self.analyze_key = uuid4().hex
        self.analyze_url = url
        self.analyze_playlist = self.playlist_check.isChecked()
        self.analyze_btn.setEnabled(False)
        self.add_btn.setEnabled(False)
        self.link_status.setText("Đang phân tích liên kết...")
        self.statusBar().showMessage("Đang lấy thông tin từ YouTube...")
        worker = AnalyzeWorker(
            self.analyze_key,
            url,
            self.playlist_check.isChecked(),
            cookie_file=self.settings.cookie_file,
            cookies_from_browser=getattr(self.settings, "cookies_from_browser", "auto"),
        )
        worker.signals.ready.connect(self.analysis_ready)
        worker.signals.failed.connect(self.analysis_failed)
        self.analyzer = worker
        self.analyze_pool.start(worker)

    def analysis_ready(self, key: str, result: dict) -> None:
        if key != self.analyze_key:
            return
        self.analyze_btn.setEnabled(True)
        self.add_btn.setEnabled(True)
        self.analyzer = None
        if self.url_edit.text().strip() != self.analyze_url or self.playlist_check.isChecked() != self.analyze_playlist:
            self.pending_add = False
            self.link_status.setText("URL đã thay đổi, hãy phân tích lại")
            return

        self.preview = result
        self.preview_url = self.url_edit.text().strip()
        self.preview_playlist = self.playlist_check.isChecked()
        self.formats_table.setRowCount(0)
        self.preview_image.setPixmap(QPixmap())
        self.preview_image.setText("Đang tải ảnh...")
        self.pending_thumbnail = ""
        self.clear_playlist_checkboxes()

        if result["type"] == "playlist":
            entries = result["entries"]
            self.preview_stack.setCurrentIndex(1)
            self.preview_badge_title.setText("DANH SÁCH VIDEO TRONG PLAYLIST")
            self.playlist_title_label.setText(str(result["title"]))
            self.video_count_label.setText(f"{len(entries)} video")
            self.link_status.setText(f"Đã phân tích Playlist ({len(entries)} mục)")
            self.preview_title.setText(result["title"])

            for idx, entry in enumerate(entries, start=1):
                safe_title = str(entry["title"]).replace("&", "&&")
                cb = QCheckBox(f"{idx}. {safe_title}")
                cb.setChecked(True)
                cb.setToolTip(entry["url"])
                cb.toggled.connect(self.update_playlist_selection_count)
                self.playlist_list_layout.addWidget(cb)
                self.playlist_checkboxes.append((cb, entry))
            self.playlist_list_layout.addStretch(1)
            self.update_playlist_selection_count()
        else:
            video = result["video"]
            self.preview_stack.setCurrentIndex(0)
            self.preview_badge_title.setText("THÔNG TIN VIDEO")
            self.preview_title.setText(
                f"{video['title']}\n"
                f"Kênh: {video['channel'] or '—'}   ·   "
                f"Thời lượng: {video['duration']}   ·   ID: {video['id']}"
            )
            self.video_count_label.setText(f"{len(video['formats'])} luồng định dạng")
            self.link_status.setText("Đã phân tích video")
            for fmt in video["formats"]:
                row = self.formats_table.rowCount()
                self.formats_table.insertRow(row)
                values = [fmt[k] for k in ("id", "ext", "resolution", "fps", "video", "audio", "bitrate", "size")]
                for col, value in enumerate(values):
                    it = QTableWidgetItem(str(value))
                    if col == 0:
                        it.setData(Qt.ItemDataRole.UserRole, fmt)
                    self.formats_table.setItem(row, col, it)
            if video["thumbnail"]:
                self.fetch_thumbnail(video["thumbnail"])
            else:
                self.preview_image.setText("Không có ảnh")

        self.preview_card.setVisible(True)
        if self.pending_add:
            auto_start = getattr(self, "_pending_auto_start", True)
            self.pending_add = False
            self.add_from_preview(auto_start=auto_start)

    def clear_playlist_checkboxes(self) -> None:
        self.playlist_checkboxes.clear()
        while self.playlist_list_layout.count():
            item = self.playlist_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def set_all_playlist_items(self, checked: bool) -> None:
        for cb, _ in self.playlist_checkboxes:
            cb.blockSignals(True)
            cb.setChecked(checked)
            cb.blockSignals(False)
        self.update_playlist_selection_count()

    def update_playlist_selection_count(self) -> None:
        selected_count = sum(1 for cb, _ in self.playlist_checkboxes if cb.isChecked())
        total_count = len(self.playlist_checkboxes)
        self.video_count_label.setText(f"Đã chọn {selected_count}/{total_count} video")
        self.playlist_download_btn.setText(f"Tải {selected_count} video đã chọn")
        self.playlist_download_btn.setEnabled(selected_count > 0)

    def analysis_failed(self, key: str, msg: str) -> None:
        if key != self.analyze_key:
            return
        self.analyze_btn.setEnabled(True)
        self.add_btn.setEnabled(True)
        self.analyzer = None
        self.pending_add = False
        self.link_status.setText("Phân tích thất bại")
        self.log(f"Phân tích: {msg}")
        QMessageBox.warning(self, "Không phân tích được", msg[:1100])

    def _get_thumbnail_disk_cache_path(self, url: str) -> Path | None:
        try:
            h = hashlib.sha1((url or "").strip().encode("utf-8")).hexdigest()
            return self._thumbnail_cache_dir / f"{h}.jpg"
        except Exception:
            return None

    def fetch_thumbnail(self, url: str, target_job_id: str = "") -> None:
        url = (url or "").strip()
        if not (url.startswith("https://") or url.startswith("http://")):
            if not target_job_id and hasattr(self, "preview_image"):
                self.preview_image.setText("Không có ảnh")
            return

        # 1. Check in-memory cache
        if url in self.thumb_cache:
            pix = self.thumb_cache[url]
            if not target_job_id and hasattr(self, "preview_image"):
                self.preview_image.setPixmap(
                    pix.scaled(
                        self.preview_image.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            elif target_job_id in self.job_cards:
                self.job_cards[target_job_id].set_thumbnail_pixmap(pix)
            return

        # 2. Check disk cache
        disk_path = self._get_thumbnail_disk_cache_path(url)
        if disk_path and disk_path.is_file():
            try:
                pix = QPixmap(str(disk_path))
                if not pix.isNull():
                    self.thumb_cache[url] = pix
                    if not target_job_id and hasattr(self, "preview_image"):
                        self.preview_image.setPixmap(
                            pix.scaled(
                                self.preview_image.size(),
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        )
                    elif target_job_id in self.job_cards:
                        self.job_cards[target_job_id].set_thumbnail_pixmap(pix)
                    return
            except Exception:
                pass

        # 3. Fetch over network (deduplicate concurrent in-flight requests)
        if url in self._inflight_thumbnail_urls:
            return
        self._inflight_thumbnail_urls.add(url)

        if not target_job_id:
            self.pending_thumbnail = url
        req = QNetworkRequest(QUrl(url))
        req.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        reply = self.network.get(req)
        self.active_thumbnail_replies.add(reply)
        reply.finished.connect(lambda r=reply, u=url, jid=target_job_id: self.thumbnail_finished(r, u, jid))
        self.thumbnail_reply = reply

    def thumbnail_finished(self, reply, url: str, target_job_id: str = "") -> None:
        try:
            self._inflight_thumbnail_urls.discard(url)
            self.active_thumbnail_replies.discard(reply)
            if reply.error() == QNetworkReply.NetworkError.NoError:
                image_data = bytes(reply.readAll())
                if 0 < len(image_data) < 3_500_000:
                    disk_path = self._get_thumbnail_disk_cache_path(url)
                    if disk_path:
                        try:
                            disk_path.write_bytes(image_data)
                        except Exception:
                            pass
                    pixmap = QPixmap()
                    if pixmap.loadFromData(image_data):
                        self.thumb_cache[url] = pixmap
                        if url == self.pending_thumbnail and hasattr(self, "preview_image"):
                            self.preview_image.setPixmap(
                                pixmap.scaled(
                                    self.preview_image.size(),
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation,
                                )
                            )
                        for job in self.jobs:
                            if job.thumbnail_url == url or job.job_id == target_job_id:
                                card = self.job_cards.get(job.job_id)
                                if card:
                                    card.set_thumbnail_pixmap(pixmap)
                        return
            if url == self.pending_thumbnail and not target_job_id and hasattr(self, "preview_image"):
                self.preview_image.setText("Không có ảnh")
        finally:
            reply.deleteLater()

    def selected_format(self):
        if not self.exact_format_check.isChecked():
            return None
        selected = self.formats_table.selectedItems()
        if not selected:
            QMessageBox.warning(
                self,
                "Chưa chọn định dạng",
                "Hãy chọn một dòng trong bảng định dạng hoặc bỏ chọn tùy chọn định dạng nâng cao.",
            )
            return False
        row = selected[0].row()
        return self.formats_table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def _validate_clip_inputs(self) -> tuple[str, str] | None:
        c_start = self.clip_start_edit.text().strip()
        c_end = self.clip_end_edit.text().strip()
        try:
            s_sec = parse_timestamp_seconds(c_start)
            e_sec = parse_timestamp_seconds(c_end)
            if s_sec is not None and e_sec is not None and e_sec <= s_sec:
                QMessageBox.warning(
                    self,
                    "Khoảng cắt không hợp lệ",
                    "Thời điểm kết thúc cắt đoạn phải lớn hơn thời điểm bắt đầu.",
                )
                return None
        except ValueError as exc:
            QMessageBox.warning(self, "Định dạng thời gian sai", str(exc))
            return None
        return c_start, c_end

    # ------------------------------------------------------------------
    # Adding Jobs & Queue Execution
    # ------------------------------------------------------------------
    def on_primary_download_clicked(self) -> None:
        url = self.url_edit.text().strip()
        if url:
            playlist = self.playlist_check.isChecked()
            has_matching_preview = (
                self.preview is not None
                and url == self.preview_url
                and playlist == self.preview_playlist
            )
            if has_matching_preview:
                self.add_from_preview()
                self.url_edit.clear()
                return

            urls, _dups, _inv = extract_youtube_urls(url)
            if not urls:
                QMessageBox.warning(self, "URL không hợp lệ", "Vui lòng dán liên kết YouTube hợp lệ.")
                return

            if len(urls) == 1 and not self.quick_download_check.isChecked() and (playlist or "list=" in url.lower()):
                self.start_analysis(add_after=True)
                return

            self.enqueue_batch_urls(url, source_label="Tải xuống", auto_start=True)
            self.url_edit.clear()
            self.start_queue()
            return

        has_paused = any(j.status == "paused" for j in self.jobs)
        if has_paused:
            self.resume_all_paused()

        has_queued = any(j.status == "queued" for j in self.jobs)
        if not has_queued and not self.active and not has_paused:
            QMessageBox.information(
                self,
                "Hàng đợi trống",
                "Chưa có tác vụ nào đang chờ tải. Hãy dán 1 hoặc nhiều liên kết YouTube vào Hàng đợi trước.",
            )
            return

        self.start_queue()
        queued_cnt = sum(1 for j in self.jobs if j.status in {"queued", "downloading"})
        self.link_status.setText(f"Đang tải xuống hàng đợi ({queued_cnt} mục)...")
        self.statusBar().showMessage(f"Đã bắt đầu tải xuống hàng đợi ({queued_cnt} mục).", 5000)

    def _jobs_collide(self, job_a: Job, job_b: Job) -> bool:
        if Path(job_a.directory).resolve() != Path(job_b.directory).resolve():
            return False
        vid_a = extract_youtube_video_id(job_a.url)
        vid_b = extract_youtube_video_id(job_b.url)
        if vid_a and vid_b:
            return vid_a == vid_b
        return job_a.url.strip() == job_b.url.strip()

    def add_quick_single_job(self, url: str) -> None:
        self.enqueue_batch_urls(url, source_label="Tải nhanh 1-click", auto_start=True)
        self.start_queue()

    def add_from_preview(self, auto_start: bool = True) -> None:
        url = self.url_edit.text().strip()
        playlist = self.playlist_check.isChecked()
        if not self.preview or url != self.preview_url or playlist != self.preview_playlist:
            self.start_analysis(add_after=True, auto_start=auto_start)
            return

        clip_pair = self._validate_clip_inputs()
        if clip_pair is None:
            return
        c_start, c_end = clip_pair

        mode = self.mode_combo.currentData()
        ext = self.ext_combo.currentData()
        v_codec = str(self.codec_combo.currentData() or "h264")
        a_bitrate = str(self.audio_bitrate_combo.currentData() or "192")

        fmt = self.selected_format() if self.preview["type"] == "video" else None
        if fmt is False:
            return
        if fmt and ((mode == "video" and not fmt["has_video"]) or (mode == "audio" and not fmt["has_audio"])):
            QMessageBox.warning(self, "Không phù hợp", "Dòng định dạng đã chọn không chứa loại dữ liệu cần tải.")
            return
        if fmt and mode == "video" and ext in ("mp4", "webm") and fmt["ext"] != ext and v_codec == "auto":
            QMessageBox.warning(
                self,
                "Sai container",
                "Dòng video được chọn có đuôi nguồn khác container đầu ra. "
                "Hãy chọn một dòng cùng đuôi, chọn MKV, hoặc chọn Codec H.264/H.265 để chuyển đổi.",
            )
            return

        directory = self.folder_edit.text().strip()
        if not directory:
            QMessageBox.warning(self, "Chưa chọn thư mục", "Chọn thư mục lưu trước khi thêm tác vụ.")
            return

        if self.preview["type"] == "video":
            entries = [{
                "url": self.preview["video"]["url"] or url,
                "title": self.preview["video"]["title"],
                "thumbnail": self.preview["video"].get("thumbnail") or "",
            }]
        else:
            if self.playlist_checkboxes:
                entries = [entry for cb, entry in self.playlist_checkboxes if cb.isChecked()]
            else:
                entries = self.preview["entries"]
            if not entries:
                QMessageBox.information(self, "Chưa chọn video", "Hãy tích chọn ít nhất 1 video trong playlist để tải.")
                return

        count = 0
        is_muted = mode == "video" and hasattr(self, "mute_btn") and self.mute_btn.isChecked()
        for entry in entries:
            thumb_u = entry.get("thumbnail") or ""
            job = Job(
                url=entry["url"],
                title=str(entry["title"]),
                mode=mode,
                container=ext,
                quality=str(self.quality_combo.currentData()),
                video_codec=v_codec,
                audio_bitrate=a_bitrate,
                directory=directory,
                format_id=(fmt["id"] if fmt else ""),
                format_ext=(fmt["ext"] if fmt else ""),
                format_has_audio=(fmt["has_audio"] if fmt else False),
                clip_start=c_start,
                clip_end=c_end,
                subtitles=self.subtitles_check.isChecked(),
                sub_langs=self.sub_langs_edit.text().strip() or "vi,en",
                embed_metadata=self.embed_meta_check.isChecked(),
                thumbnail_url=thumb_u,
                mute_audio=is_muted,
            )
            self.jobs.append(job)
            self.jobs_by_id[job.job_id] = job
            self.session_job_ids.add(job.job_id)
            self.insert_job_row(job)
            if thumb_u:
                self.fetch_thumbnail(thumb_u, job.job_id)
            count += 1

        self.log(f"Đã thêm {count} mục vào hàng đợi (Codec mục tiêu: {CODEC_LABELS.get(v_codec, v_codec)}).")
        if auto_start:
            self.statusBar().showMessage(f"Đã thêm {count} tác vụ và tự động bắt đầu tải.", 6000)
            self.start_queue()
        else:
            self.statusBar().showMessage(f"Đã thêm {count} tác vụ vào Hàng đợi (Chờ tải).", 6000)
        self.schedule_save()

    def on_queue_btn_clicked(self) -> None:
        text = self.url_edit.text().strip()
        if not text:
            clip_text = QApplication.clipboard().text().strip()
            urls, _dups, _inv = extract_youtube_urls(clip_text)
            if urls:
                self.enqueue_batch_urls(clip_text, source_label="Hàng đợi (Clipboard)", auto_start=False)
                return
            self.open_multiline_dialog()
            return
        urls, _dups, _inv = extract_youtube_urls(text)
        if not urls:
            QMessageBox.warning(
                self,
                "Không tìm thấy liên kết hợp lệ",
                "Nội dung nhập vào không chứa liên kết YouTube hợp lệ nào.",
            )
            return
        self.enqueue_batch_urls(text, source_label="Hàng đợi", auto_start=False)
        self.url_edit.clear()

    def on_batch_queue_clicked(self) -> None:
        self.on_queue_btn_clicked()

    def on_batch_download_clicked(self) -> None:
        self.on_primary_download_clicked()

    def enqueue_batch_urls(
        self,
        raw_text: str | list[str] | tuple[str, ...],
        source_label: str = "Hàng đợi",
        auto_start: bool = False,
    ) -> int:
        if isinstance(raw_text, (list, tuple)):
            raw_text = "\n".join(str(item) for item in raw_text)
        urls, dup_in_input, invalid_cnt = extract_youtube_urls(raw_text)
        if not urls:
            msg = "Không tìm thấy liên kết YouTube hợp lệ."
            if hasattr(self, "batch_link_status"):
                self.batch_link_status.setText(msg)
            self.statusBar().showMessage(msg, 4000)
            return 0

        directory = self.folder_edit.text().strip()
        if not directory:
            QMessageBox.warning(self, "Chưa chọn thư mục", "Chọn thư mục lưu trước khi thêm vào hàng đợi.")
            return 0
        clip_pair = self._validate_clip_inputs()
        if clip_pair is None:
            return 0
        c_start, c_end = clip_pair

        if not auto_start and not self.active:
            self.queue_running = False

        mode = self.mode_combo.currentData()
        ext = self.ext_combo.currentData()
        quality = str(self.quality_combo.currentData())
        v_codec = str(self.codec_combo.currentData() or "h264")
        a_bitrate = str(self.audio_bitrate_combo.currentData() or "192")
        is_muted = mode == "video" and hasattr(self, "mute_btn") and self.mute_btn.isChecked()

        added_count = 0
        dup_in_queue = 0

        for url in urls:
            vid = extract_youtube_video_id(url)
            thumb_u = f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg" if vid else ""
            job = Job(
                url=url,
                title=f"Đang chờ tải · {url}",
                mode=mode,
                container=ext,
                quality=quality,
                video_codec=v_codec,
                audio_bitrate=a_bitrate,
                directory=directory,
                clip_start=c_start,
                clip_end=c_end,
                subtitles=self.subtitles_check.isChecked(),
                sub_langs=self.sub_langs_edit.text().strip() or "vi,en",
                embed_metadata=self.embed_meta_check.isChecked(),
                thumbnail_url=thumb_u,
                mute_audio=is_muted,
            )

            collision = False
            for existing in self.jobs:
                if existing.status in {"queued", "downloading", "processing", "converting", "paused"}:
                    if (
                        self._jobs_collide(existing, job)
                        and existing.mode == job.mode
                        and existing.container == job.container
                        and existing.clip_start == job.clip_start
                        and existing.clip_end == job.clip_end
                        and getattr(existing, "mute_audio", False) == getattr(job, "mute_audio", False)
                    ):
                        collision = True
                        break
            if collision:
                dup_in_queue += 1
                continue

            self.jobs.append(job)
            self.jobs_by_id[job.job_id] = job
            self.session_job_ids.add(job.job_id)
            self.insert_job_row(job)
            if thumb_u:
                self.fetch_thumbnail(thumb_u, job.job_id)
            self._fetch_oembed_title_async(job.url, job.job_id)
            added_count += 1

        total_dups = dup_in_input + dup_in_queue
        summary_parts = [f"Đã thêm {added_count} link vào Hàng đợi (Chờ tải)"]
        if total_dups > 0:
            summary_parts.append(f"lọc {total_dups} link trùng")
        if invalid_cnt > 0:
            summary_parts.append(f"bỏ qua {invalid_cnt} nội dung không hợp lệ")
        summary_msg = " · ".join(summary_parts)

        if hasattr(self, "batch_link_status"):
            self.batch_link_status.setText(summary_msg)
        self.link_status.setText(summary_msg)
        self.statusBar().showMessage(summary_msg, 6000)
        if added_count > 0:
            self.log(f"{source_label}: {summary_msg} (Bấm 'Tải xuống' để bắt đầu tải).")

        self.refresh_stats()
        self.schedule_save()
        if auto_start and added_count > 0:
            self.start_queue()
        return added_count

    def _fetch_oembed_title_async(self, video_url: str, job_id: str) -> None:
        from urllib.parse import quote
        oembed_url = f"https://www.youtube.com/oembed?url={quote(video_url, safe='')}&format=json"
        req = QNetworkRequest(QUrl(oembed_url))
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Mozilla/5.0")
        reply = self.network.get(req)
        reply.finished.connect(lambda r=reply, jid=job_id: self._on_oembed_finished(r, jid))

    def _on_oembed_finished(self, reply: QNetworkReply, job_id: str) -> None:
        import json
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                raw = bytes(reply.readAll()).decode("utf-8", errors="ignore")
                data = json.loads(raw)
                title = str(data.get("title") or "").strip()
                thumb = str(data.get("thumbnail_url") or "").strip()
                job = self.jobs_by_id.get(job_id)
                if job:
                    if title and (job.title.startswith("Đang chờ tải") or job.title.startswith("Đang lấy thông tin")):
                        job.title = title
                    if thumb and not job.thumbnail_url:
                        job.thumbnail_url = thumb
                        self.fetch_thumbnail(thumb, job.job_id)
                    self.paint_job(job)
                    self.schedule_save()
        except Exception:
            pass
        finally:
            reply.deleteLater()

    # ------------------------------------------------------------------
    # Row List Management, Navigation & Filtering
    # ------------------------------------------------------------------
    def insert_job_row(self, job: Job, *, batch_init: bool = False) -> None:
        row = self.job_table.rowCount()
        self.job_table.insertRow(row)
        self.rows[job.job_id] = row
        for col in range(8):
            self.job_table.setItem(row, col, QTableWidgetItem(""))

        card = JobRow(job, self.cards_container)
        card.clicked_with_modifiers.connect(self.on_job_card_clicked)
        card.set_selected(job.job_id in self.selected_job_ids)
        card.start_requested.connect(self.start_job_by_id)
        card.pause_requested.connect(self.pause_job_by_id)
        card.resume_requested.connect(self.resume_job_by_id)
        card.cancel_requested.connect(self.cancel_job_by_id)
        card.retry_requested.connect(self.retry_job_by_id)
        card.remove_requested.connect(self.remove_job_by_id)
        card.delete_file_requested.connect(self.delete_job_file_by_id)
        card.delete_selected_files_requested.connect(self.delete_selected_job_files)
        card.play_requested.connect(self.play_job_file_by_id)
        card.folder_requested.connect(self.open_job_folder_by_id)
        card.change_folder_requested.connect(self.change_job_folder_by_id)
        card.transcode_requested.connect(self.prompt_transcode_job_by_id)
        card.mute_requested.connect(self.mute_job_by_id)

        thumb_url = (job.thumbnail_url or "").strip()
        if not thumb_url:
            vid = extract_youtube_video_id(job.url)
            if vid:
                thumb_url = f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
                job.thumbnail_url = thumb_url

        if thumb_url and thumb_url in self.thumb_cache:
            card.set_thumbnail_pixmap(self.thumb_cache[thumb_url])
        elif thumb_url and not batch_init:
            self.fetch_thumbnail(thumb_url, job.job_id)

        self.job_cards[job.job_id] = card
        self.cards_layout.insertWidget(0, card)
        self.paint_job(job)
        if not batch_init:
            self.apply_job_filters()

    def paint_job(self, job: Job) -> None:
        card = self.job_cards.get(job.job_id)
        if card is not None:
            card.update_from_job(job)
            if (
                job.thumbnail_url
                and job.thumbnail_url in self.thumb_cache
                and not getattr(card, "_has_custom_thumb", False)
            ):
                card.set_thumbnail_pixmap(self.thumb_cache[job.thumbnail_url])

        row = self.rows.get(job.job_id)
        if row is not None and row < self.job_table.rowCount():
            typ = f"{job.mode} / {job.container}"
            quality = (
                f"ID {job.format_id}"
                if job.format_id
                else (job.quality if job.mode == "video" else "Audio tốt nhất")
            )
            columns = {
                0: job.title,
                1: typ,
                2: quality,
                3: STATUS_TEXT.get(job.status, job.status),
                5: job.speed,
                6: job.eta,
                7: job.filepath or job.error or job.size,
            }
            for idx, value in columns.items():
                item = self.job_table.item(row, idx)
                if item is not None:
                    item.setText(str(value))

    def on_filter_pill_clicked(self, filter_key: str) -> None:
        if filter_key in self.tab_buttons:
            self.current_filter = filter_key
            btn = self.tab_buttons[filter_key]
            btn.blockSignals(True)
            btn.setChecked(True)
            btn.blockSignals(False)
        self.deselect_all_jobs()
        self._update_undo_redo_buttons()
        self.apply_job_filters()

    def switch_workspace_tab(self, tab_key: str) -> None:
        if tab_key == "log":
            self.workspace_stack.setCurrentIndex(1)
            self.sidebar.set_active_page("log")
        elif tab_key == "hardware":
            self.workspace_stack.setCurrentIndex(2)
            self.sidebar.set_active_page("hardware")
            self.refresh_hardware_telemetry()
        elif tab_key == "guide":
            self.workspace_stack.setCurrentIndex(3)
            self.sidebar.set_active_page("guide")
        elif tab_key == "settings":
            self.workspace_stack.setCurrentIndex(4)
            self.sidebar.set_active_page("settings")
            if hasattr(self, "refresh_env_panel"):
                self.refresh_env_panel()
        else:
            filter_key = self.current_filter if tab_key in ("downloads", "batch") else tab_key
            if filter_key in self.tab_buttons:
                self.current_filter = filter_key
                btn = self.tab_buttons[filter_key]
                btn.blockSignals(True)
                btn.setChecked(True)
                btn.blockSignals(False)
            if hasattr(self, "downloads_queue_slot") and hasattr(self, "queue_section"):
                self.downloads_queue_slot.addWidget(self.queue_section, 1)
            self.workspace_stack.setCurrentIndex(0)
            self.sidebar.set_active_page("downloads")
            self.apply_job_filters()

    def _is_recent_job(self, job: Job) -> bool:
        if job.job_id in self.session_job_ids:
            return True
        if job.status in {"queued", "downloading", "processing", "converting", "paused"}:
            return True
        ts_raw = job.updated_at or job.created_at
        if ts_raw:
            try:
                dt = datetime.fromisoformat(ts_raw)
                now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
                if (now - dt).total_seconds() <= 86400:
                    return True
            except Exception:
                pass
        return False

    def job_matches_filter(self, job: Job, filter_key: str, query: str) -> bool:
        if filter_key == "recent" and not self._is_recent_job(job):
            return False
        if filter_key == "queued" and job.status != "queued":
            return False
        if filter_key == "active" and job.status not in {"downloading", "processing", "converting", "paused"}:
            return False
        if filter_key == "done" and job.status != "done":
            return False
        if filter_key == "error" and job.status not in {"error", "cancelled"}:
            return False
        if query:
            haystack = (
                f"{job.title} {job.url} {job.container} {job.video_codec} {job.detected_codec} "
                f"{job.detected_resolution} {job.detected_fps} {job.detected_bitrate} "
                f"{job.directory} {job.filepath} {job.status}"
            ).lower()
            if query not in haystack:
                return False
        return True

    def apply_job_filters(self) -> None:
        query = self.search_edit.text().strip().lower() if hasattr(self, "search_edit") else ""
        visible_count = 0
        for job in self.jobs:
            card = self.job_cards.get(job.job_id)
            if card is None:
                continue
            visible = self.job_matches_filter(job, self.current_filter, query)
            card.setVisible(visible)
            if visible:
                visible_count += 1
                if job.thumbnail_url and not getattr(card, "_has_custom_thumb", False):
                    if job.thumbnail_url in self.thumb_cache:
                        card.set_thumbnail_pixmap(self.thumb_cache[job.thumbnail_url])
                    else:
                        self.fetch_thumbnail(job.thumbnail_url, job.job_id)

        if hasattr(self, "empty_state_frame"):
            self.empty_state_frame.setVisible(visible_count == 0)
            if not self.jobs:
                self.empty_title_label.setText("Chưa có tác vụ tải xuống nào")
                self.empty_sub_label.setText(
                    "Dán liên kết YouTube ở khung phía trên để đưa vào Hàng đợi và bấm 'Tải xuống'."
                )
            elif visible_count == 0:
                self.empty_title_label.setText("Không có mục nào khớp với bộ lọc hiện tại")
                self.empty_sub_label.setText("Hãy chuyển sang bộ lọc 'Tất cả' hoặc xóa từ khóa tìm kiếm.")

    # ------------------------------------------------------------------
    # Single-Row & On-Demand Transcode Actions
    # ------------------------------------------------------------------
    def start_job_by_id(self, job_id: str) -> None:
        job = self.jobs_by_id.get(job_id)
        if not job or job_id in self.active:
            return
        if job.status not in {"queued", "paused", "error", "cancelled"}:
            return
        if not job.directory:
            job.directory = (
                (self.folder_edit.text().strip() if hasattr(self, "folder_edit") else "")
                or self.settings.download_dir
            )
        control = DownloadControl()
        worker = DownloadWorker(job, self.settings_snapshot(), control)
        worker.signals.progress.connect(self.download_progress)
        worker.signals.message.connect(self.download_message)
        worker.signals.complete.connect(self.download_complete)
        self.active[job.job_id] = (worker, control)
        job.status = "downloading"
        job.error = ""
        job.updated_at = timestamp()
        self.paint_job(job)
        self.download_pool.start(worker)
        self.log(f"Bắt đầu tải đơn lẻ: {job.title}")
        self.refresh_stats()
        self.schedule_save()

    def prompt_transcode_job_by_id(self, job_id: str) -> None:
        job = self.jobs_by_id.get(job_id)
        if not job or job_id in self.active:
            return
        if not job.filepath or not Path(job.filepath).is_file():
            QMessageBox.warning(self, "Không tìm thấy file", "File gốc không còn tồn tại trên ổ đĩa.")
            return

        choices = [
            "H.264 / AVC (Tương thích cao nhất)",
            "H.265 / HEVC (Nén tốt, dung lượng nhẹ)",
            "AV1 (Hiện đại)",
            "VP9",
        ]
        codec_map = {
            choices[0]: "h264",
            choices[1]: "h265",
            choices[2]: "av1",
            choices[3]: "vp9",
        }
        selected, ok = QInputDialog.getItem(
            self,
            "Chuyển đổi Video Codec (FFmpeg)",
            f"Chọn Codec đích để chuyển đổi cho video:\n{job.title[:70]}",
            choices,
            0,
            False,
        )
        if not ok or not selected:
            return
        target_codec = codec_map[selected]
        self.start_transcode_job(job, target_codec)

    def mute_job_by_id(self, job_id: str) -> None:
        job = self.jobs_by_id.get(job_id)
        if not job or job_id in self.active:
            return
        if not job.filepath or not Path(job.filepath).is_file():
            QMessageBox.warning(self, "Không tìm thấy file", "File gốc không còn tồn tại trên ổ đĩa.")
            return
        self.start_transcode_job(job, "mute")

    def start_transcode_job(self, job: Job, target_codec: str) -> None:
        if job.job_id in self.active:
            return
        control = DownloadControl()
        worker = TranscodeWorker(job, target_codec, self.settings_snapshot(), control)
        worker.signals.progress.connect(self.download_progress)
        worker.signals.message.connect(self.download_message)
        worker.signals.complete.connect(self.download_complete)
        self.active[job.job_id] = (worker, control)
        if target_codec != "mute":
            job.video_codec = target_codec
        else:
            job.mute_audio = True
        job.status = "converting"
        job.progress = 0.0
        job.error = ""
        job.updated_at = timestamp()
        self.paint_job(job)
        self.download_pool.start(worker)
        self.refresh_stats()
        self.schedule_save()

    def pause_job_by_id(self, job_id: str) -> None:
        job = self.jobs_by_id.get(job_id)
        if job and job_id in self.active and job.status in {"downloading", "processing", "converting"}:
            setattr(job, "_pre_pause_status", job.status)
            self.active[job_id][1].pause()
            job.status = "paused"
            self.paint_job(job)
            self.refresh_stats()
            self.schedule_save()

    def resume_job_by_id(self, job_id: str) -> None:
        job = self.jobs_by_id.get(job_id)
        if not job or job.status != "paused":
            return
        if job_id in self.active:
            self.active[job_id][1].resume()
            job.status = getattr(job, "_pre_pause_status", "downloading")
            self.paint_job(job)
            self.refresh_stats()
            self.schedule_save()
        else:
            job.status = "queued"
            self.paint_job(job)
            self.start_job_by_id(job_id)

    def cancel_job_by_id(self, job_id: str) -> None:
        job = self.jobs_by_id.get(job_id)
        if not job:
            return
        if job_id in self.active:
            self.active[job_id][1].cancel()
            job.status = "cancelled"
        elif job.status in {"queued", "paused"}:
            job.status = "cancelled"
        job.speed = ""
        job.eta = ""
        job.updated_at = timestamp()
        self.paint_job(job)
        self.refresh_stats()
        self.schedule_save()

    def _apply_current_toolbar_config_to_job(self, job: Job) -> None:
        mode = str(self.mode_combo.currentData() or "video")
        ext = str(self.ext_combo.currentData() or ("mp4" if mode == "video" else "mp3"))
        quality = str(self.quality_combo.currentData() or "best")
        v_codec = str(self.codec_combo.currentData() or "h264")
        a_bitrate = str(self.audio_bitrate_combo.currentData() or "192")
        is_muted = mode == "video" and hasattr(self, "mute_btn") and self.mute_btn.isChecked()
        directory = (
            (self.folder_edit.text().strip() if hasattr(self, "folder_edit") else "")
            or self.settings.download_dir
            or job.directory
        )

        job.mode = mode
        job.container = ext
        job.quality = quality
        job.video_codec = v_codec
        job.audio_bitrate = a_bitrate
        job.mute_audio = is_muted
        if directory:
            job.directory = directory
        job.subtitles = self.subtitles_check.isChecked()
        job.sub_langs = self.sub_langs_edit.text().strip() or "vi,en"
        job.embed_metadata = self.embed_meta_check.isChecked()
        job.format_id = ""
        job.format_ext = ""
        job.format_has_audio = False
        job.detected_codec = ""
        job.detected_resolution = ""
        job.detected_fps = ""
        job.detected_bitrate = ""

    def retry_job_by_id(self, job_id: str) -> None:
        job = self.jobs_by_id.get(job_id)
        if not job:
            return
        if job_id in self.active:
            self.statusBar().showMessage("Tác vụ đang kết thúc hủy, vui lòng thử lại sau giây lát...", 3000)
            return
        if job.status in {"done", "error", "cancelled"}:
            self._apply_current_toolbar_config_to_job(job)
            job.status = "queued"
            job.progress = 0.0
            job.speed = ""
            job.eta = ""
            job.error = ""
            job.filepath = ""
            job.updated_at = timestamp()
            self.session_job_ids.add(job.job_id)
            self.paint_job(job)
            self.start_queue()
            self.schedule_save()

    def retry_all_visible(self) -> int:
        query = self.search_edit.text().strip().lower() if hasattr(self, "search_edit") else ""
        target_jobs = [
            j for j in self.jobs
            if j.job_id not in self.active and self.job_matches_filter(j, self.current_filter, query)
        ]
        if not target_jobs:
            self.statusBar().showMessage("Không có mục nào trong danh sách đang xem để tải lại.", 4000)
            return 0
        count = 0
        for job in target_jobs:
            self._apply_current_toolbar_config_to_job(job)
            job.status = "queued"
            job.progress = 0.0
            job.speed = ""
            job.eta = ""
            job.error = ""
            job.filepath = ""
            job.updated_at = timestamp()
            self.session_job_ids.add(job.job_id)
            self.paint_job(job)
            count += 1
        if count > 0:
            self.log(f"Tải lại tất cả ({count} mục trong tab hiện tại) theo cấu hình mới.")
            self.statusBar().showMessage(f"Đang tải lại {count} mục theo cấu hình hiện tại...", 5000)
            self.start_queue()
        self.refresh_stats()
        self.schedule_save()
        return count

    def _push_deleted_batch(self, batch: list[tuple[int, Job]]) -> None:
        if not batch:
            return
        tab = getattr(self, "current_filter", "recent")
        stack = self.tab_undo_stacks.setdefault(tab, [])
        stack.append(batch)
        if len(stack) > 30:
            stack.pop(0)
        self.tab_redo_stacks.setdefault(tab, []).clear()
        self._update_undo_redo_buttons()

    def _update_undo_button(self) -> None:
        self._update_undo_redo_buttons()

    def _update_undo_redo_buttons(self) -> None:
        current_tab = getattr(self, "current_filter", "recent")
        undo_stack = self.tab_undo_stacks.setdefault(current_tab, [])
        redo_stack = self.tab_redo_stacks.setdefault(current_tab, [])

        if hasattr(self, "undo_btn"):
            has_undo = bool(undo_stack)
            self.undo_btn.setEnabled(has_undo)
            if has_undo:
                last_cnt = len(undo_stack[-1])
                self.undo_btn.setText(f"Hoàn tác ({last_cnt})" if last_cnt > 1 else "Hoàn tác")
            else:
                self.undo_btn.setText("Hoàn tác")

        if hasattr(self, "redo_btn"):
            has_redo = bool(redo_stack)
            self.redo_btn.setEnabled(has_redo)
            if has_redo:
                last_cnt = len(redo_stack[-1])
                self.redo_btn.setText(f"Làm lại ({last_cnt})" if last_cnt > 1 else "Làm lại")
            else:
                self.redo_btn.setText("Làm lại")

    def remove_job_by_id(self, job_id: str) -> None:
        if job_id in self.active:
            self.statusBar().showMessage("Không thể xóa tác vụ đang chạy; hãy bấm Hủy trước.", 5000)
            return
        removed_entries: list[tuple[int, Job]] = []
        for idx, j in enumerate(self.jobs):
            if j.job_id == job_id:
                removed_entries.append((idx, replace(j)))
                break
        if removed_entries:
            self._push_deleted_batch(removed_entries)
        self.jobs = [j for j in self.jobs if j.job_id != job_id]
        self.jobs_by_id.pop(job_id, None)
        self.selected_job_ids.discard(job_id)
        if self.last_selected_job_id == job_id:
            self.last_selected_job_id = None
        card = self.job_cards.pop(job_id, None)
        if card is not None:
            card.setParent(None)
            card.deleteLater()
        self._rebuild_legacy_rows()
        self.refresh_stats()
        self.schedule_save()
        self.statusBar().showMessage("Đã xóa tác vụ khỏi hàng đợi (Bấm 'Hoàn tác' để khôi phục).", 4000)

    def clear_all_jobs(self) -> None:
        removed_entries: list[tuple[int, Job]] = []
        remaining: list[Job] = []
        for idx, j in enumerate(self.jobs):
            if j.job_id in self.active:
                remaining.append(j)
            else:
                removed_entries.append((idx, replace(j)))
        if not removed_entries:
            self.statusBar().showMessage("Không có tác vụ nào trong hàng đợi để xóa.", 4000)
            return
        self._push_deleted_batch(removed_entries)
        self.jobs = remaining
        for _idx, removed_job in removed_entries:
            self.jobs_by_id.pop(removed_job.job_id, None)
            self.selected_job_ids.discard(removed_job.job_id)
            card = self.job_cards.pop(removed_job.job_id, None)
            if card is not None:
                card.setParent(None)
                card.deleteLater()
        self.last_selected_job_id = None
        self._rebuild_legacy_rows()
        self.refresh_stats()
        self.schedule_save()
        self.log(f"Đã xóa {len(removed_entries)} mục khỏi hàng đợi.")
        self.statusBar().showMessage(
            f"Đã xóa {len(removed_entries)} mục khỏi hàng đợi (Bấm 'Hoàn tác' để khôi phục).",
            5000,
        )

    def undo_last_remove(self) -> None:
        tab = getattr(self, "current_filter", "recent")
        undo_stack = self.tab_undo_stacks.setdefault(tab, [])
        if not undo_stack:
            self.statusBar().showMessage("Không có thao tác xóa nào để hoàn tác trong tab này.", 4000)
            return
        batch = undo_stack.pop()
        restored_count = 0
        for idx, restored_job in sorted(batch, key=lambda item: item[0]):
            if restored_job.job_id in self.jobs_by_id:
                continue
            insert_pos = min(max(0, idx), len(self.jobs))
            self.jobs.insert(insert_pos, restored_job)
            self.jobs_by_id[restored_job.job_id] = restored_job
            restored_count += 1

        self.tab_redo_stacks.setdefault(tab, []).append(batch)

        self._rebuild_cards_and_rows()
        self._update_undo_redo_buttons()
        self.refresh_stats()
        self.schedule_save()
        if restored_count > 0:
            self.log(f"Hoàn tác ({tab}): Đã khôi phục {restored_count} mục vào hàng đợi.")
            self.statusBar().showMessage(f"Đã hoàn tác và khôi phục {restored_count} mục vào hàng đợi.", 5000)

    def redo_last_remove(self) -> None:
        tab = getattr(self, "current_filter", "recent")
        redo_stack = self.tab_redo_stacks.setdefault(tab, [])
        if not redo_stack:
            self.statusBar().showMessage("Không có thao tác nào để làm lại trong tab này.", 4000)
            return
        batch = redo_stack.pop()
        removed_entries: list[tuple[int, Job]] = []
        for idx, target_job in sorted(batch, key=lambda item: item[0], reverse=True):
            jid = target_job.job_id
            if jid in self.active:
                continue
            cur_idx = next((i for i, j in enumerate(self.jobs) if j.job_id == jid), None)
            if cur_idx is not None:
                removed_entries.append((cur_idx, replace(self.jobs[cur_idx])))
                del self.jobs[cur_idx]
                self.jobs_by_id.pop(jid, None)
                self.selected_job_ids.discard(jid)
                card = self.job_cards.pop(jid, None)
                if card is not None:
                    card.setParent(None)
                    card.deleteLater()

        if removed_entries:
            removed_entries.reverse()
            self.tab_undo_stacks.setdefault(tab, []).append(removed_entries)

        self._rebuild_legacy_rows()
        self._update_undo_redo_buttons()
        self.refresh_stats()
        self.schedule_save()
        if removed_entries:
            self.log(f"Làm lại ({tab}): Đã xóa lại {len(removed_entries)} mục.")
            self.statusBar().showMessage(f"Đã làm lại thao tác xóa {len(removed_entries)} mục.", 5000)

    def _rebuild_cards_and_rows(self) -> None:
        for card in list(self.job_cards.values()):
            card.setParent(None)
            card.deleteLater()
        self.job_cards.clear()
        self.job_table.setRowCount(0)
        self.rows.clear()
        for job in self.jobs:
            self.insert_job_row(job)
        self.apply_job_filters()

    # ------------------------------------------------------------------
    # Selection & Keyboard Shortcuts Management
    # ------------------------------------------------------------------
    def get_visible_jobs(self) -> list[Job]:
        query = self.search_edit.text().strip().lower() if hasattr(self, "search_edit") else ""
        return [job for job in self.jobs if self.job_matches_filter(job, self.current_filter, query)]

    def on_job_card_clicked(self, job_id: str, modifiers: object) -> None:
        shift = False
        ctrl = False
        try:
            shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
            ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        except Exception:
            pass

        visible_jobs = self.get_visible_jobs()
        visible_ids = [j.job_id for j in visible_jobs]

        if shift and self.last_selected_job_id and self.last_selected_job_id in visible_ids and job_id in visible_ids:
            idx1 = visible_ids.index(self.last_selected_job_id)
            idx2 = visible_ids.index(job_id)
            start, end = min(idx1, idx2), max(idx1, idx2)
            range_ids = set(visible_ids[start : end + 1])
            if ctrl:
                self.selected_job_ids.update(range_ids)
            else:
                self.selected_job_ids = range_ids
        elif ctrl:
            if job_id in self.selected_job_ids:
                self.selected_job_ids.discard(job_id)
            else:
                self.selected_job_ids.add(job_id)
                self.last_selected_job_id = job_id
        else:
            self.selected_job_ids = {job_id}
            self.last_selected_job_id = job_id

        self._update_selection_visuals()

    def _update_selection_visuals(self) -> None:
        for jid, card in self.job_cards.items():
            card.set_selected(jid in self.selected_job_ids)

    def select_all_jobs(self) -> None:
        visible_jobs = self.get_visible_jobs()
        self.selected_job_ids = {j.job_id for j in visible_jobs}
        if visible_jobs:
            self.last_selected_job_id = visible_jobs[-1].job_id
        self._update_selection_visuals()

    def deselect_all_jobs(self) -> None:
        self.selected_job_ids.clear()
        self.last_selected_job_id = None
        self._update_selection_visuals()

    def delete_selected_jobs(self) -> None:
        if not self.selected_job_ids:
            return
        active_selected = [jid for jid in self.selected_job_ids if jid in self.active]
        if active_selected:
            self.statusBar().showMessage(f"Bỏ qua {len(active_selected)} tác vụ đang chạy tải.", 4000)

        removable_ids = self.selected_job_ids - set(active_selected)
        if not removable_ids:
            return

        removed_entries: list[tuple[int, Job]] = []
        remaining: list[Job] = []
        for idx, j in enumerate(self.jobs):
            if j.job_id in removable_ids:
                removed_entries.append((idx, replace(j)))
            else:
                remaining.append(j)

        if not removed_entries:
            return

        self._push_deleted_batch(removed_entries)
        self.jobs = remaining
        for _idx, removed_job in removed_entries:
            self.jobs_by_id.pop(removed_job.job_id, None)
            card = self.job_cards.pop(removed_job.job_id, None)
            if card is not None:
                card.setParent(None)
                card.deleteLater()

        self.deselect_all_jobs()
        self._rebuild_legacy_rows()
        self.refresh_stats()
        self.schedule_save()
        self.log(f"Đã xóa {len(removed_entries)} mục được chọn.")
        self.statusBar().showMessage(
            f"Đã xóa {len(removed_entries)} mục (Bấm 'Hoàn tác' hoặc Ctrl+Z để khôi phục).",
            5000,
        )

    def start_selected_jobs(self) -> None:
        if not self.selected_job_ids:
            return
        started = 0
        for jid in list(self.selected_job_ids):
            job = self.jobs_by_id.get(jid)
            if not job:
                continue
            if job.status == "paused":
                self.resume_job_by_id(jid)
                started += 1
            elif job.status in {"error", "cancelled"}:
                self.retry_job_by_id(jid)
                started += 1
            elif job.status == "queued":
                started += 1
        self.start_queue()
        if started:
            self.statusBar().showMessage(f"Đã kích hoạt tải {started} tác vụ được chọn.", 4000)

    def toggle_selected_jobs_playback(self) -> None:
        if not self.selected_job_ids:
            return
        if len(self.selected_job_ids) == 1:
            single_id = next(iter(self.selected_job_ids))
            job = self.jobs_by_id.get(single_id)
            if job and job.status == "done":
                self.play_job_file_by_id(single_id)
                return

        running_ids = [
            jid
            for jid in self.selected_job_ids
            if jid in self.active
            and self.jobs_by_id.get(jid)
            and self.jobs_by_id[jid].status in {"downloading", "processing", "converting"}
        ]
        if running_ids:
            for jid in running_ids:
                self.pause_job_by_id(jid)
            self.statusBar().showMessage(f"Đã tạm dừng {len(running_ids)} tác vụ đang tải.", 4000)
            return

        paused_ids = [
            jid
            for jid in self.selected_job_ids
            if jid in self.active and self.jobs_by_id.get(jid) and self.jobs_by_id[jid].status == "paused"
        ]
        if paused_ids:
            for jid in paused_ids:
                self.resume_job_by_id(jid)
            self.statusBar().showMessage(f"Đã tiếp tục {len(paused_ids)} tác vụ.", 4000)
            return

    def keyPressEvent(self, event: QKeyEvent) -> None:
        focused = self.focusWidget()
        if isinstance(focused, (QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox)):
            super().keyPressEvent(event)
            return

        key = event.key()
        modifiers = event.modifiers()

        # Ctrl + Shift + Z or Ctrl + Y: Redo
        if (
            key == Qt.Key.Key_Z
            and (modifiers == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
        ) or (key == Qt.Key.Key_Y and modifiers == Qt.KeyboardModifier.ControlModifier):
            self.redo_last_remove()
            event.accept()
            return

        # Ctrl + Z: Undo
        if key == Qt.Key.Key_Z and modifiers == Qt.KeyboardModifier.ControlModifier:
            self.undo_last_remove()
            event.accept()
            return

        # Ctrl + Shift + A: Deselect all
        if key == Qt.Key.Key_A and (
            modifiers == (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        ):
            self.deselect_all_jobs()
            event.accept()
            return

        # Ctrl + A: Select all
        if key == Qt.Key.Key_A and modifiers == Qt.KeyboardModifier.ControlModifier:
            self.select_all_jobs()
            event.accept()
            return

        # Escape: Deselect all
        if key == Qt.Key.Key_Escape and modifiers == Qt.KeyboardModifier.NoModifier:
            self.deselect_all_jobs()
            event.accept()
            return

        # Delete / Backspace: Delete selected
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and modifiers == Qt.KeyboardModifier.NoModifier:
            if self.selected_job_ids:
                self.delete_selected_jobs()
                event.accept()
                return

        # Enter / Return: Start selected
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and modifiers == Qt.KeyboardModifier.NoModifier:
            if self.selected_job_ids:
                self.start_selected_jobs()
                event.accept()
                return

        # Space: Play / Pause toggle
        if key == Qt.Key.Key_Space and modifiers == Qt.KeyboardModifier.NoModifier:
            if self.selected_job_ids:
                self.toggle_selected_jobs_playback()
                event.accept()
                return

        super().keyPressEvent(event)

    def play_job_file_by_id(self, job_id: str) -> None:
        job = self.jobs_by_id.get(job_id)
        if not job:
            return
        if job.filepath and Path(job.filepath).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(job.filepath).resolve())))
        else:
            QMessageBox.information(self, "Không tìm thấy file", "File không tồn tại hoặc đã bị di chuyển.")

    def open_job_folder_by_id(self, job_id: str) -> None:
        job = self.jobs_by_id.get(job_id)
        if not job:
            return
        candidate = Path(job.filepath) if job.filepath else Path(job.directory)
        if candidate.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(candidate.parent.resolve())))
        elif candidate.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(candidate.resolve())))
        else:
            QMessageBox.information(self, "Không tìm thấy", "Đường dẫn không tồn tại hoặc file đã bị di chuyển.")

    def delete_job_file_by_id(self, job_id: str) -> None:
        job = self.jobs_by_id.get(job_id)
        if not job:
            return

        filepath = getattr(job, "filepath", "")
        if not filepath:
            self.statusBar().showMessage("Không tìm thấy đường dẫn tệp của tác vụ này.", 4000)
            return

        file_path_obj = Path(filepath)
        if not file_path_obj.exists():
            QMessageBox.information(
                self,
                "Tệp không tồn tại",
                f"Tệp không tồn tại trên đĩa:\n{filepath}\n\nThẻ sẽ được xóa khỏi danh sách tải.",
            )
            self.remove_job_by_id(job_id)
            return

        file_name = file_path_obj.name
        ans = QMessageBox.question(
            self,
            "Xác nhận xóa tệp",
            f"Bạn có chắc muốn xóa tệp này khỏi máy tính và chuyển vào Thùng rác không?\n\n"
            f"• Tên tệp: {file_name}\n"
            f"• Đường dẫn: {filepath}\n\n"
            f"(Bạn vẫn có thể khôi phục tệp từ Thùng rác / Recycle Bin của Windows nếu cần)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        success = send_to_trash(file_path_obj)
        if success:
            self.remove_job_by_id(job_id)
            self.log(f"Đã chuyển tệp vào Thùng rác: {filepath}")
            self.statusBar().showMessage(f"Đã chuyển tệp '{file_name}' vào Thùng rác.", 5000)
        else:
            QMessageBox.warning(
                self,
                "Không thể xóa tệp",
                f"Không thể xóa tệp sau:\n{filepath}\n\nTệp có thể đang được mở bởi chương trình khác hoặc bạn không có quyền ghi.",
            )

    def delete_selected_job_files(self) -> None:
        if not self.selected_job_ids:
            return

        target_jobs: list[Job] = []
        for jid in list(self.selected_job_ids):
            job = self.jobs_by_id.get(jid)
            if not job or job.status != "done" or not job.filepath:
                continue
            try:
                if Path(job.filepath).exists():
                    target_jobs.append(job)
            except Exception:
                pass

        if not target_jobs:
            self.statusBar().showMessage("Không có tệp đã tải xong nào trong các mục được chọn.", 4000)
            return

        ans = QMessageBox.question(
            self,
            "Xác nhận xóa hàng loạt tệp",
            f"Bạn có chắc muốn xóa {len(target_jobs)} tệp đã chọn khỏi máy tính và chuyển vào Thùng rác không?\n\n"
            f"(Các tệp sẽ được đưa vào Thùng rác và thẻ tương ứng sẽ được gỡ khỏi danh sách)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        deleted_count = 0
        failed_count = 0
        to_remove_ids: list[str] = []

        for job in target_jobs:
            if send_to_trash(job.filepath):
                deleted_count += 1
                to_remove_ids.append(job.job_id)
            else:
                failed_count += 1

        for jid in to_remove_ids:
            self.remove_job_by_id(jid)

        if failed_count > 0:
            self.log(f"Đã chuyển {deleted_count} tệp vào Thùng rác, thất bại {failed_count} tệp.")
            self.statusBar().showMessage(
                f"Đã xóa {deleted_count} tệp vào Thùng rác ({failed_count} tệp không thể xóa).",
                5000,
            )
        else:
            self.log(f"Đã chuyển {deleted_count} tệp vào Thùng rác.")
            self.statusBar().showMessage(f"Đã chuyển {deleted_count} tệp vào Thùng rác thành công.", 5000)


    def change_job_folder_by_id(self, job_id: str) -> None:
        job = self.jobs_by_id.get(job_id)
        if not job or job.status not in {"queued", "paused", "error", "cancelled"}:
            return
        initial_dir = (
            job.directory
            or (self.folder_edit.text().strip() if hasattr(self, "folder_edit") else "")
            or self.settings.download_dir
        )
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu cho video này", initial_dir)
        if folder:
            job.directory = folder
            self.paint_job(job)
            self.statusBar().showMessage(f"Đã đổi thư mục lưu: {folder}", 4000)
            self.schedule_save()

    def pause_all_active(self) -> None:
        count = 0
        for job_id, (_, control) in list(self.active.items()):
            job = self.jobs_by_id.get(job_id)
            if job and job.status in {"downloading", "processing", "converting"}:
                setattr(job, "_pre_pause_status", job.status)
                control.pause()
                job.status = "paused"
                self.paint_job(job)
                count += 1
        if count:
            self.statusBar().showMessage(f"Đã tạm dừng {count} tác vụ đang tải.", 4000)
        self.refresh_stats()
        self.schedule_save()

    def resume_all_paused(self) -> None:
        count = 0
        for job_id, (_, control) in list(self.active.items()):
            job = self.jobs_by_id.get(job_id)
            if job and job.status == "paused":
                control.resume()
                job.status = getattr(job, "_pre_pause_status", "downloading")
                self.paint_job(job)
                count += 1
        # Đồng thời kiểm tra nếu có tác vụ paused chưa có trong active thì chuyển về queued
        for job in self.jobs:
            if job.status == "paused" and job.job_id not in self.active:
                job.status = "queued"
                self.paint_job(job)
                count += 1
        if count:
            self.statusBar().showMessage(f"Đã tiếp tục {count} tác vụ.", 4000)
        self.queue_running = True
        self.schedule_next()
        self.refresh_stats()
        self.schedule_save()

    def retry_all_failed(self) -> None:
        count = 0
        for job in self.jobs:
            if job.job_id not in self.active and job.status in {"error", "cancelled"}:
                job.status = "queued"
                job.progress = 0.0
                job.speed = ""
                job.eta = ""
                job.error = ""
                job.filepath = ""
                self.paint_job(job)
                count += 1
        if count:
            self.statusBar().showMessage(f"Đang tải lại {count} tác vụ.", 4000)
            self.start_queue()
        self.refresh_stats()
        self.schedule_save()

    def clear_completed_jobs(self) -> None:
        removed_entries: list[tuple[int, Job]] = []
        removable: set[str] = set()
        for idx, j in enumerate(self.jobs):
            if j.job_id not in self.active and j.status in {"done", "cancelled"}:
                removable.add(j.job_id)
                removed_entries.append((idx, replace(j)))
        if not removable:
            self.statusBar().showMessage("Không có mục hoàn tất/đã hủy nào để xóa.", 4000)
            return
        self._push_deleted_batch(removed_entries)
        self.jobs = [j for j in self.jobs if j.job_id not in removable]
        for ident in removable:
            self.jobs_by_id.pop(ident, None)
            self.selected_job_ids.discard(ident)
            card = self.job_cards.pop(ident, None)
            if card is not None:
                card.setParent(None)
                card.deleteLater()
        if self.last_selected_job_id in removable:
            self.last_selected_job_id = None
        self._rebuild_legacy_rows()
        self.refresh_stats()
        self.schedule_save()
        self.statusBar().showMessage(f"Đã dọn {len(removable)} mục khỏi danh sách.", 4000)

    def _rebuild_legacy_rows(self) -> None:
        self.job_table.setRowCount(0)
        self.rows.clear()
        for job in self.jobs:
            row = self.job_table.rowCount()
            self.job_table.insertRow(row)
            self.rows[job.job_id] = row
            for col in range(8):
                self.job_table.setItem(row, col, QTableWidgetItem(""))
            self.paint_job(job)

    def selected_jobs(self) -> list[Job]:
        indexes = self.job_table.selectionModel().selectedRows()
        result = []
        for index in indexes:
            row = index.row()
            if 0 <= row < len(self.jobs):
                result.append(self.jobs[row])
        return result

    def toggle_queue_running(self) -> None:
        """Nút chuyển đổi Tiếp tục tải / Tạm dừng tất cả."""
        # 1. Nếu đang có tác vụ đang tải chạy ngầm -> Tạm dừng tất cả!
        has_active_running = any(
            j.status in {"downloading", "processing", "converting"}
            for j in self.jobs
            if j.job_id in self.active
        )
        if has_active_running:
            self.stop_queue()
            self.pause_all_active()
            self.statusBar().showMessage("Đã tạm dừng tất cả tiến trình tải.", 4000)
            self._update_queue_toggle_icon()
            return

        # 2. Nếu có tác vụ đang bị tạm dừng (paused) -> Tiếp tục tất cả!
        has_paused = any(j.status == "paused" for j in self.jobs)
        has_queued = any(j.status == "queued" for j in self.jobs)

        if has_paused:
            self.resume_all_paused()
            self.start_queue()
            self.statusBar().showMessage("Đang tiếp tục tải tất cả tác vụ...", 4000)
        elif has_queued:
            self.start_queue()
            self.statusBar().showMessage("Bắt đầu tải các tác vụ trong Hàng chờ.", 4000)
        else:
            has_retryable = any(j.status in {"error", "cancelled"} for j in self.jobs)
            if has_retryable:
                self.retry_all_failed()
                self.start_queue()
                self.statusBar().showMessage("Đang tải lại các tác vụ lỗi/hủy.", 4000)
            else:
                self.statusBar().showMessage("Không có tác vụ nào đang chờ hoặc tạm dừng.", 4000)

        self._update_queue_toggle_icon()

    def start_queue(self) -> None:
        self.queue_running = True
        self.schedule_next()
        self.refresh_stats()

    def stop_queue(self) -> None:
        self.queue_running = False
        self.refresh_stats()
        self.log("Đã dừng nhận tác vụ mới; lượt tải đang chạy tiếp tục bình thường.")

    def pause_selected(self) -> None:
        for job in self.selected_jobs():
            self.pause_job_by_id(job.job_id)

    def resume_selected(self) -> None:
        for job in self.selected_jobs():
            self.resume_job_by_id(job.job_id)

    def cancel_selected(self) -> None:
        for job in self.selected_jobs():
            self.cancel_job_by_id(job.job_id)

    def retry_selected(self) -> None:
        for job in self.selected_jobs():
            self.retry_job_by_id(job.job_id)

    def remove_selected(self) -> None:
        for job in list(self.selected_jobs()):
            self.remove_job_by_id(job.job_id)

    def open_selected_file(self) -> None:
        selected = self.selected_jobs()
        if selected:
            self.open_job_folder_by_id(selected[0].job_id)

    # ------------------------------------------------------------------
    # Worker Scheduling & Progress Callbacks
    # ------------------------------------------------------------------
    def _collides_with_any_active(self, candidate: Job) -> bool:
        for active_id in self.active:
            active_job = self.jobs_by_id.get(active_id)
            if active_job and self._jobs_collide(active_job, candidate):
                return True
        return False

    def schedule_next(self) -> None:
        if not self.queue_running or self.closing_after_cancel:
            return
        max_active = self.concurrent_spin.value()
        while len(self.active) < max_active:
            waiting = next(
                (
                    job for job in self.jobs
                    if job.status == "queued"
                    and job.job_id not in self.active
                    and not self._collides_with_any_active(job)
                ),
                None,
            )
            if waiting is None:
                break
            if not waiting.directory:
                waiting.directory = (
                    (self.folder_edit.text().strip() if hasattr(self, "folder_edit") else "")
                    or self.settings.download_dir
                )
            control = DownloadControl()
            worker = DownloadWorker(waiting, self.settings_snapshot(), control)
            worker.signals.progress.connect(self.download_progress)
            worker.signals.message.connect(self.download_message)
            worker.signals.complete.connect(self.download_complete)
            self.active[waiting.job_id] = (worker, control)
            waiting.status = "downloading"
            waiting.error = ""
            waiting.updated_at = timestamp()
            self.paint_job(waiting)
            self.download_pool.start(worker)
            self.log(f"Bắt đầu: {waiting.title}")
        self.refresh_stats()
        self.schedule_save()

    def settings_snapshot(self) -> Settings:
        return replace(self.settings)

    def download_progress(self, job_id: str, data: dict) -> None:
        job = self.jobs_by_id.get(job_id)
        if not job or job_id not in self.active or job.status == "cancelled":
            return
        if job.status != "paused":
            job.status = data.get("status", "downloading")
        if data.get("title"):
            job.title = str(data["title"])
        if data.get("detected_codec"):
            job.detected_codec = str(data["detected_codec"])
        if data.get("detected_resolution"):
            job.detected_resolution = str(data["detected_resolution"])
        if data.get("detected_fps"):
            job.detected_fps = str(data["detected_fps"])
        if data.get("detected_bitrate"):
            job.detected_bitrate = str(data["detected_bitrate"])
        if data.get("thumbnail_url"):
            new_thumb = str(data["thumbnail_url"]).strip()
            if new_thumb and (not job.thumbnail_url or job.thumbnail_url != new_thumb):
                job.thumbnail_url = new_thumb
            card = self.job_cards.get(job_id)
            if job.thumbnail_url and (
                job.thumbnail_url not in self.thumb_cache
                or not card
                or not getattr(card, "_has_custom_thumb", False)
            ):
                self.fetch_thumbnail(job.thumbnail_url, job.job_id)
        job.progress = float(data.get("progress", job.progress))
        job.speed = data.get("speed", job.speed)
        job.eta = data.get("eta", job.eta)
        job.size = data.get("size", job.size)
        self.paint_job(job)
        self.schedule_save()

    def download_message(self, job_id: str, msg: str) -> None:
        job = self.jobs_by_id.get(job_id)
        title = job.title[:55] if job else job_id[:8]
        self.log(f"[{title}] {msg}")

    @staticmethod
    def _is_bot_cookie_error_text(text: str) -> bool:
        low = (text or "").lower()
        return (
            "xác minh chống bot" in low
            or "not a bot" in low
            or "sign in to confirm" in low
            or "--cookies-from-browser" in low
            or "confirm your age" in low
        )

    def open_cookie_paste_dialog(self, error_reason: str = "") -> bool:
        if isinstance(error_reason, bool):
            error_reason = ""
        if getattr(self, "_bot_dialog_active", False):
            return False
        self._bot_dialog_active = True
        try:
            dlg = CookieVerifyDialog(self, error_reason=error_reason)
            if dlg.exec() == CookieVerifyDialog.DialogCode.Accepted:
                norm_text, count = dlg.normalized_cookies()
                if norm_text and count > 0:
                    target_cookie = app_data_dir() / "cookies.txt"
                    target_cookie.parent.mkdir(parents=True, exist_ok=True)
                    target_cookie.write_text(norm_text, encoding="utf-8")
                    self.settings.cookie_file = str(target_cookie)
                    if hasattr(self, "cookie_edit"):
                        self.cookie_edit.setText(str(target_cookie))
                    self.save_all()
                    self.log(f"Đã lưu {count} dòng Cookie YouTube vào {target_cookie}")
                    self.statusBar().showMessage(
                        f"Đã lưu {count} dòng Cookie vào cookies.txt — đang tự động tải lại các mục lỗi...",
                        6000,
                    )
                    if any(j.status == "error" for j in self.jobs):
                        self.retry_all_failed()
                    return True
        finally:
            self._bot_dialog_active = False
        return False

    def download_complete(self, job_id: str, status: str, value: str) -> None:
        self.active.pop(job_id, None)
        job = self.jobs_by_id.get(job_id)
        is_bot_err = False
        if job:
            job.status = status
            job.updated_at = timestamp()
            job.speed = ""
            job.eta = ""
            if status == "done":
                job.progress = 100.0
                job.filepath = value
                if value and job.title.startswith("Đang lấy thông tin"):
                    job.title = Path(value).stem
                if not value:
                    self.log(f"Tải xong {job.title}, nhưng không xác định được đường dẫn file.")
            elif status == "error":
                job.error = value
                is_bot_err = self._is_bot_cookie_error_text(value)
            self.paint_job(job)
            self.log(f"{STATUS_TEXT[status]}: {job.title}" + (f" | {value}" if status == "error" else ""))

        self.refresh_stats()
        self.schedule_save()

        if self.closing_after_cancel and not self.active:
            self.save_all()
            QTimer.singleShot(0, self.close)
            return

        self.schedule_next()

        if (
            is_bot_err
            and self.isVisible()
            and not getattr(self, "_bot_dialog_active", False)
            and not getattr(self, "_suppress_auto_bot_dialog", False)
        ):
            QTimer.singleShot(200, lambda msg=value: self.open_cookie_paste_dialog(error_reason=msg))

        has_queued = any(j.status == "queued" for j in self.jobs)
        if not self.active and not has_queued and status in {"done", "error"}:
            self.notify_queue_finished()

    def notify_queue_finished(self) -> None:
        done_count = sum(1 for j in self.jobs if j.status == "done")
        error_count = sum(1 for j in self.jobs if j.status == "error")
        msg = f"Đã hoàn tất hàng đợi ({done_count} thành công" + (f", {error_count} lỗi)." if error_count else ").")
        self.statusBar().showMessage(msg, 8000)
        if not self.settings.notify_on_complete:
            return
        QApplication.beep()
        if self.tray_icon is not None:
            try:
                if not self.tray_icon.isVisible():
                    self.tray_icon.show()
                self.tray_icon.showMessage(
                    "Hoàn tất tải xuống",
                    msg,
                    QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Remote Updater & Auto-Saving Settings Handlers
    # ------------------------------------------------------------------
    def check_remote_update_silent(self) -> None:
        worker = UpdateCheckWorker("")
        worker.signals.checked.connect(self._on_silent_update_checked)
        self.analyze_pool.start(worker)

    def _on_silent_update_checked(self, info: UpdateInfo) -> None:
        if hasattr(self, "apply_update_check_result"):
            self.apply_update_check_result(info)
        elif info.has_update:
            self.sidebar.set_update_badge(info.latest_version)
        if info.has_update:
            self.statusBar().showMessage(
                f"Phát hiện phiên bản mới v{info.latest_version}! Mở mục 'Cài đặt → Cập nhật' để nâng cấp.",
                10000,
            )

    def open_updater_dialog(self) -> None:
        self.switch_workspace_tab("settings")
        if hasattr(self, "settings_sub_segment"):
            self.settings_sub_segment.setCurrentIndex(1)

    def open_settings(self, initial_tab: int = 0) -> None:
        if isinstance(initial_tab, bool):
            initial_tab = 0
        if initial_tab == 2:
            self.switch_workspace_tab("guide")
        else:
            self.switch_workspace_tab("settings")
            if hasattr(self, "settings_sub_segment"):
                self.settings_sub_segment.setCurrentIndex(min(2, max(0, initial_tab)))

    def on_theme_preference_changed(self) -> None:
        pref = self.theme_segment.currentData() or "system"
        self.settings.theme_mode = str(pref)
        theme_manager().apply(self.settings.theme_mode)
        self.schedule_save()

    def on_folder_text_changed(self, text: str) -> None:
        if hasattr(self, "folder_chip"):
            self.folder_chip.set_path(text)
        if hasattr(self, "batch_folder_chip"):
            self.batch_folder_chip.set_path(text)

    def on_folder_edited(self) -> None:
        value = self.folder_edit.text().strip()
        if value:
            self.settings.download_dir = value
            if hasattr(self, "folder_chip"):
                self.folder_chip.set_path(value)
            if hasattr(self, "batch_folder_chip"):
                self.batch_folder_chip.set_path(value)
            # Tự động đồng bộ thư mục lưu mới cho tất cả các tác vụ đang ở Hàng chờ
            updated_cnt = 0
            for j in self.jobs:
                if j.status == "queued":
                    j.directory = value
                    self.paint_job(j)
                    updated_cnt += 1
            if updated_cnt > 0:
                self.statusBar().showMessage(
                    f"Đã cập nhật thư mục lưu mới cho {updated_cnt} tác vụ trong Hàng chờ.", 4000
                )
            self.schedule_save()

    def reset_default_folder(self) -> None:
        default_str = str(default_download_dir())
        self.folder_edit.setText(default_str)
        self.on_folder_edited()

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục tải xuống", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)
            self.on_folder_edited()

    def open_download_folder(self) -> None:
        folder = Path(self.folder_edit.text().strip()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))

    def open_app_data_folder(self) -> None:
        data_folder = app_data_dir()
        data_folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_folder.resolve())))

    def concurrent_changed(self, value: int) -> None:
        self.settings.max_concurrent = int(value)
        self.schedule_save()
        self.schedule_next()

    def on_fragments_changed(self, value: int) -> None:
        self.settings.fragment_connections = int(value)
        self.schedule_save()

    def on_hw_accel_changed(self) -> None:
        self.settings.hw_accel = str(self.hw_accel_combo.currentData() or "auto")
        self.schedule_save()

    def on_browser_cookie_changed(self) -> None:
        if hasattr(self, "browser_cookie_combo"):
            self.settings.cookies_from_browser = str(self.browser_cookie_combo.currentData() or "")
            self.schedule_save()

    def on_cookie_edited(self) -> None:
        self.settings.cookie_file = self.cookie_edit.text().strip()
        self.schedule_save()

    def clear_cookie_file(self) -> None:
        self.cookie_edit.clear()
        self.on_cookie_edited()

    def on_system_flags_changed(self) -> None:
        self.settings.keep_history = self.keep_history_check.isChecked()
        self.settings.notify_on_complete = self.notify_check.isChecked()
        self.settings.auto_check_updates = self.auto_update_check.isChecked()
        self.schedule_save()

    def _update_queue_toggle_icon(self) -> None:
        if not hasattr(self, "start_btn"):
            return
        t = theme_manager().tokens
        has_active_running = any(
            j.status in {"downloading", "processing", "converting"}
            for j in self.jobs
            if j.job_id in self.active
        )
        ic_name = "pause" if has_active_running else "play"
        self.start_btn.setProperty("lucideIcon", ic_name)
        self.start_btn.setIcon(icons.icon(ic_name, color=t["text_secondary"], size=15))
        self.start_btn.setIconSize(QSize(15, 15))
        self.start_btn.setToolTip(
            "Tạm dừng tất cả tiến trình tải đang chạy"
            if has_active_running
            else "Tiếp tục tải / Bắt đầu tất cả tác vụ trong hàng đợi"
        )

    def refresh_stats(self) -> None:
        statuses = [j.status for j in self.jobs]
        total_cnt = len(statuses)
        recent_cnt = sum(1 for j in self.jobs if self._is_recent_job(j))
        queued_cnt = statuses.count("queued")
        active_cnt = sum(1 for s in statuses if s in {"downloading", "processing", "converting", "paused"})
        done_cnt = statuses.count("done")
        err_cnt = sum(1 for s in statuses if s in {"error", "cancelled"})

        if hasattr(self, "tab_buttons"):
            if "recent" in self.tab_buttons:
                self.tab_buttons["recent"].setText(f"Gần đây ({recent_cnt})")
            self.tab_buttons["all"].setText(f"Tất cả ({total_cnt})")
            if "queued" in self.tab_buttons:
                self.tab_buttons["queued"].setText(f"Hàng chờ ({queued_cnt})")
            self.tab_buttons["active"].setText(f"Đang tải ({active_cnt})")
            self.tab_buttons["done"].setText(f"Hoàn tất ({done_cnt})")
            self.tab_buttons["error"].setText(f"Lỗi ({err_cnt})")

        if hasattr(self, "sidebar"):
            self.sidebar.set_downloads_badge(active_cnt + queued_cnt)

        running_cnt = sum(
            1 for jid in self.active
            if self.jobs_by_id.get(jid) and self.jobs_by_id[jid].status != "cancelled"
        )
        self.stats_label.setText(
            f"{running_cnt} đang tải · {queued_cnt} chờ · {done_cnt} hoàn tất"
            + (f" · {statuses.count('error')} lỗi" if statuses.count("error") else "")
        )
        self._update_queue_toggle_icon()
        self.apply_job_filters()

    def check_environment(self, show_dialog: bool = True) -> dict[str, bool | str]:
        report = environment_report()
        missing = [name for name in ("ffmpeg", "deno", "ejs") if not report[name]]
        if not show_dialog:
            if missing:
                self.log("Thiếu thành phần khuyến nghị: " + ", ".join(missing))
                if is_frozen() and (not report["ffmpeg"] or not report["deno"]):
                    QTimer.singleShot(800, lambda: self.ensure_runtime_tools_async(force=False))
            return report
        details = (
            f"Phiên bản ứng dụng: v{APP_VERSION} (Single-File Portable EXE)\n"
            f"yt-dlp: {report['yt_dlp_version']}\n"
            f"FFmpeg: {report['ffmpeg'] or 'CHƯA CÓ'}\n"
            f"FFprobe: {report['ffprobe'] or 'CHƯA CÓ'}\n"
            f"Deno: {report['deno'] or 'CHƯA CÓ'}\n"
            f"yt-dlp-ejs: {'Đã cài' if report['ejs'] else 'CHƯA CÓ'}\n\n"
            f"Thư mục dữ liệu ứng dụng: {app_data_dir()}"
        )
        QMessageBox.information(self, "Kiểm tra môi trường", details)
        return report

    def ensure_runtime_tools_async(self, force: bool = False) -> None:
        if getattr(self, "_bootstrapping_runtime", False):
            return
        self._bootstrapping_runtime = True
        self.log("Đang kiểm tra / tự động cài đặt công cụ nền (FFmpeg & Deno)...")
        self.statusBar().showMessage("Đang tải công cụ nền FFmpeg & Deno...", 10000)
        worker = RuntimeBootstrapWorker(force=force)

        def on_prog(msg: str) -> None:
            self.statusBar().showMessage(str(msg), 5000)
            if hasattr(self, "upd_status_lbl"):
                self.upd_status_lbl.setText(str(msg))
            if hasattr(self, "upd_pbar"):
                self.upd_pbar.setVisible(True)
                self.upd_pbar.setRange(0, 0)

        def on_done(ok: bool, msg: str) -> None:
            self._bootstrapping_runtime = False
            self.log(msg)
            self.statusBar().showMessage(msg, 8000)
            if hasattr(self, "upd_status_lbl"):
                self.upd_status_lbl.setText(msg)
            if hasattr(self, "upd_pbar"):
                self.upd_pbar.setVisible(False)
                self.upd_pbar.setRange(0, 100)
            if hasattr(self, "refresh_env_panel"):
                self.refresh_env_panel()

        worker.signals.progress.connect(on_prog)
        worker.signals.finished.connect(on_done)
        self.analyze_pool.start(worker)

    def _pick_dir_into(self, line_edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu tải xuống", line_edit.text())
        if folder:
            line_edit.setText(folder)

    def browse_cookie(self, line_edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn cookies.txt", "", "Netscape cookies (*.txt);;All files (*)"
        )
        if path:
            line_edit.setText(path)
            self.on_cookie_edited()

    def schedule_save(self, *args) -> None:
        if hasattr(self, "save_timer") and not self.save_timer.isActive():
            self.save_timer.start()

    def save_all(self) -> None:
        self.settings.download_dir = self.folder_edit.text().strip() or self.settings.download_dir
        self.settings.last_quality = self.quality_combo.currentData() or "best"
        self.settings.default_video_codec = self.codec_combo.currentData() or "h264"
        self.settings.default_audio_bitrate = self.audio_bitrate_combo.currentData() or "192"
        if hasattr(self, "browser_cookie_combo"):
            self.settings.cookies_from_browser = str(self.browser_cookie_combo.currentData() or "")
        self.settings.last_geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        try:
            self.storage.save_settings(self.settings)
            if self.settings.keep_history:
                self.storage.save_jobs(self.jobs)
            else:
                self.storage.save_jobs([
                    j for j in self.jobs
                    if j.status in {"queued", "downloading", "paused", "processing", "converting"}
                ])
        except OSError as exc:
            self.statusBar().showMessage(f"Không ghi được cấu hình: {exc}", 7000)

    def trigger_update_and_close(self, script_path: Path) -> None:
        """Store pending update script, cancel any running downloads without a second prompt,
        and close the window so `launch_staged_updater` runs right as the process exits.
        """
        self._pending_update_script = Path(script_path)
        if self.active:
            self.closing_after_cancel = True
            self.queue_running = False
            for _worker, control in self.active.values():
                control.cancel()
            self.statusBar().showMessage("Đang dừng các tác vụ để nâng cấp phiên bản mới...")
            return
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.active:
            if not self.closing_after_cancel:
                if getattr(self, "_pending_update_script", None) is not None:
                    self.closing_after_cancel = True
                    self.queue_running = False
                    for _worker, control in self.active.values():
                        control.cancel()
                    self.statusBar().showMessage("Đang dừng các tác vụ để nâng cấp phiên bản mới...")
                    event.ignore()
                    return
                choice = QMessageBox.question(
                    self,
                    "Tác vụ đang chạy",
                    "Vẫn còn tác vụ tải xuống hoặc chuyển đổi Codec. Hủy những tác vụ này và đóng ứng dụng?\n"
                    "File đang tải dở có thể được tiếp tục khi tải lại.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if choice != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
                self.closing_after_cancel = True
                self.queue_running = False
                for _worker, control in self.active.values():
                    control.cancel()
                self.statusBar().showMessage("Đang dừng các tác vụ đang chạy...")
            event.ignore()
            return
        self.telemetry_timer.stop()
        self.analyze_pool.clear()
        self.download_pool.clear()
        self.analyze_pool.waitForDone(2500)
        if self.tray_icon is not None:
            self.tray_icon.hide()
        self.save_timer.stop()
        self.save_all()
        pending_upd = getattr(self, "_pending_update_script", None)
        if pending_upd is not None:
            self._pending_update_script = None
            from ..updater import launch_staged_updater
            launch_staged_updater(pending_upd)
        event.accept()
