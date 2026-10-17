"""Minimal list-row widget for a single download job with hover-revealed actions."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .common import icon_button
from .. import icons
from ...engine import CODEC_LABELS
from ...models import Job
from ...theme import progress_bar_qss, status_badge_qss, theme_manager

STATUS_TEXT: dict[str, str] = {
    "queued": "Chờ tải",
    "downloading": "Đang tải",
    "paused": "Tạm dừng",
    "processing": "Đang xử lý",
    "converting": "Đổi codec",
    "done": "Hoàn tất",
    "error": "Lỗi",
    "cancelled": "Đã hủy",
}


class JobRow(QFrame):
    """Flat list row inside the unified jobs container; reveals action icons on hover."""

    pause_requested = pyqtSignal(str)
    resume_requested = pyqtSignal(str)
    cancel_requested = pyqtSignal(str)
    retry_requested = pyqtSignal(str)
    remove_requested = pyqtSignal(str)
    play_requested = pyqtSignal(str)
    folder_requested = pyqtSignal(str)
    transcode_requested = pyqtSignal(str)

    def __init__(self, job: Job, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.job_id = job.job_id
        self._job_snapshot: Job = job
        self._raw_title: str = job.title or job.url
        self._last_status: str = ""
        self._hovered: bool = False
        self._has_custom_thumb: bool = False

        self.setObjectName("jobRow")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 11, 12, 11)
        outer.setSpacing(14)

        # 1. Left 16:9 thumbnail (96x54)
        self.thumb_label = QLabel()
        self.thumb_label.setObjectName("cardThumbnail")
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setFixedSize(96, 54)
        outer.addWidget(self.thumb_label)

        # 2. Middle column: Title + status dot on row 1, metadata + detail on row 2, thin progress bar on row 3
        mid = QVBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(10)

        self.title_label = QLabel()
        self.title_label.setObjectName("cardTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top_row.addWidget(self.title_label, 1)

        self.status_badge = QLabel()
        top_row.addWidget(self.status_badge)
        mid.addLayout(top_row)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(6)

        self.spec_badge = QLabel()
        self.spec_badge.setObjectName("mutedLabel")
        meta_row.addWidget(self.spec_badge)

        # Keep codec_badge attribute for compatibility
        self.codec_badge = QLabel()
        self.codec_badge.setObjectName("mutedLabel")
        self.codec_badge.setVisible(False)

        self.sep_dot = QLabel("·")
        self.sep_dot.setObjectName("mutedLabel")
        meta_row.addWidget(self.sep_dot)

        self.detail_label = QLabel()
        self.detail_label.setObjectName("mutedLabel")
        self.detail_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        meta_row.addWidget(self.detail_label, 1)
        mid.addLayout(meta_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        mid.addWidget(self.progress_bar)

        outer.addLayout(mid, 1)

        # 3. Fixed-width right action slot so hovering never shifts layout
        self.actions_slot = QWidget(self)
        self.actions_slot.setFixedWidth(104)
        slot_layout = QHBoxLayout(self.actions_slot)
        slot_layout.setContentsMargins(0, 0, 0, 0)
        slot_layout.setSpacing(4)
        slot_layout.addStretch(1)

        self.actions_container = QWidget(self.actions_slot)
        act_layout = QHBoxLayout(self.actions_container)
        act_layout.setContentsMargins(0, 0, 0, 0)
        act_layout.setSpacing(3)

        self.btn_pause = icon_button(
            "pause",
            lambda: self.pause_requested.emit(self.job_id),
            "Tạm dừng",
        )
        self.btn_resume = icon_button(
            "play",
            lambda: self.resume_requested.emit(self.job_id),
            "Tiếp tục tải",
        )
        self.btn_cancel = icon_button(
            "x",
            lambda: self.cancel_requested.emit(self.job_id),
            "Hủy tác vụ",
            danger=True,
        )
        self.btn_play = icon_button(
            "play",
            lambda: self.play_requested.emit(self.job_id),
            "Phát media",
        )
        self.btn_folder = icon_button(
            "folder-open",
            lambda: self.folder_requested.emit(self.job_id),
            "Mở thư mục chứa file",
        )
        self.btn_transcode = icon_button(
            "repeat-2",
            lambda: self.transcode_requested.emit(self.job_id),
            "Đổi Codec video (FFmpeg)",
        )
        self.btn_retry = icon_button(
            "rotate-cw",
            lambda: self.retry_requested.emit(self.job_id),
            "Tải lại",
        )
        self.btn_remove = icon_button(
            "trash-2",
            lambda: self.remove_requested.emit(self.job_id),
            "Xóa khỏi danh sách",
            danger=True,
        )
        self.btn_more = icon_button(
            "ellipsis",
            self._open_more_menu,
            "Thao tác khác",
        )

        for b in (
            self.btn_pause,
            self.btn_resume,
            self.btn_play,
            self.btn_folder,
            self.btn_retry,
            self.btn_cancel,
            self.btn_remove,
            self.btn_transcode,
            self.btn_more,
        ):
            act_layout.addWidget(b)

        slot_layout.addWidget(self.actions_container)
        outer.addWidget(self.actions_slot)

        self.actions_container.setVisible(False)
        theme_manager().changed.connect(self._on_theme_changed)
        self.update_from_job(job)

    # ------------------------------------------------------------------
    # Hover & Context Menu
    # ------------------------------------------------------------------
    def set_hovered(self, hovered: bool) -> None:
        self._hovered = bool(hovered)
        self.actions_container.setVisible(self._hovered)

    def is_hovered(self) -> bool:
        return self._hovered

    def enterEvent(self, event) -> None:
        self.set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.set_hovered(False)
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        self.set_hovered(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        if not self.underMouse():
            self.set_hovered(False)
        super().focusOutEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide_title()

    def _elide_title(self) -> None:
        avail = max(180, self.width() - 280)
        fm = QFontMetrics(self.title_label.font())
        self.title_label.setText(fm.elidedText(self._raw_title, Qt.TextElideMode.ElideRight, avail))

    def _open_more_menu(self) -> None:
        pos = self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height() + 2))
        self._build_menu().exec(pos)

    def _show_context_menu(self, pos: QPoint) -> None:
        self._build_menu().exec(self.mapToGlobal(pos))

    def _build_menu(self) -> QMenu:
        job = self._job_snapshot
        status = job.status
        menu = QMenu(self)

        is_running = status in {"downloading", "processing", "converting"}
        is_paused = status == "paused"
        is_queued = status == "queued"
        is_done = status == "done"
        is_retryable = status in {"done", "error", "cancelled"}
        is_removable = status not in {"downloading", "processing", "converting", "paused"}

        if is_done and job.filepath:
            act_play = menu.addAction(icons.icon("play", size=14), "Phát tập tin")
            act_play.triggered.connect(lambda: self.play_requested.emit(self.job_id))
        if is_done:
            act_folder = menu.addAction(icons.icon("folder-open", size=14), "Mở thư mục chứa file")
            act_folder.triggered.connect(lambda: self.folder_requested.emit(self.job_id))
        if is_done and job.mode == "video" and job.filepath:
            act_tc = menu.addAction(icons.icon("repeat-2", size=14), "Đổi Codec video (FFmpeg)...")
            act_tc.triggered.connect(lambda: self.transcode_requested.emit(self.job_id))

        if is_running:
            act_pause = menu.addAction(icons.icon("pause", size=14), "Tạm dừng")
            act_pause.triggered.connect(lambda: self.pause_requested.emit(self.job_id))
        if is_paused:
            act_resume = menu.addAction(icons.icon("play", size=14), "Tiếp tục tải")
            act_resume.triggered.connect(lambda: self.resume_requested.emit(self.job_id))
        if is_retryable:
            act_retry = menu.addAction(icons.icon("rotate-cw", size=14), "Tải lại từ đầu")
            act_retry.triggered.connect(lambda: self.retry_requested.emit(self.job_id))

        if status == "error" and job.error:
            act_err = menu.addAction(icons.icon("circle-alert", size=14), "Xem chi tiết lỗi...")
            act_err.triggered.connect(
                lambda: QMessageBox.information(self, "Chi tiết lỗi", job.error)
            )

        menu.addSeparator()
        act_copy = menu.addAction(icons.icon("link", size=14), "Sao chép liên kết YouTube")
        act_copy.triggered.connect(lambda: QApplication.clipboard().setText(job.url))

        if is_running or is_paused or is_queued:
            menu.addSeparator()
            act_cancel = menu.addAction(icons.icon("x", size=14), "Hủy tác vụ")
            act_cancel.triggered.connect(lambda: self.cancel_requested.emit(self.job_id))
        if is_removable:
            act_rm = menu.addAction(icons.icon("trash-2", size=14), "Xóa khỏi danh sách")
            act_rm.triggered.connect(lambda: self.remove_requested.emit(self.job_id))

        return menu

    # ------------------------------------------------------------------
    # Thumbnail & Job State Painting
    # ------------------------------------------------------------------
    def set_thumbnail_pixmap(self, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        self._has_custom_thumb = True
        w, h = self.thumb_label.width(), self.thumb_label.height()
        scaled = pixmap.scaled(
            w,
            h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        cropped = scaled.copy(max(0, (scaled.width() - w) // 2), max(0, (scaled.height() - h) // 2), w, h)
        rounded = QPixmap(w, h)
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(w), float(h), 6.0, 6.0)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, cropped)
        painter.end()
        self.thumb_label.setPixmap(rounded)

    def _render_placeholder_thumb(self, mode: str) -> None:
        if self._has_custom_thumb:
            return
        t = theme_manager().tokens
        ic_name = "music" if mode == "audio" else "video"
        self.thumb_label.setPixmap(icons.render_svg_pixmap(ic_name, t["muted"], size=20, dpr=2.0))

    def _on_theme_changed(self, *_args) -> None:
        self._last_status = ""
        self._render_placeholder_thumb(self._job_snapshot.mode)
        self.update_from_job(self._job_snapshot)

    def update_from_job(self, job: Job) -> None:
        self._job_snapshot = job
        self._render_placeholder_thumb(job.mode)

        self._raw_title = job.title or job.url
        self._elide_title()
        self.title_label.setToolTip(f"{job.title}\n{job.url}")

        ext_str = "GỐC" if job.container == "original" else job.container.upper()
        if job.format_id:
            qual_str = f"ID {job.format_id}"
        elif job.mode == "video":
            qual_str = "Tốt nhất" if job.quality == "best" else f"{job.quality}p"
        else:
            qual_str = f"{job.audio_bitrate} kbps" if job.container in ("mp3", "m4a") else "Lossless"

        spec_parts = [ext_str, qual_str]
        if job.mode == "video":
            codec_disp = job.detected_codec or CODEC_LABELS.get(job.video_codec, job.video_codec.upper())
            spec_parts.append(codec_disp)
            self.codec_badge.setText(codec_disp)
        if job.clip_start or job.clip_end:
            spec_parts.append(f"{job.clip_start or '00:00'}–{job.clip_end or 'end'}")
        if job.subtitles:
            spec_parts.append("CC")
        self.spec_badge.setText(" · ".join(spec_parts))

        status = job.status
        mode = theme_manager().mode
        t = theme_manager().tokens
        self.status_badge.setText(f"● {STATUS_TEXT.get(status, status)}")
        if status != self._last_status:
            self.status_badge.setStyleSheet(status_badge_qss(status, mode))
            self.progress_bar.setStyleSheet(progress_bar_qss(status, mode))
            self._last_status = status

        pct = max(0.0, min(100.0, float(job.progress)))
        self.progress_bar.setValue(round(pct * 10))
        self.progress_bar.setVisible(status != "done")

        if status == "downloading":
            parts = [f"{pct:.1f}%"]
            if job.speed and job.speed != "—":
                parts.append(job.speed)
            if job.eta and job.eta != "—":
                parts.append(f"còn {job.eta}")
            if job.size and job.size != "—":
                parts.append(job.size)
            detail = " · ".join(parts)
            self.detail_label.setStyleSheet(f"QLabel {{ color: {t['text_secondary']}; font-size: 12px; }}")
        elif status == "converting":
            parts = [f"{pct:.1f}%", job.speed or "Đang chuyển đổi Codec bằng FFmpeg"]
            if job.eta and job.eta != "—":
                parts.append(f"còn {job.eta}")
            detail = " · ".join(parts)
            self.detail_label.setStyleSheet(f"QLabel {{ color: {t['purple']}; font-size: 12px; font-weight: 500; }}")
        elif status == "processing":
            detail = "Đang ghép luồng và nhúng metadata bằng FFmpeg..."
            self.detail_label.setStyleSheet(f"QLabel {{ color: {t['purple']}; font-size: 12px; font-weight: 500; }}")
        elif status == "paused":
            detail = f"Đã tạm dừng ở {pct:.1f}%"
            self.detail_label.setStyleSheet(f"QLabel {{ color: {t['warning']}; font-size: 12px; }}")
        elif status == "done":
            detail = job.filepath or f"Đã lưu tại {job.directory}"
            self.detail_label.setStyleSheet(f"QLabel {{ color: {t['muted']}; font-size: 12px; }}")
        elif status == "error":
            detail = job.error or "Đã xảy ra lỗi trong quá trình tải."
            self.detail_label.setStyleSheet(f"QLabel {{ color: {t['danger']}; font-size: 12px; font-weight: 500; }}")
        elif status == "cancelled":
            detail = "Đã hủy"
            self.detail_label.setStyleSheet(f"QLabel {{ color: {t['muted']}; font-size: 12px; }}")
        else:
            detail = f"Đang chờ · Lưu vào {job.directory}"
            self.detail_label.setStyleSheet(f"QLabel {{ color: {t['muted']}; font-size: 12px; }}")

        full_detail = detail
        if len(detail) > 84:
            detail = detail[:81] + "…"
        self.detail_label.setText(detail)
        self.detail_label.setToolTip(full_detail)

        is_running = status in {"downloading", "processing", "converting"}
        is_paused = status == "paused"
        is_queued = status == "queued"
        is_done = status == "done"
        is_retryable = status in {"done", "error", "cancelled"}
        is_removable = status not in {"downloading", "processing", "converting", "paused"}

        # Quick hover buttons (at most 2 primary icons + '⋯' menu)
        self.btn_pause.setVisible(is_running)
        self.btn_resume.setVisible(is_paused)
        self.btn_cancel.setVisible(is_running or is_paused or is_queued)
        self.btn_play.setVisible(is_done and bool(job.filepath))
        self.btn_folder.setVisible(is_done)
        self.btn_retry.setVisible(status in {"error", "cancelled"})
        self.btn_remove.setVisible(status in {"error", "cancelled", "queued"})
        # Transcode remains accessible from the '⋯' menu and right-click menu, plus attribute exposed
        self.btn_transcode.setVisible(False)
        self.btn_transcode.setEnabled(is_done and job.mode == "video" and bool(job.filepath))
        self.btn_more.setVisible(True)
