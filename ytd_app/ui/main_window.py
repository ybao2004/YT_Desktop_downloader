"""Main application window coordinating sidebar navigation, pages, workers, and queue execution."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PyQt6.QtCore import QByteArray, QSize, Qt, QThreadPool, QTimer, QUrl
from PyQt6.QtGui import QCloseEvent, QDesktopServices, QPixmap
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
    QStackedWidget,
    QStyle,
    QSystemTrayIcon,
    QTableWidgetItem,
    QWidget,
)

from . import icons
from .app import load_bundled_fonts
from .pages import (
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
    extract_youtube_video_id,
    is_youtube_url,
    parse_timestamp_seconds,
)
from ..hw_monitor import HardwareMonitor, HardwareProfile, format_rate
from ..models import Job, Settings, timestamp
from ..storage import Storage
from ..theme import build_palette, build_stylesheet, theme_manager, tokens_for
from ..updater import UpdateInfo
from ..version import APP_VERSION, app_data_dir, default_download_dir
from ..workers import (
    AnalyzeWorker,
    DownloadControl,
    DownloadWorker,
    HardwareProfileWorker,
    TranscodeWorker,
    UpdateCheckWorker,
)

JobCardWidget = JobRow


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        load_bundled_fonts()

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
        self.current_filter = "all"

        self.hw_monitor = HardwareMonitor()
        self.hw_profile: HardwareProfile | None = None

        self.network = QNetworkAccessManager(self)
        self.thumbnail_reply = None
        self.pending_thumbnail = ""

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

        if self.settings.last_geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(self.settings.last_geometry.encode("ascii")))
                if self.width() < 980:
                    self.resize(1240, max(self.height(), 760))
            except (ValueError, TypeError):
                pass

        for job in self.jobs:
            self.insert_job_row(job)

        self.refresh_stats()
        self.check_environment(show_dialog=False)
        self.start_hardware_monitoring()

        if self.settings.auto_check_updates:
            QTimer.singleShot(2500, lambda: self.check_remote_update_silent())

        self.statusBar().showMessage(
            f"Sẵn sàng · Mặc định Codec {CODEC_LABELS.get(self.settings.default_video_codec, 'H.264')}"
        )

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

        self.workspace_stack.addWidget(page_downloads)  # 0
        self.workspace_stack.addWidget(page_log)        # 1
        self.workspace_stack.addWidget(page_hardware)   # 2
        self.workspace_stack.addWidget(page_guide)      # 3
        self.workspace_stack.addWidget(page_settings)   # 4

        # Status Bar: summary + subtle telemetry text items
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

    def paste_from_clipboard(self) -> None:
        text = QApplication.clipboard().text().strip()
        if not text:
            self.statusBar().showMessage("Clipboard hiện đang trống.", 4000)
            return
        self.url_edit.setText(text)
        if is_youtube_url(text):
            self.link_status.setText("Đã dán URL hợp lệ")
            if not self.quick_download_check.isChecked():
                self.start_analysis()
        else:
            self.link_status.setText("Nội dung vừa dán chưa phải URL YouTube")

    def on_url_enter_pressed(self) -> None:
        if self.quick_download_check.isChecked():
            self.on_primary_download_clicked()
        else:
            self.start_analysis()

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
        self.schedule_save()

    def on_audio_bitrate_changed(self) -> None:
        self.settings.default_audio_bitrate = self.audio_bitrate_combo.currentData() or "192"
        self.schedule_save()

    def on_more_options_toggled(self, checked: bool) -> None:
        self.extra_options_frame.setVisible(checked)
        self.more_options_btn.setText("Tùy chọn ▴" if checked else "Tùy chọn ▾")

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
        self.schedule_save()

    def on_ext_changed(self) -> None:
        if self.mode_combo.currentData() == "video":
            self.settings.default_video_ext = self.ext_combo.currentData()
        else:
            self.settings.default_audio_ext = self.ext_combo.currentData()
        self.schedule_save()

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
    def start_analysis(self, *args, add_after: bool = False) -> None:
        url = self.url_edit.text().strip()
        if not is_youtube_url(url):
            QMessageBox.warning(self, "URL không hợp lệ", "Vui lòng dán liên kết YouTube hợp lệ.")
            return
        self.pending_add = add_after
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
            self.pending_add = False
            self.add_from_preview()

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

    def fetch_thumbnail(self, url: str, target_job_id: str = "") -> None:
        if not url.startswith("https://"):
            if not target_job_id:
                self.preview_image.setText("Không có ảnh")
            return
        if url in self.thumb_cache:
            pix = self.thumb_cache[url]
            if not target_job_id:
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

        if not target_job_id:
            self.pending_thumbnail = url
        reply = self.network.get(QNetworkRequest(QUrl(url)))
        reply.finished.connect(lambda r=reply, u=url, jid=target_job_id: self.thumbnail_finished(r, u, jid))
        self.thumbnail_reply = reply

    def thumbnail_finished(self, reply, url: str, target_job_id: str = "") -> None:
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                image_data = bytes(reply.readAll())
                if len(image_data) < 3_500_000:
                    pixmap = QPixmap()
                    if pixmap.loadFromData(image_data):
                        self.thumb_cache[url] = pixmap
                        if url == self.pending_thumbnail:
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
            if url == self.pending_thumbnail and not target_job_id:
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
        if not is_youtube_url(url):
            QMessageBox.warning(self, "URL không hợp lệ", "Vui lòng dán liên kết YouTube hợp lệ.")
            return

        playlist = self.playlist_check.isChecked()
        has_matching_preview = (
            self.preview is not None
            and url == self.preview_url
            and playlist == self.preview_playlist
        )

        if has_matching_preview:
            self.add_from_preview()
            return

        if self.quick_download_check.isChecked() and not playlist and "list=" not in url.lower():
            self.add_quick_single_job(url)
        else:
            self.start_analysis(add_after=True)

    def _jobs_collide(self, job_a: Job, job_b: Job) -> bool:
        if Path(job_a.directory).resolve() != Path(job_b.directory).resolve():
            return False
        vid_a = extract_youtube_video_id(job_a.url)
        vid_b = extract_youtube_video_id(job_b.url)
        if vid_a and vid_b:
            return vid_a == vid_b
        return job_a.url.strip() == job_b.url.strip()

    def add_quick_single_job(self, url: str) -> None:
        directory = self.folder_edit.text().strip()
        if not directory:
            QMessageBox.warning(self, "Chưa chọn thư mục", "Chọn thư mục lưu trước khi tải xuống.")
            return
        clip_pair = self._validate_clip_inputs()
        if clip_pair is None:
            return
        c_start, c_end = clip_pair

        mode = self.mode_combo.currentData()
        ext = self.ext_combo.currentData()
        quality = str(self.quality_combo.currentData())
        v_codec = str(self.codec_combo.currentData() or "h264")
        a_bitrate = str(self.audio_bitrate_combo.currentData() or "192")

        job = Job(
            url=url,
            title=f"Đang lấy thông tin video... ({url})",
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
        )

        for existing in self.jobs:
            if existing.status in {"queued", "downloading", "processing", "converting", "paused"}:
                if (
                    self._jobs_collide(existing, job)
                    and existing.mode == job.mode
                    and existing.container == job.container
                    and existing.clip_start == job.clip_start
                    and existing.clip_end == job.clip_end
                ):
                    self.statusBar().showMessage("Video này đã có trong hàng đợi đang tải.", 5000)
                    return

        self.jobs.append(job)
        self.jobs_by_id[job.job_id] = job
        self.insert_job_row(job)
        self.log(f"Tải nhanh 1-click ({CODEC_LABELS.get(v_codec, v_codec)}): {url}")
        self.statusBar().showMessage("Đã thêm vào hàng đợi và bắt đầu tải ngay.", 5000)
        self.start_queue()
        self.schedule_save()

    def add_from_preview(self) -> None:
        url = self.url_edit.text().strip()
        playlist = self.playlist_check.isChecked()
        if not self.preview or url != self.preview_url or playlist != self.preview_playlist:
            self.start_analysis(add_after=True)
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
            )
            self.jobs.append(job)
            self.jobs_by_id[job.job_id] = job
            self.insert_job_row(job)
            if thumb_u:
                self.fetch_thumbnail(thumb_u, job.job_id)
            count += 1

        self.log(f"Đã thêm {count} mục vào hàng đợi (Codec mục tiêu: {CODEC_LABELS.get(v_codec, v_codec)}).")
        self.statusBar().showMessage(f"Đã thêm {count} tác vụ và tự động bắt đầu tải.", 6000)
        self.start_queue()
        self.schedule_save()

    # ------------------------------------------------------------------
    # Row List Management, Navigation & Filtering
    # ------------------------------------------------------------------
    def insert_job_row(self, job: Job) -> None:
        row = self.job_table.rowCount()
        self.job_table.insertRow(row)
        self.rows[job.job_id] = row
        for col in range(8):
            self.job_table.setItem(row, col, QTableWidgetItem(""))

        card = JobRow(job, self.cards_container)
        card.pause_requested.connect(self.pause_job_by_id)
        card.resume_requested.connect(self.resume_job_by_id)
        card.cancel_requested.connect(self.cancel_job_by_id)
        card.retry_requested.connect(self.retry_job_by_id)
        card.remove_requested.connect(self.remove_job_by_id)
        card.play_requested.connect(self.play_job_file_by_id)
        card.folder_requested.connect(self.open_job_folder_by_id)
        card.transcode_requested.connect(self.prompt_transcode_job_by_id)

        if job.thumbnail_url and job.thumbnail_url in self.thumb_cache:
            card.set_thumbnail_pixmap(self.thumb_cache[job.thumbnail_url])

        self.job_cards[job.job_id] = card
        self.cards_layout.insertWidget(0, card)
        self.paint_job(job)
        self.apply_job_filters()

    def paint_job(self, job: Job) -> None:
        card = self.job_cards.get(job.job_id)
        if card is not None:
            card.update_from_job(job)

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
            filter_key = "all" if tab_key == "downloads" else tab_key
            if filter_key in self.tab_buttons:
                self.current_filter = filter_key
                btn = self.tab_buttons[filter_key]
                btn.blockSignals(True)
                btn.setChecked(True)
                btn.blockSignals(False)
            self.workspace_stack.setCurrentIndex(0)
            self.sidebar.set_active_page("downloads")
            self.apply_job_filters()

    def job_matches_filter(self, job: Job, filter_key: str, query: str) -> bool:
        if filter_key == "active" and job.status not in {"queued", "downloading", "processing", "converting", "paused"}:
            return False
        if filter_key == "done" and job.status != "done":
            return False
        if filter_key == "error" and job.status not in {"error", "cancelled"}:
            return False
        if query:
            haystack = f"{job.title} {job.url} {job.container} {job.video_codec} {job.detected_codec} {job.status}".lower()
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

        if hasattr(self, "empty_state_frame"):
            self.empty_state_frame.setVisible(visible_count == 0)
            if not self.jobs:
                self.empty_title_label.setText("Chưa có tác vụ tải xuống nào")
                self.empty_sub_label.setText(
                    "Dán liên kết YouTube ở khung phía trên và bấm 'Tải xuống'."
                )
            elif visible_count == 0:
                self.empty_title_label.setText("Không có mục nào khớp với bộ lọc hiện tại")
                self.empty_sub_label.setText("Hãy chuyển sang bộ lọc 'Tất cả' hoặc xóa từ khóa tìm kiếm.")

    # ------------------------------------------------------------------
    # Single-Row & On-Demand Transcode Actions
    # ------------------------------------------------------------------
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

    def start_transcode_job(self, job: Job, target_codec: str) -> None:
        if job.job_id in self.active:
            return
        control = DownloadControl()
        worker = TranscodeWorker(job, target_codec, self.settings_snapshot(), control)
        worker.signals.progress.connect(self.download_progress)
        worker.signals.message.connect(self.download_message)
        worker.signals.complete.connect(self.download_complete)
        self.active[job.job_id] = (worker, control)
        job.video_codec = target_codec
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
        if job and job_id in self.active and job.status == "paused":
            self.active[job_id][1].resume()
            job.status = getattr(job, "_pre_pause_status", "downloading")
            self.paint_job(job)
            self.refresh_stats()
            self.schedule_save()

    def cancel_job_by_id(self, job_id: str) -> None:
        job = self.jobs_by_id.get(job_id)
        if not job:
            return
        if job_id in self.active:
            self.active[job_id][1].cancel()
            job.status = "cancelled"
        elif job.status == "queued":
            job.status = "cancelled"
        job.speed = ""
        job.eta = ""
        job.updated_at = timestamp()
        self.paint_job(job)
        self.refresh_stats()
        self.schedule_save()

    def retry_job_by_id(self, job_id: str) -> None:
        job = self.jobs_by_id.get(job_id)
        if not job:
            return
        if job_id in self.active:
            self.statusBar().showMessage("Tác vụ đang kết thúc hủy, vui lòng thử lại sau giây lát...", 3000)
            return
        if job.status in {"done", "error", "cancelled"}:
            job.status = "queued"
            job.progress = 0.0
            job.speed = ""
            job.eta = ""
            job.error = ""
            job.filepath = ""
            self.paint_job(job)
            self.start_queue()
            self.schedule_save()

    def remove_job_by_id(self, job_id: str) -> None:
        if job_id in self.active:
            self.statusBar().showMessage("Không thể xóa tác vụ đang chạy; hãy bấm Hủy trước.", 5000)
            return
        self.jobs = [j for j in self.jobs if j.job_id != job_id]
        self.jobs_by_id.pop(job_id, None)
        card = self.job_cards.pop(job_id, None)
        if card is not None:
            card.setParent(None)
            card.deleteLater()
        self._rebuild_legacy_rows()
        self.refresh_stats()
        self.schedule_save()

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
        if count:
            self.statusBar().showMessage(f"Đã tiếp tục {count} tác vụ.", 4000)
        if not self.queue_running and any(j.status == "queued" for j in self.jobs):
            self.start_queue()
        else:
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
        removable = {
            j.job_id
            for j in self.jobs
            if j.job_id not in self.active and j.status in {"done", "cancelled"}
        }
        if not removable:
            self.statusBar().showMessage("Không có mục hoàn tất/đã hủy nào để xóa.", 4000)
            return
        self.jobs = [j for j in self.jobs if j.job_id not in removable]
        for ident in removable:
            self.jobs_by_id.pop(ident, None)
            card = self.job_cards.pop(ident, None)
            if card is not None:
                card.setParent(None)
                card.deleteLater()
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
        if self.queue_running:
            self.stop_queue()
        else:
            self.start_queue()

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
        if data.get("thumbnail_url") and not job.thumbnail_url:
            job.thumbnail_url = str(data["thumbnail_url"])
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

    def download_complete(self, job_id: str, status: str, value: str) -> None:
        self.active.pop(job_id, None)
        job = self.jobs_by_id.get(job_id)
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
            self.paint_job(job)
            self.log(f"{STATUS_TEXT[status]}: {job.title}" + (f" | {value}" if status == "error" else ""))

        self.refresh_stats()
        self.schedule_save()

        if self.closing_after_cancel and not self.active:
            self.save_all()
            QTimer.singleShot(0, self.close)
            return

        self.schedule_next()

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
        if not self.settings.update_manifest_url:
            return
        worker = UpdateCheckWorker(self.settings.update_manifest_url)
        worker.signals.checked.connect(self._on_silent_update_checked)
        self.analyze_pool.start(worker)

    def _on_silent_update_checked(self, info: UpdateInfo) -> None:
        if info.has_update:
            self.sidebar.set_update_badge(info.latest_version)
            self.statusBar().showMessage(
                f"Phát hiện phiên bản mới v{info.latest_version}! Mở mục 'Cài đặt' ở thanh bên để nâng cấp.",
                10000,
            )

    def open_updater_dialog(self) -> None:
        self.switch_workspace_tab("settings")

    def open_settings(self, initial_tab: int = 0) -> None:
        if isinstance(initial_tab, bool):
            initial_tab = 0
        self.switch_workspace_tab("guide" if initial_tab == 2 else "settings")

    def on_theme_preference_changed(self) -> None:
        pref = self.theme_segment.currentData() or "system"
        self.settings.theme_mode = str(pref)
        theme_manager().apply(self.settings.theme_mode)
        self.schedule_save()

    def on_folder_text_changed(self, text: str) -> None:
        if hasattr(self, "folder_chip"):
            self.folder_chip.set_path(text)

    def on_folder_edited(self) -> None:
        value = self.folder_edit.text().strip()
        if value:
            self.settings.download_dir = value
            if hasattr(self, "folder_chip"):
                self.folder_chip.set_path(value)
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

    def on_cookie_edited(self) -> None:
        self.settings.cookie_file = self.cookie_edit.text().strip()
        self.schedule_save()

    def clear_cookie_file(self) -> None:
        self.cookie_edit.clear()
        self.on_cookie_edited()

    def on_manifest_edited(self) -> None:
        self.settings.update_manifest_url = self.manifest_edit.text().strip()
        self.schedule_save()

    def on_system_flags_changed(self) -> None:
        self.settings.keep_history = self.keep_history_check.isChecked()
        self.settings.notify_on_complete = self.notify_check.isChecked()
        self.settings.auto_check_updates = self.auto_update_check.isChecked()
        self.schedule_save()

    def _update_queue_toggle_icon(self) -> None:
        if not hasattr(self, "start_btn"):
            return
        t = theme_manager().tokens
        ic_name = "pause" if self.queue_running else "play"
        self.start_btn.setProperty("lucideIcon", ic_name)
        self.start_btn.setIcon(icons.icon(ic_name, color=t["text_secondary"], size=15))
        self.start_btn.setIconSize(QSize(15, 15))
        self.start_btn.setToolTip(
            "Hàng đợi đang bật (bấm để tạm dừng nhận tác vụ mới)"
            if self.queue_running
            else "Bắt đầu chạy hàng đợi"
        )

    def refresh_stats(self) -> None:
        statuses = [j.status for j in self.jobs]
        total_cnt = len(statuses)
        queued_cnt = statuses.count("queued")
        active_cnt = sum(1 for s in statuses if s in {"queued", "downloading", "processing", "converting", "paused"})
        done_cnt = statuses.count("done")
        err_cnt = sum(1 for s in statuses if s in {"error", "cancelled"})

        if hasattr(self, "tab_buttons"):
            self.tab_buttons["all"].setText(f"Tất cả ({total_cnt})")
            self.tab_buttons["active"].setText(f"Đang tải ({active_cnt})")
            self.tab_buttons["done"].setText(f"Hoàn tất ({done_cnt})")
            self.tab_buttons["error"].setText(f"Lỗi ({err_cnt})")

        if hasattr(self, "sidebar"):
            self.sidebar.set_downloads_badge(active_cnt)

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

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.active:
            if not self.closing_after_cancel:
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
        event.accept()
