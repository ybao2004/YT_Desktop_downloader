"""Qt background tasks; all widget changes must happen in the main Qt thread."""
from __future__ import annotations

import threading
import time

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from .engine import DownloadCancelled, download_media, inspect_url, transcode_existing_job
from .hw_monitor import HardwareMonitor
from .updater import (
    UpdateInfo,
    check_for_updates,
    download_update_package,
    ensure_runtime_binaries,
    stage_portable_update,
    update_ytdlp_core,
)


class AnalyzeSignals(QObject):
    ready = pyqtSignal(str, object)
    failed = pyqtSignal(str, str)


class AnalyzeWorker(QRunnable):
    def __init__(
        self,
        key: str,
        url: str,
        playlist: bool,
        cookie_file: str = "",
        cookies_from_browser: str = "auto",
    ):
        super().__init__()
        self.key = key
        self.url = url
        self.playlist = playlist
        self.cookie_file = cookie_file
        self.cookies_from_browser = cookies_from_browser
        self.signals = AnalyzeSignals()

    def run(self):
        try:
            self.signals.ready.emit(
                self.key,
                inspect_url(
                    self.url,
                    self.playlist,
                    cookie_file=self.cookie_file,
                    cookies_from_browser=self.cookies_from_browser,
                ),
            )
        except Exception as exc:
            self.signals.failed.emit(self.key, str(exc))


class DownloadControl:
    def __init__(self):
        self.run_event = threading.Event()
        self.run_event.set()
        self.cancel_event = threading.Event()

    def pause(self):
        self.run_event.clear()

    def resume(self):
        self.run_event.set()

    def cancel(self):
        self.cancel_event.set()
        self.run_event.set()


class DownloadSignals(QObject):
    progress = pyqtSignal(str, object)
    message = pyqtSignal(str, str)
    complete = pyqtSignal(str, str, str)  # job_id, result: done/cancelled/error, filepath or error


class DownloadWorker(QRunnable):
    def __init__(self, job, settings, control):
        super().__init__()
        self.job = job
        self.settings = settings
        self.control = control
        self.signals = DownloadSignals()

    def run(self):
        last_emit = 0.0
        last_status = None
        seen_title = False
        seen_thumb = False

        def emit_progress(data):
            nonlocal last_emit, last_status, seen_title, seen_thumb
            current = time.monotonic()
            status = data.get("status")
            has_new_title = bool(data.get("title")) and not seen_title
            has_new_thumb = bool(data.get("thumbnail_url")) and not seen_thumb
            if (
                status != last_status
                or current - last_emit >= 0.18
                or "detected_codec" in data
                or has_new_title
                or has_new_thumb
            ):
                if data.get("title"):
                    seen_title = True
                if data.get("thumbnail_url"):
                    seen_thumb = True
                last_emit = current
                last_status = status
                self.signals.progress.emit(self.job.job_id, data)

        try:
            path = download_media(
                self.job,
                self.settings,
                self.control,
                emit_progress,
                lambda msg: self.signals.message.emit(self.job.job_id, str(msg)),
            )
            self.signals.complete.emit(self.job.job_id, "done", path)
        except DownloadCancelled:
            self.signals.complete.emit(self.job.job_id, "cancelled", "")
        except Exception as exc:
            if self.control.cancel_event.is_set():
                self.signals.complete.emit(self.job.job_id, "cancelled", "")
            else:
                self.signals.complete.emit(self.job.job_id, "error", str(exc))


class TranscodeWorker(QRunnable):
    """Converts an already downloaded job file to a target codec (e.g. h264, h265, av1, vp9)."""

    def __init__(self, job, target_codec: str, settings, control):
        super().__init__()
        self.job = job
        self.target_codec = target_codec
        self.settings = settings
        self.control = control
        self.signals = DownloadSignals()

    def run(self):
        last_emit = 0.0
        last_status = None

        def emit_progress(data):
            nonlocal last_emit, last_status
            current = time.monotonic()
            status = data.get("status")
            if status != last_status or current - last_emit >= 0.18 or "detected_codec" in data:
                last_emit = current
                last_status = status
                self.signals.progress.emit(self.job.job_id, data)

        try:
            out_path = transcode_existing_job(
                self.job,
                self.target_codec,
                self.settings,
                self.control,
                emit_progress,
                lambda msg: self.signals.message.emit(self.job.job_id, str(msg)),
            )
            self.signals.complete.emit(self.job.job_id, "done", out_path)
        except DownloadCancelled:
            self.signals.complete.emit(self.job.job_id, "cancelled", "")
        except Exception as exc:
            if self.control.cancel_event.is_set():
                self.signals.complete.emit(self.job.job_id, "cancelled", "")
            else:
                self.signals.complete.emit(self.job.job_id, "error", str(exc))


class HardwareProfileSignals(QObject):
    ready = pyqtSignal(object)


class HardwareProfileWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = HardwareProfileSignals()

    def run(self):
        mon = HardwareMonitor()
        profile = mon.build_profile(probe_encoders=True)
        self.signals.ready.emit(profile)


class UpdateSignals(QObject):
    checked = pyqtSignal(object)          # UpdateInfo
    failed = pyqtSignal(str)              # error message
    progress = pyqtSignal(float, str)     # percent, status message
    staged = pyqtSignal(str)              # path to apply_update.bat
    ytdlp_done = pyqtSignal(bool, str)


class UpdateCheckWorker(QRunnable):
    def __init__(self, custom_url: str = ""):
        super().__init__()
        self.custom_url = custom_url
        self.signals = UpdateSignals()

    def run(self):
        try:
            info = check_for_updates(self.custom_url)
            self.signals.checked.emit(info)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class UpdateDownloadWorker(QRunnable):
    def __init__(self, info: UpdateInfo):
        super().__init__()
        self.info = info
        self.signals = UpdateSignals()

    def run(self):
        try:
            pkg = download_update_package(
                self.info,
                lambda pct, msg: self.signals.progress.emit(pct, msg),
            )
            script = stage_portable_update(pkg)
            self.signals.staged.emit(str(script))
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class YtDlpUpdateWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = UpdateSignals()

    def run(self):
        ok, msg = update_ytdlp_core()
        self.signals.ytdlp_done.emit(ok, msg)


class RuntimeBootstrapSignals(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)


class RuntimeBootstrapWorker(QRunnable):
    def __init__(self, force: bool = False):
        super().__init__()
        self.force = force
        self.signals = RuntimeBootstrapSignals()

    def run(self):
        try:
            ok, msg = ensure_runtime_binaries(
                progress_cb=lambda m: self.signals.progress.emit(str(m)),
                force=self.force,
            )
            self.signals.finished.emit(ok, msg)
        except Exception as exc:
            self.signals.finished.emit(False, str(exc))

