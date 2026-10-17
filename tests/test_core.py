"""Offline tests for core behavior; no network or GUI needed."""
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

# Installed yt-dlp is used normally; a minimal replacement permits running offline
# core tests on a build machine before installing runtime dependencies.
try:
    import yt_dlp
except ModuleNotFoundError:
    fake = types.ModuleType("yt_dlp")
    fake.version = types.SimpleNamespace(__version__="stub")
    fake.YoutubeDL = object
    sys.modules["yt_dlp"] = fake

from ytd_app.engine import (
    _entry_url, build_format, find_output_file, friendly_eta, friendly_size,
    inspect_url, is_youtube_url, metadata_view,
)
from ytd_app.models import Job, Settings
from ytd_app.storage import Storage


class CoreTests(unittest.TestCase):
    def test_domain_validation(self):
        self.assertTrue(is_youtube_url("https://youtu.be/abcdefghijk"))
        self.assertTrue(is_youtube_url("https://music.youtube.com/watch?v=abcdefghijk"))
        for url in ("https://youtube.com.evil.com/watch?v=xx", "file:///etc/passwd",
                    "https://example.org", "javascript:alert(1)", ""):
            self.assertFalse(is_youtube_url(url))

    def test_format_video_mp4_limit(self):
        # Default video_codec is h264 -> prefers avc1 at target height, then falls back
        job = Job(url="https://youtu.be/abcdefghijk", container="mp4", quality="1080", video_codec="h264")
        fmt = build_format(job)
        self.assertIn("[vcodec^=avc1][height<=1080]", fmt)
        # When video_codec is 'auto', preserves classic format expression
        job_auto = Job(url="https://youtu.be/abcdefghijk", container="mp4", quality="1080", video_codec="auto")
        self.assertEqual(build_format(job_auto),
                         "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4][height<=1080]")

    def test_format_webm_and_mkv(self):
        job = Job(url="https://youtu.be/abcdefghijk", container="webm", quality="720", video_codec="auto")
        self.assertIn("[ext=webm]", build_format(job))
        job.container = "mkv"
        self.assertEqual(build_format(job), "bv*[height<=720]+ba/b[height<=720]")
        job_h265 = Job(url="https://youtu.be/abcdefghijk", container="mkv", quality="720", video_codec="h265")
        self.assertIn("[vcodec^=hev1][height<=720]", build_format(job_h265))

    def test_format_audio(self):
        job = Job(url="https://youtu.be/abcdefghijk", mode="audio", container="mp3")
        self.assertEqual(build_format(job), "bestaudio")

    def test_format_exact(self):
        job = Job(url="https://youtu.be/abcdefghijk", mode="video", container="mp4",
                  format_id="137", format_ext="mp4")
        self.assertEqual(build_format(job), "137+ba[ext=m4a]")
        job.format_id = "137/bad"
        with self.assertRaises(ValueError):
            build_format(job)

    def test_metadata(self):
        result = metadata_view({"title": "ABC", "formats": [
            {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 128},
            {"format_id": "137", "ext": "mp4", "vcodec": "avc1", "acodec": "none", "height": 1080},
        ]})
        self.assertEqual(len(result["formats"]), 2)
        self.assertFalse(result["formats"][0]["has_video"])
        self.assertFalse(result["formats"][1]["has_audio"])

    def test_entry(self):
        self.assertEqual(_entry_url({"id": "abcdefghijk"}), "https://www.youtube.com/watch?v=abcdefghijk")
        self.assertEqual(_entry_url({"url": "https://youtu.be/abcdefghijk"}), "https://youtu.be/abcdefghijk")
        self.assertEqual(_entry_url({"url": "https://evil.invalid", "id": "oops"}), "")

    def test_formatting_and_timestamps(self):
        from ytd_app.engine import parse_timestamp_seconds
        self.assertEqual(friendly_eta(75), "01:15")
        self.assertEqual(friendly_size(1024), "1.0 KB")
        self.assertEqual(parse_timestamp_seconds("01:30"), 90.0)
        self.assertEqual(parse_timestamp_seconds("01:02:03"), 3723.0)
        self.assertIsNone(parse_timestamp_seconds(""))
        with self.assertRaises(ValueError):
            parse_timestamp_seconds("bad:time")

    def test_storage_roundtrip_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Storage(Path(tmp))
            settings = Settings(max_concurrent=3, default_audio_ext="flac", default_video_codec="h265")
            store.save_settings(settings)
            restored = store.load_settings()
            self.assertEqual(restored.max_concurrent, 3)
            self.assertEqual(restored.default_audio_ext, "flac")
            self.assertEqual(restored.default_video_codec, "h265")
            job = Job(url="https://youtu.be/abcdefghijk", status="converting", progress=43, video_codec="h265")
            store.save_jobs([job])
            jobs = store.load_jobs()
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0].status, "queued")
            self.assertEqual(jobs[0].progress, 43)
            self.assertEqual(jobs[0].video_codec, "h265")

    def test_find_file_with_literal_brackets(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            target = folder / "Example [abcdefghijk].mp3"
            target.write_bytes(b"data")
            job = Job(url="https://youtu.be/abcdefghijk", mode="audio", container="mp3")
            self.assertEqual(find_output_file({"id": "abcdefghijk"}, folder, job), target)

    def test_find_file_original_title_without_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            target = folder / "Original Song Title.mp3"
            target.write_bytes(b"data")
            job = Job(url="https://youtu.be/abcdefghijk", mode="audio", container="mp3")
            self.assertEqual(find_output_file({"title": "Original Song Title"}, folder, job), target)

    def test_ensure_video_codec_skips_when_matching_and_converts_when_different(self):
        import threading
        from ytd_app.engine import ensure_video_codec
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "video.mp4"
            sample.write_bytes(b"dummy")
            job = Job(url="https://youtu.be/abcdefghijk", mode="video", container="mp4", video_codec="h264")
            ctrl = types.SimpleNamespace(cancel_event=threading.Event(), run_event=threading.Event())
            ctrl.run_event.set()

            # Case 1: Already h264 -> skips FFmpeg
            with patch("ytd_app.engine.probe_media_info", return_value={"video_codec": "h264", "audio_codec": "aac", "duration": 10.0}):
                out_path, label = ensure_video_codec(sample, job, Settings(), ctrl, lambda d: None, lambda m: None)
                self.assertEqual(out_path, sample)
                self.assertEqual(label, "H.264")

            # Case 2: Source is vp9, target is h265 -> invokes FFmpeg conversion
            job.video_codec = "h265"
            def fake_exec(cmd, dur, stage, control, prog, temp_file):
                temp_file.write_bytes(b"hevc_converted")
                prog({"status": "converting", "progress": 55.0})
                return True, ""

            events = []
            with patch("ytd_app.engine.probe_media_info", return_value={"video_codec": "vp9", "audio_codec": "opus", "duration": 20.0}), \
                 patch("ytd_app.engine.select_encoder_candidates", return_value=[("libx265", ["-c:v", "libx265"])]), \
                 patch("ytd_app.engine._execute_ffmpeg_with_progress", side_effect=fake_exec):
                out_path, label = ensure_video_codec(sample, job, Settings(), ctrl, events.append, lambda m: None)
                self.assertEqual(label, "H.265")
                self.assertTrue(out_path.exists())
                self.assertTrue(any(e.get("status") == "converting" for e in events))

    def test_hardware_monitor_and_updater_version_compare(self):
        from ytd_app.hw_monitor import HardwareMonitor
        from ytd_app.updater import is_newer_version, parse_version_tuple, resolve_manifest_url
        self.assertEqual(parse_version_tuple("v2.1.0"), (2, 1, 0))
        self.assertTrue(is_newer_version("2.1.0", "2.0.0"))
        self.assertFalse(is_newer_version("2.0.0", "2.0.0"))
        self.assertFalse(is_newer_version("1.9.5", "2.0.0"))
        self.assertEqual(
            resolve_manifest_url(""),
            "https://api.github.com/repos/ybao2004/YT_Desktop_downloader/releases/latest",
        )
        self.assertEqual(
            resolve_manifest_url("https://github.com/ybao2004/YT_Desktop_downloader"),
            "https://api.github.com/repos/ybao2004/YT_Desktop_downloader/releases/latest",
        )

        mon = HardwareMonitor()
        metrics = mon.sample_metrics()
        self.assertGreaterEqual(metrics.disk_total_gb, 0.0)

    def test_ffmpeg_progress_no_stderr_deadlock_and_win_replace_retry(self):
        import sys
        import threading
        from ytd_app.engine import _execute_ffmpeg_with_progress, _safe_win_replace, extract_youtube_video_id

        self.assertEqual(extract_youtube_video_id("https://www.youtube.com/watch?v=bXlQ3Mw4uGc"), "bXlQ3Mw4uGc")
        self.assertEqual(extract_youtube_video_id("https://youtu.be/bXlQ3Mw4uGc?si=123"), "bXlQ3Mw4uGc")

        # 1. Test that >100KB of stderr output + stdout progress does not deadlock _execute_ffmpeg_with_progress
        with tempfile.TemporaryDirectory() as tmp:
            temp_out = Path(tmp) / "out.transcode_temp.mp4"
            script = (
                "import sys\n"
                "sys.stderr.write('Duration: 00:00:10.00\\n' + ('warning line ' * 400 + '\\n') * 30)\n"
                "sys.stderr.flush()\n"
                "for sec in (2, 5, 8, 10):\n"
                "    sys.stdout.write(f'fps=120.0\\nout_time_us={sec*1000000}\\nspeed=4.0x\\nprogress=continue\\n')\n"
                "    sys.stdout.flush()\n"
                "sys.stdout.write('progress=end\\n')\n"
                "sys.stdout.flush()\n"
            )
            ctrl = types.SimpleNamespace(cancel_event=threading.Event(), run_event=threading.Event())
            ctrl.run_event.set()
            events = []
            ok, err = _execute_ffmpeg_with_progress(
                [sys.executable, "-c", script],
                0.0,  # Duration inferred from stderr!
                "Đang đổi H.264 (GPU)",
                ctrl,
                events.append,
                temp_out,
            )
            self.assertTrue(ok)
            self.assertTrue(any(e.get("progress", 0) >= 45.0 for e in events))

            # 2. Test _safe_win_replace retries transient PermissionError (WinError 5)
            src = Path(tmp) / "video.temp.mp4"
            dst = Path(tmp) / "video.mp4"
            src.write_bytes(b"new_mp4_content")
            dst.write_bytes(b"old_mp4_content")
            attempts = {"n": 0}
            from ytd_app.engine import _ORIG_OS_REPLACE as real_orig_replace

            def flaky_replace(s, d):
                attempts["n"] += 1
                if attempts["n"] < 3:
                    raise PermissionError(5, "Access is denied", str(s), 5, str(d))
                return real_orig_replace(s, d)

            with patch("ytd_app.engine._ORIG_OS_REPLACE", side_effect=flaky_replace):
                _safe_win_replace(str(src), str(dst))
            self.assertEqual(dst.read_bytes(), b"new_mp4_content")
            self.assertEqual(attempts["n"], 3)

            # 3. Test find_output_file ignores .temp.mp4 and .f137.mp4
            stale_temp = Path(tmp) / "Flowers [bXlQ3Mw4uGc].temp.mp4"
            stale_frag = Path(tmp) / "Flowers [bXlQ3Mw4uGc].f137.mp4"
            real_mp4 = Path(tmp) / "Flowers [bXlQ3Mw4uGc].mp4"
            real_mp4.write_bytes(b"final")
            stale_temp.write_bytes(b"temp")
            stale_frag.write_bytes(b"frag")
            job = Job(url="https://www.youtube.com/watch?v=bXlQ3Mw4uGc", mode="video", container="mp4")
            picked = find_output_file({"id": "bXlQ3Mw4uGc"}, Path(tmp), job)
            self.assertEqual(picked, real_mp4)


if __name__ == "__main__":
    unittest.main()

class SimulatedEngineTests(unittest.TestCase):
    def test_analyze_video_offline(self):
        from unittest.mock import MagicMock
        data = {"id": "abcdefghijk", "title": "Video demo", "formats": []}
        context = MagicMock()
        context.__enter__.return_value.extract_info.return_value = data
        with patch("ytd_app.engine.yt_dlp.YoutubeDL", return_value=context):
            response = inspect_url("https://youtu.be/abcdefghijk")
        self.assertEqual(response["type"], "video")
        self.assertEqual(response["video"]["title"], "Video demo")

    def test_analyze_playlist_offline(self):
        from unittest.mock import MagicMock
        data = {"_type": "playlist", "title": "Demo list", "entries": [
            {"id": "abcdefghijk", "title": "First"},
            {"id": "12345678901", "title": "Second"},
            {"id": "invalid", "title": "Skip"},
        ]}
        context = MagicMock()
        context.__enter__.return_value.extract_info.return_value = data
        with patch("ytd_app.engine.yt_dlp.YoutubeDL", return_value=context):
            result = inspect_url("https://www.youtube.com/playlist?list=PL123", playlist=True)
        self.assertEqual(len(result["entries"]), 2)

    def test_simulated_download_and_settings(self):
        import threading
        from unittest.mock import MagicMock
        from ytd_app.engine import download_media
        # Module requires PyQt6, which is optional on a headless CI host.
        with tempfile.TemporaryDirectory() as tmp:
            item = Job(url="https://youtu.be/abcdefghijk", mode="audio", container="mp3", directory=tmp)
            output = Path(tmp).resolve() / "Video [abcdefghijk].mp3"
            ctx = MagicMock()
            def extract_info(url, download):
                output.write_bytes(b"mp3")
                return {"id": "abcdefghijk", "title": "Video"}
            ctx.__enter__.return_value.extract_info.side_effect = extract_info
            events = []
            control = types.SimpleNamespace(cancel_event=threading.Event(), run_event=threading.Event())
            control.run_event.set()
            with patch("ytd_app.engine.yt_dlp.YoutubeDL", return_value=ctx) as construct:
                result = download_media(item, Settings(), control, events.append, lambda x: None)
            self.assertEqual(Path(result).resolve(), output.resolve())
            self.assertTrue(any(e.get("title") == "Video" for e in events))
            self.assertEqual(construct.call_args.args[0]["postprocessors"][0]["preferredcodec"], "mp3")

    def test_cancel_before_download(self):
        import threading
        from ytd_app.engine import DownloadCancelled, download_media
        with tempfile.TemporaryDirectory() as tmp:
            job = Job(url="https://youtu.be/abcdefghijk", directory=tmp)
            control = types.SimpleNamespace(cancel_event=threading.Event(), run_event=threading.Event())
            control.cancel_event.set()
            control.run_event.set()
            with self.assertRaises(DownloadCancelled):
                download_media(job, Settings(), control, lambda d: None, lambda s: None)

    def test_outtmpl_default_no_id_suffix_and_optional_suffix(self):
        import threading
        from unittest.mock import MagicMock
        from ytd_app.engine import download_media
        with tempfile.TemporaryDirectory() as tmp:
            job = Job(url="https://youtu.be/abcdefghijk", mode="video", container="mp4", directory=tmp)
            target_default = Path(tmp) / "Test Video.mp4"
            target_default.write_bytes(b"data")

            ctx = MagicMock()
            ctx.__enter__.return_value.extract_info.return_value = {
                "id": "abcdefghijk",
                "title": "Test Video",
                "filepath": str(target_default),
            }
            ctrl = types.SimpleNamespace(cancel_event=threading.Event(), run_event=threading.Event())
            ctrl.run_event.set()

            # Default settings: no suffix in outtmpl
            with patch("ytd_app.engine.ensure_video_codec", return_value=(target_default, "H.264")):
                with patch("ytd_app.engine.yt_dlp.YoutubeDL", return_value=ctx) as construct:
                    download_media(job, Settings(), ctrl, lambda d: None, lambda s: None)
                tmpl_default = construct.call_args.args[0]["outtmpl"]
                self.assertTrue(tmpl_default.endswith("%(title)s.%(ext)s"))
                self.assertNotIn("[%(id)s]", tmpl_default)

                # When append_id_suffix is enabled: has [%(id)s]
                with patch("ytd_app.engine.yt_dlp.YoutubeDL", return_value=ctx) as construct_suffix:
                    download_media(job, Settings(append_id_suffix=True), ctrl, lambda d: None, lambda s: None)
                tmpl_suffix = construct_suffix.call_args.args[0]["outtmpl"]
                self.assertTrue(tmpl_suffix.endswith("%(title)s [%(id)s].%(ext)s"))


class UIRedesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
            cls.app = QApplication.instance() or QApplication([])
            cls.has_qt = True
        except Exception:
            cls.has_qt = False

    def test_ui_workflows_and_cards(self):
        if not self.has_qt:
            self.skipTest("PyQt6 not available")
        from ytd_app.ui import MainWindow
        with tempfile.TemporaryDirectory() as tmp:
            with patch("ytd_app.ui.Storage") as MockStorage:
                store = Storage(Path(tmp))
                MockStorage.return_value = store
                win = MainWindow()
                win.folder_edit.setText(tmp)

                # 1. Verify initial state: preview hidden, empty state visible
                self.assertFalse(win.preview_card.isVisible())
                self.assertFalse(win.empty_state_frame.isHidden())

                # 2. Simulate video analysis ready
                fake_video = {
                    "type": "video",
                    "video": {
                        "url": "https://youtu.be/abcdefghijk",
                        "title": "Test Video Redesign",
                        "channel": "Demo Channel",
                        "duration": "03:45",
                        "thumbnail": "",
                        "id": "abcdefghijk",
                        "formats": [
                            {
                                "id": "137", "ext": "mp4", "resolution": "1080p",
                                "height": 1080, "fps": "60", "video": "avc1",
                                "audio": "none", "bitrate": "2500 kb/s", "size": "25.0 MB",
                                "has_video": True, "has_audio": False,
                            }
                        ],
                    },
                }
                win.url_edit.setText("https://youtu.be/abcdefghijk")
                win.analyze_key = "k1"
                win.analyze_url = "https://youtu.be/abcdefghijk"
                win.analyze_playlist = False
                win.analysis_ready("k1", fake_video)

                self.assertFalse(win.preview_card.isHidden())
                self.assertEqual(win.preview_stack.currentIndex(), 0)
                self.assertTrue(win.formats_table.isHidden())
                win.exact_format_check.setChecked(True)
                self.assertFalse(win.formats_table.isHidden())
                win.exact_format_check.setChecked(False)

                # 3. Simulate playlist analysis with checkbox selection
                fake_playlist = {
                    "type": "playlist",
                    "title": "My Course Playlist",
                    "entries": [
                        {"url": "https://youtu.be/11111111111", "title": "Lesson 1"},
                        {"url": "https://youtu.be/22222222222", "title": "Lesson 2"},
                        {"url": "https://youtu.be/33333333333", "title": "Lesson 3"},
                    ],
                }
                win.playlist_check.setChecked(True)
                win.analyze_key = "k2"
                win.analyze_url = "https://youtu.be/abcdefghijk"
                win.analyze_playlist = True
                win.analysis_ready("k2", fake_playlist)

                self.assertEqual(win.preview_stack.currentIndex(), 1)
                self.assertEqual(len(win.playlist_checkboxes), 3)
                # Uncheck second item
                win.playlist_checkboxes[1][0].setChecked(False)
                win.update_playlist_selection_count()
                self.assertIn("2/3", win.video_count_label.text())

                # Add selected playlist items (mock schedule_next so no real worker starts)
                with patch.object(win, "schedule_next"):
                    win.add_from_preview()
                self.assertEqual(len(win.jobs), 2)
                self.assertEqual(len(win.job_cards), 2)
                self.assertTrue(win.queue_running)

                # 4. Test tab filtering & search
                j1, j2 = win.jobs[0], win.jobs[1]
                j1.status = "done"
                j1.filepath = str(Path(tmp) / "done.mp4")
                j2.status = "error"
                j2.error = "Network timeout"
                win.paint_job(j1)
                win.paint_job(j2)
                win.refresh_stats()

                win.switch_workspace_tab("done")
                self.assertFalse(win.job_cards[j1.job_id].isHidden())
                self.assertTrue(win.job_cards[j2.job_id].isHidden())

                win.switch_workspace_tab("error")
                self.assertTrue(win.job_cards[j1.job_id].isHidden())
                self.assertFalse(win.job_cards[j2.job_id].isHidden())

                win.switch_workspace_tab("all")
                win.search_edit.setText("Lesson 1")
                self.assertFalse(win.job_cards[j1.job_id].isHidden())
                self.assertTrue(win.job_cards[j2.job_id].isHidden())
                win.search_edit.setText("")

                # 5. Test Log Tab switch
                win.switch_workspace_tab("log")
                self.assertEqual(win.workspace_stack.currentIndex(), 1)
                win.switch_workspace_tab("all")
                self.assertEqual(win.workspace_stack.currentIndex(), 0)

                # 6. Test clear completed jobs
                win.clear_completed_jobs()
                self.assertEqual(len(win.jobs), 1)
                self.assertEqual(win.jobs[0].job_id, j2.job_id)

                # 7. Verify new layout: telemetry pills in statusBar & settings_btn in workspace bar
                from ytd_app.storage import _normalize_download_dir
                from ytd_app.version import app_data_dir, default_download_dir
                self.assertEqual(default_download_dir(), Path.home() / "Downloads" / "YouTube Desktop Downloader")
                self.assertEqual(app_data_dir(), Path.home() / "youtube_desktop_downloader_data")
                self.assertEqual(
                    _normalize_download_dir(r"C:\Users\SomeOtherPCUser_DoesNotExist\Downloads\YouTube Desktop Downloader"),
                    str(default_download_dir()),
                )
                self.assertEqual(
                    _normalize_download_dir(r"C:\Users\Y Bao\Downloads\YouTube Downloads"),
                    str(default_download_dir()),
                )
                self.assertIsNotNone(win.settings_btn)
                self.assertIn("Cài đặt", win.settings_btn.text())
                self.assertIs(win.pill_cpu.parentWidget(), win.statusBar())
                win.close()

    def test_minimal_ui_sidebar_themes_icons_hover_and_settings(self):
        if not self.has_qt:
            self.skipTest("PyQt6 not available")
        from PyQt6.QtCore import Qt
        from ytd_app.theme import DARK, LIGHT, build_stylesheet, resolve_mode, theme_manager
        from ytd_app.ui import MainWindow, load_bundled_fonts
        from ytd_app.ui import icons as ui_icons

        # 1. Verify bundled Inter font & Lucide SVG icons
        fam = load_bundled_fonts()
        self.assertTrue(fam)
        avail = set(ui_icons.available_icons())
        for required_ic in (
            "download", "clipboard-paste", "search", "x", "pause", "play",
            "rotate-cw", "trash-2", "folder", "folder-open", "ellipsis",
            "repeat-2", "cpu", "microchip", "memory-stick", "hard-drive",
            "activity", "scroll-text", "book-open", "settings", "sun", "moon", "monitor",
        ):
            self.assertIn(required_ic, avail)
            pix = ui_icons.render_svg_pixmap(required_ic, "#18181B", size=16, dpr=2.0)
            self.assertFalse(pix.isNull())

        # 2. Verify Light & Dark stylesheets and ThemeManager
        qss_light = build_stylesheet(LIGHT)
        qss_dark = build_stylesheet(DARK)
        self.assertIn("#FAFAFA", qss_light)
        self.assertIn("#09090B", qss_dark)
        self.assertIn(resolve_mode("system"), ("light", "dark"))

        with tempfile.TemporaryDirectory() as tmp:
            with patch("ytd_app.ui.Storage") as MockStorage:
                store = Storage(Path(tmp))
                MockStorage.return_value = store
                win = MainWindow()
                win.show()

                # 3. Verify Sidebar branding ("YouTube" on top, "Downloader" below, left-aligned)
                self.assertEqual(win.sidebar.brand_top_label.text(), "YouTube")
                self.assertEqual(win.sidebar.brand_bottom_label.text(), "Downloader")
                self.assertTrue(
                    bool(win.sidebar.brand_top_label.alignment() & Qt.AlignmentFlag.AlignLeft)
                )
                self.assertTrue(
                    bool(win.sidebar.brand_bottom_label.alignment() & Qt.AlignmentFlag.AlignLeft)
                )

                # 4. Verify Sidebar navigation across all 5 pages
                for key, expected_idx in [
                    ("downloads", 0),
                    ("log", 1),
                    ("hardware", 2),
                    ("guide", 3),
                    ("settings", 4),
                    ("all", 0),
                ]:
                    win.switch_workspace_tab(key)
                    self.assertEqual(win.workspace_stack.currentIndex(), expected_idx)

                # 5. Verify JobRow hover-only action buttons & status-dependent visibility
                job = Job(
                    url="https://youtu.be/abcdefghijk",
                    title="Very Long Video Title To Verify Dynamic Eliding In List Row Widget",
                    mode="video",
                    container="mp4",
                    quality="1080",
                    directory=tmp,
                )
                job.status = "downloading"
                job.progress = 55.0
                win.jobs.append(job)
                win.jobs_by_id[job.job_id] = job
                win.insert_job_row(job)
                row_widget = win.job_cards[job.job_id]

                # Actions hidden when not hovered
                self.assertFalse(row_widget.is_hovered())
                self.assertTrue(row_widget.actions_container.isHidden())

                # Actions shown on hover
                row_widget.set_hovered(True)
                self.assertFalse(row_widget.actions_container.isHidden())
                self.assertFalse(row_widget.btn_pause.isHidden())
                self.assertFalse(row_widget.btn_cancel.isHidden())
                self.assertTrue(row_widget.btn_play.isHidden())

                # Switch job to done -> play & folder visible, progress bar hidden
                job.status = "done"
                job.filepath = str(Path(tmp) / "out.mp4")
                row_widget.update_from_job(job)
                self.assertTrue(row_widget.progress_bar.isHidden())
                self.assertFalse(row_widget.btn_play.isHidden())
                self.assertFalse(row_widget.btn_folder.isHidden())
                self.assertTrue(row_widget.btn_pause.isHidden())

                row_widget.set_hovered(False)
                self.assertTrue(row_widget.actions_container.isHidden())

                # 6. Verify auto-saving Settings controls & Theme switching
                dark_idx = win.theme_segment.findData("dark")
                win.theme_segment.setCurrentIndex(dark_idx)
                self.assertEqual(win.settings.theme_mode, "dark")
                self.assertEqual(theme_manager().mode, "dark")

                light_idx = win.theme_segment.findData("light")
                win.theme_segment.setCurrentIndex(light_idx)
                self.assertEqual(win.settings.theme_mode, "light")
                self.assertEqual(theme_manager().mode, "light")

                win.concurrent_spin.setValue(4)
                self.assertEqual(win.settings.max_concurrent, 4)
                win.quick_download_check.setChecked(False)
                self.assertFalse(win.settings.quick_download)

                # Verify ID suffix setting toggle
                self.assertFalse(win.settings.append_id_suffix)
                win.id_suffix_check.setChecked(True)
                self.assertTrue(win.settings.append_id_suffix)

                # Verify Log timestamping
                win.log("Thông điệp kiểm tra nhật ký")
                log_text = win.log_box.toPlainText()
                self.assertTrue(re.search(r"\[\d{2}:\d{2}:\d{2}\] Thông điệp kiểm tra nhật ký", log_text))

                # 7. Verify Hardware sparkline sample pushing
                win.metric_cpu.set_metric("35%", "35.0% đang sử dụng", 35.0)
                self.assertEqual(win.metric_cpu.sparkline.samples()[-1], 35.0)

                win.close()


if __name__ == "__main__":
    unittest.main()


