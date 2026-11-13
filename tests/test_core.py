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
    _ = yt_dlp
except ModuleNotFoundError:
    fake = types.ModuleType("yt_dlp")
    fake.version = types.SimpleNamespace(__version__="stub")
    fake.YoutubeDL = object
    sys.modules["yt_dlp"] = fake

from ytd_app.engine import (
    _entry_url, build_format, find_output_file, friendly_eta, friendly_size,
    inspect_url, is_youtube_url, metadata_view, send_to_trash,
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

    def test_send_to_trash(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "test_del.txt"
            f.write_text("hello recycle bin")
            self.assertTrue(f.exists())
            ok = send_to_trash(f)
            self.assertTrue(ok)
            self.assertFalse(f.exists())


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

    def test_v2_batch_download_auto_capture_and_undo_workflows(self):
        if not self.has_qt:
            self.skipTest("PyQt6 not available")
        import ytd_app
        from ytd_app.engine import extract_youtube_urls
        from ytd_app.ui import MainWindow
        from ytd_app.version import APP_VERSION

        # 1. Verify APP_VERSION is 3.x and matches package __version__
        self.assertTrue(APP_VERSION.startswith("3."))
        self.assertEqual(ytd_app.__version__, APP_VERSION)

        # 2. Verify extract_youtube_urls parses multi-line, filters non-YouTube, and deduplicates
        raw_input = (
            "Random note line without link\n"
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
            "https://example.com/not-youtube\n"
            "Check this out: https://youtu.be/dQw4w9WgXcQ and https://youtu.be/abc12345678, "
            "plus https://www.youtube.com/shorts/xyz98765432!"
        )
        valid_urls, dup_cnt, ignored_cnt = extract_youtube_urls(raw_input)
        self.assertEqual(len(valid_urls), 3)
        self.assertEqual(dup_cnt, 1)
        self.assertGreaterEqual(ignored_cnt, 2)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("ytd_app.ui.Storage") as MockStorage:
                store = Storage(Path(tmp))
                MockStorage.return_value = store
                win = MainWindow()
                win.show()

                # 3. Verify unified Sidebar ("downloads" only, no separate "batch" tab) & version label
                nav_keys = list(win.sidebar.nav_buttons.keys())
                self.assertEqual(nav_keys[0], "downloads")
                self.assertNotIn("batch", nav_keys)
                self.assertIn(f"v{APP_VERSION}", win.sidebar.version_label.text())

                # 4. Verify unified Downloads tab UI: "Hàng đợi" button removed/hidden, "Tự bắt link" default OFF,
                #    "Nhập nhiều dòng..." button visible on config row, and folder_chip mounted on bottom statusBar
                self.assertEqual(win.workspace_stack.currentIndex(), 0)
                self.assertTrue(win.queue_btn.isHidden())
                self.assertTrue(win.analyze_btn.isHidden())
                self.assertEqual(win.add_btn.text(), "Tải xuống")
                self.assertFalse(win.multiline_btn.isHidden())
                self.assertIn("Nhập nhiều dòng", win.multiline_btn.text())
                self.assertFalse(win.auto_capture_btn.isChecked())
                self.assertIn("Tự bắt link: Tắt", win.auto_capture_btn.text())
                self.assertIs(win.folder_chip.parentWidget(), win.statusBar())
                win.statusBar().showMessage("Kiểm tra thông báo thanh trạng thái", 3000)
                self.assertFalse(win.folder_chip.isHidden())

                # 5. Enqueue URLs via Multi-line batch -> added in "queued" state WITHOUT auto-starting download,
                #    and verify "Chờ tải" ("queued") and "Đang tải" ("active") do NOT overlap
                win.enqueue_batch_urls(
                    "https://youtu.be/vid00000001\n"
                    "https://www.youtube.com/watch?v=vid00000002\n"
                    "https://www.youtube.com/watch?v=vid00000001\n"
                    "not a link",
                    source_label="Nhập nhiều dòng",
                    auto_start=False,
                )
                self.assertEqual(len(win.jobs), 2)
                self.assertFalse(win.queue_running)
                self.assertEqual(len(win.active), 0)
                self.assertTrue(all(j.status == "queued" for j in win.jobs))
                self.assertIn("Hàng chờ (2)", win.tab_buttons["queued"].text())
                self.assertIn("Đang tải (0)", win.tab_buttons["active"].text())

                # Verify filter views are disjoint between "queued" and "active"
                win.switch_workspace_tab("queued")
                self.assertFalse(win.job_cards[win.jobs[0].job_id].isHidden())
                self.assertFalse(win.job_cards[win.jobs[1].job_id].isHidden())

                win.switch_workspace_tab("active")
                self.assertTrue(win.job_cards[win.jobs[0].job_id].isHidden())
                self.assertTrue(win.job_cards[win.jobs[1].job_id].isHidden())

                win.switch_workspace_tab("all")

                # Deduplication against already queued jobs
                added_again = win.enqueue_batch_urls(["https://youtu.be/vid00000002"], source_label="Test")
                self.assertEqual(added_again, 0)
                self.assertEqual(len(win.jobs), 2)

                # 6. Verify queued JobRow hover actions: btn_start & btn_remove hidden until hovered
                first_job = win.jobs[0]
                first_row = win.job_cards[first_job.job_id]
                self.assertTrue(first_row.actions_container.isHidden())
                first_row.set_hovered(True)
                self.assertFalse(first_row.actions_container.isHidden())
                self.assertFalse(first_row.btn_start.isHidden())
                self.assertFalse(first_row.btn_remove.isHidden())
                first_row.set_hovered(False)
                self.assertTrue(first_row.actions_container.isHidden())

                # 7. Verify "Tự bắt link" toggle ON & clipboard change handling
                win.auto_capture_btn.setChecked(True)
                self.assertTrue(win.auto_capture_enabled)
                self.assertIn("Tự bắt link: Bật", win.auto_capture_btn.text())

                # 8. Verify single delete + Undo & Clear All + Undo
                first_id = win.jobs[0].job_id
                win.remove_job_by_id(first_id)
                self.assertEqual(len(win.jobs), 1)
                self.assertTrue(win.undo_btn.isEnabled())

                win.undo_last_remove()
                self.assertEqual(len(win.jobs), 2)
                self.assertEqual(win.jobs[0].job_id, first_id)

                win.clear_all_jobs()
                self.assertEqual(len(win.jobs), 0)
                self.assertTrue(win.undo_btn.isEnabled())

                win.undo_last_remove()
                self.assertEqual(len(win.jobs), 2)
                self.assertFalse(win.undo_btn.isEnabled())

                # 9. Verify changing folder updates all queued jobs' destination immediately
                new_dest = str(Path(tmp) / "CustomUserFolder")
                win.folder_edit.setText(new_dest)
                win.on_folder_edited()
                self.assertEqual(win.jobs[0].directory, new_dest)
                self.assertEqual(win.jobs[1].directory, new_dest)
                self.assertIn("CustomUserFolder", win.job_cards[win.jobs[0].job_id].detail_label.text())

                # 10. Verify single job change_folder
                specific_dest = str(Path(tmp) / "SpecificJobFolder")
                with patch("PyQt6.QtWidgets.QFileDialog.getExistingDirectory", return_value=specific_dest):
                    win.change_job_folder_by_id(win.jobs[0].job_id)
                self.assertEqual(win.jobs[0].directory, specific_dest)
                self.assertEqual(win.jobs[1].directory, new_dest)
                self.assertIn("SpecificJobFolder", win.job_cards[win.jobs[0].job_id].detail_label.text())

                win.close()

    def test_lightweight_level2_packaging_and_runtime_bootstrap(self):
        import io
        import zipfile
        import build_portable
        from ytd_app.engine import environment_report
        from ytd_app.updater import ensure_runtime_binaries

        # 1. Verify excluded modules in build_portable
        for mod in ("PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtSql", "tkinter", "unittest", "sqlite3"):
            self.assertIn(mod, build_portable.EXCLUDED_MODULES)

        # 2. Verify environment_report falls back ffprobe to ffmpeg -i when ffprobe is absent
        with patch("ytd_app.engine.shutil.which") as mock_find:
            mock_find.side_effect = lambda name: (
                r"C:\fake\bin\ffmpeg.exe" if name == "ffmpeg" else (r"C:\fake\bin\deno.exe" if name == "deno" else None)
            )
            rep = environment_report()
            self.assertEqual(rep["ffmpeg"], r"C:\fake\bin\ffmpeg.exe")
            self.assertIn("ffmpeg -i", rep["ffprobe"])

        # 3. Verify ensure_runtime_binaries downloads and extracts deno.exe & ffmpeg.exe into bin_dir
        with tempfile.TemporaryDirectory() as tmp:
            fake_app_dir = Path(tmp)

            def make_fake_zip(member_path: str, payload: bytes) -> bytes:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(member_path, payload)
                return buf.getvalue()

            deno_zip = make_fake_zip("deno.exe", b"MZ_FAKE_DENO")
            ffmpeg_zip = make_fake_zip("ffmpeg-master/bin/ffmpeg.exe", b"MZ_FAKE_FFMPEG")

            class FakeResp:
                def __init__(self, data: bytes):
                    self._bio = io.BytesIO(data)
                    self.headers = {"Content-Length": str(len(data))}

                def read(self, size: int = -1) -> bytes:
                    return self._bio.read(size)

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

            def fake_urlopen(req, timeout=180):
                url = req.full_url if hasattr(req, "full_url") else str(req)
                if "deno" in url.lower():
                    return FakeResp(deno_zip)
                return FakeResp(ffmpeg_zip)

            with patch("ytd_app.updater.app_data_dir", return_value=fake_app_dir), patch(
                "ytd_app.updater.shutil.which", return_value=None
            ), patch("urllib.request.urlopen", side_effect=fake_urlopen):
                ok, msg = ensure_runtime_binaries(force=True)
                self.assertTrue(ok, msg)
                self.assertTrue((fake_app_dir / "bin" / "deno.exe").is_file())
                self.assertTrue((fake_app_dir / "bin" / "ffmpeg.exe").is_file())

            # 4. Verify stage_portable_update sets PYINSTALLER_RESET_ENVIRONMENT=1 and strips _MEIPASS2
            from ytd_app.updater import stage_portable_update
            fake_pkg = fake_app_dir / "dummy_update.exe"
            fake_pkg.write_bytes(b"MZ_FAKE_EXE")
            with patch("ytd_app.updater.app_data_dir", return_value=fake_app_dir):
                bat_path = stage_portable_update(fake_pkg)
                bat_text = bat_path.read_text(encoding="utf-8")
                self.assertIn('set "PYINSTALLER_RESET_ENVIRONMENT=1"', bat_text)
                self.assertIn('set "_MEIPASS2="', bat_text)
                self.assertIn('set "_PYI_ARCHIVE_FILE="', bat_text)
                self.assertIn("tasklist /FI", bat_text)

        # 5. Verify _run_ytdlp_extract_with_fallback retries on 'Sign in to confirm you're not a bot'
        from ytd_app.engine import _run_ytdlp_extract_with_fallback
        seen_opts: list[dict] = []

        class BotCheckFakeYDL:
            def __init__(self, opts):
                self.opts = dict(opts)
                seen_opts.append(self.opts)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download=False):
                if self.opts.get("cookiesfrombrowser") == ("firefox",):
                    return {"id": "OP-00EwLdiU", "title": "Oceans", "webpage_url": url}
                raise Exception(
                    "ERROR: [youtube] OP-00EwLdiU: Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies"
                )

        with patch("ytd_app.engine.yt_dlp.YoutubeDL", BotCheckFakeYDL):
            res = _run_ytdlp_extract_with_fallback(
                {"quiet": True},
                "https://www.youtube.com/watch?v=OP-00EwLdiU",
                download=False,
                cookies_from_browser="auto",
            )
            self.assertEqual(res["id"], "OP-00EwLdiU")
            self.assertGreaterEqual(len(seen_opts), 3)

        # 6. Verify parse_and_normalize_netscape_cookies normalizes pasted cookies.txt content
        from ytd_app.ui.pages import parse_and_normalize_netscape_cookies
        raw_cookies = (
            ".youtube.com\tTRUE\t/\tTRUE\t1799999999\tSID\tabc123xyz\n"
            ".youtube.com TRUE / TRUE 1799999999 __Secure-3PSID def456uvw\n"
            "invalid line that is not a cookie\n"
        )
        norm_text, count = parse_and_normalize_netscape_cookies(raw_cookies)
        self.assertEqual(count, 2)
        self.assertTrue(norm_text.startswith("# Netscape HTTP Cookie File\n"))
        self.assertIn(".youtube.com\tTRUE\t/\tTRUE\t1799999999\t__Secure-3PSID\tdef456uvw", norm_text)

        # Test file path input (validates Path import and disk reading in batch.py)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as tf:
            tf.write(raw_cookies)
            temp_cookie_path = tf.name
        try:
            path_norm_text, path_count = parse_and_normalize_netscape_cookies(temp_cookie_path)
            self.assertEqual(path_count, 2)
            self.assertEqual(path_norm_text, norm_text)
        finally:
            Path(temp_cookie_path).unlink(missing_ok=True)

    def test_mute_audio_video_only_download_and_strip_existing(self):
        from ytd_app.engine import build_format, transcode_existing_job
        from ytd_app.models import Job, Settings
        from ytd_app.workers import DownloadControl

        # 1. build_format omits +ba when mute_audio=True
        j_normal = Job(url="https://youtu.be/abc12345678", mode="video", container="mp4", quality="1080", video_codec="h264", mute_audio=False)
        j_muted = Job(url="https://youtu.be/abc12345678", mode="video", container="mp4", quality="1080", video_codec="h264", mute_audio=True)
        fmt_normal = build_format(j_normal)
        fmt_muted = build_format(j_muted)
        self.assertIn("+ba", fmt_normal)
        self.assertNotIn("+ba", fmt_muted)
        self.assertTrue(fmt_muted.startswith("bv*[vcodec^=avc1]"))

        # Custom format_id with format_has_audio=False vs mute_audio=True
        j_fmt = Job(url="https://youtu.be/abc12345678", mode="video", container="mp4", format_id="137", format_ext="mp4", format_has_audio=False, mute_audio=True)
        self.assertEqual(build_format(j_fmt), "137")

        # 2. transcode_existing_job with target_codec="mute" strips audio in-place and sets job.mute_audio=True
        with tempfile.TemporaryDirectory() as tmp:
            fake_video = Path(tmp) / "sample.mp4"
            fake_video.write_bytes(b"FAKE_VIDEO_WITH_AUDIO")
            job_tc = Job(url="https://youtu.be/abc12345678", title="Sample", mode="video", container="mp4", filepath=str(fake_video), mute_audio=False)

            def fake_strip(path, start, end, control, progress_cb=None, log_cb=None, total_duration=None, strip_audio=False):
                self.assertTrue(strip_audio)
                Path(path).write_bytes(b"FAKE_VIDEO_MUTED")
                return Path(path)

            with patch("ytd_app.engine._run_ffmpeg_trim_only", side_effect=fake_strip), patch(
                "ytd_app.engine.probe_media_info", return_value={"duration": 10.0}
            ):
                out_path = transcode_existing_job(
                    job_tc,
                    "mute",
                    Settings(),
                    DownloadControl(),
                    lambda d: None,
                    lambda m: None,
                )
                self.assertEqual(out_path, str(fake_video))
                self.assertTrue(job_tc.mute_audio)
                self.assertEqual(fake_video.read_bytes(), b"FAKE_VIDEO_MUTED")

        # 3. UI verification for win.mute_btn, mode switching, and JobRow badge
        if self.has_qt:
            from ytd_app.ui import MainWindow
            with tempfile.TemporaryDirectory() as tmp:
                with patch("ytd_app.ui.Storage") as MockStorage:
                    MockStorage.return_value = Storage(Path(tmp))
                    win = MainWindow()
                    win.show()

                    # Default state on startup is always unchecked (False) and visible in video mode
                    self.assertFalse(win.mute_btn.isChecked())
                    self.assertFalse(win.mute_btn.isHidden())

                    # Switching to audio mode hides mute_btn; switching back to video shows it
                    audio_idx = win.mode_combo.findData("audio")
                    win.mode_combo.setCurrentIndex(audio_idx)
                    self.assertTrue(win.mute_btn.isHidden())
                    video_idx = win.mode_combo.findData("video")
                    win.mode_combo.setCurrentIndex(video_idx)
                    self.assertFalse(win.mute_btn.isHidden())

                    # Enqueue with mute_btn checked -> job.mute_audio is True and JobRow shows "Tắt tiếng"
                    win.mute_btn.setChecked(True)
                    win.enqueue_batch_urls("https://youtu.be/mute0000001", auto_start=False)
                    self.assertEqual(len(win.jobs), 1)
                    self.assertTrue(win.jobs[0].mute_audio)
                    row_card = win.job_cards[win.jobs[0].job_id]
                    self.assertIn("Tắt tiếng", row_card.spec_badge.text())
                    win.close()

    def test_retry_all_visible_recent_tab_and_detailed_specs_display(self):
        if not self.has_qt:
            self.skipTest("PyQt6 not available")
        from datetime import datetime, timedelta, timezone
        from ytd_app.models import Job
        from ytd_app.ui import MainWindow
        from ytd_app.ui.widgets import JobRow

        with tempfile.TemporaryDirectory() as tmp:
            with patch("ytd_app.ui.Storage") as MockStorage:
                store = Storage(Path(tmp))
                # Create an old historical job from 3 days ago (not in current session)
                old_ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
                j_old_done = Job(
                    url="https://youtu.be/olddone00001",
                    title="Old Done Video",
                    mode="video",
                    container="mp4",
                    quality="1080",
                    video_codec="h264",
                    status="done",
                    filepath=str(Path(tmp) / "old.mp4"),
                    created_at=old_ts,
                    updated_at=old_ts,
                )
                store.save_jobs([j_old_done])
                MockStorage.return_value = store

                win = MainWindow()
                win.show()

                # 1. Verify 6 status tabs exist and "recent" is active by default
                expected_tab_keys = ["recent", "all", "queued", "active", "done", "error"]
                self.assertEqual(list(win.tab_buttons.keys()), expected_tab_keys)
                self.assertEqual(win.current_filter, "recent")
                self.assertTrue(win.tab_buttons["recent"].isChecked())

                # The old done job should be visible in "all" and "done", but NOT in "recent"
                self.assertEqual(len(win.jobs), 1)
                self.assertFalse(win._is_recent_job(j_old_done))
                self.assertIn("Gần đây (0)", win.tab_buttons["recent"].text())
                self.assertIn("Tất cả (1)", win.tab_buttons["all"].text())
                self.assertIn("Hoàn tất (1)", win.tab_buttons["done"].text())

                # 2. Add a new job in the current session
                win.enqueue_batch_urls("https://youtu.be/recent000001", auto_start=False)
                self.assertEqual(len(win.jobs), 2)
                j_new = win.jobs[1]
                self.assertTrue(win._is_recent_job(j_new))
                self.assertIn("Gần đây (1)", win.tab_buttons["recent"].text())
                self.assertIn("Tất cả (2)", win.tab_buttons["all"].text())
                self.assertIn("Hàng chờ (1)", win.tab_buttons["queued"].text())

                # In "recent" filter, j_new is visible, j_old_done is hidden
                win.apply_job_filters()
                self.assertFalse(win.job_cards[j_new.job_id].isHidden())
                self.assertTrue(win.job_cards[j_old_done.job_id].isHidden())

                # 3. Test "Tải lại tất cả" (retry_all_visible) scoped to active tab with toolbar config update
                # Switch to "done" tab
                win.switch_workspace_tab("done")
                self.assertEqual(win.current_filter, "done")
                self.assertFalse(win.job_cards[j_old_done.job_id].isHidden())
                self.assertTrue(win.job_cards[j_new.job_id].isHidden())

                # Change toolbar config: switch to audio mode MP3, 320 kbps
                audio_idx = win.mode_combo.findData("audio")
                win.mode_combo.setCurrentIndex(audio_idx)
                ext_idx = win.ext_combo.findData("mp3")
                win.ext_combo.setCurrentIndex(ext_idx)
                br_idx = win.audio_bitrate_combo.findData("320")
                win.audio_bitrate_combo.setCurrentIndex(br_idx)

                # Click "Tải lại tất cả" -> only the 1 job in "done" tab should be re-queued with new config!
                with patch.object(win, "schedule_next"):
                    retried_cnt = win.retry_all_visible()
                self.assertEqual(retried_cnt, 1)
                target_j = win.jobs[0]
                self.assertEqual(target_j.status, "queued")
                self.assertEqual(target_j.mode, "audio")
                self.assertEqual(target_j.container, "mp3")
                self.assertEqual(target_j.audio_bitrate, "320")
                self.assertEqual(target_j.progress, 0.0)
                # j_new remains untouched (still queued, video mode)
                self.assertEqual(win.jobs[1].mode, "video")

                # 4. Verify JobRow displays: Định dạng · Codec · Độ phân giải · FPS · Bitrate · Đường dẫn lưu
                test_job = Job(
                    url="https://youtu.be/specs0000001",
                    title="Specs Display Test Video",
                    mode="video",
                    container="mp4",
                    video_codec="h264",
                    detected_codec="H.264",
                    detected_resolution="1920x1080",
                    detected_fps="60fps",
                    detected_bitrate="4500 kbps",
                    status="done",
                    filepath=r"D:\Downloads\video_sample.mp4",
                    directory=r"D:\Downloads",
                )
                test_card = JobRow(test_job)
                spec_text = test_card.spec_badge.text()
                # Check format, codec, resolution, fps, bitrate
                self.assertIn("MP4", spec_text)
                self.assertIn("H.264", spec_text)
                self.assertIn("1920x1080", spec_text)
                self.assertIn("60fps", spec_text)
                self.assertIn("4500 kbps", spec_text)

                # Check status text
                self.assertIn("Hoàn tất", test_card.status_badge.text())

                # Check path in detail label
                self.assertIn(r"D:\Downloads\video_sample.mp4", test_card.detail_label.text())

                win.close()

    def test_per_tab_undo_redo_and_keyboard_shortcuts(self):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import Qt, QEvent
        from PyQt6.QtGui import QKeyEvent
        from ytd_app.ui.main_window import MainWindow
        from ytd_app.models import Job

        self.qapp = QApplication.instance() or QApplication([])

        with tempfile.TemporaryDirectory() as tmp:
            store = Storage(Path(tmp) / "data.json")
            j1 = Job(url="https://youtu.be/tab0000000001", title="Queued Job 1", status="queued")
            j2 = Job(url="https://youtu.be/tab0000000002", title="Queued Job 2", status="queued")
            j3 = Job(url="https://youtu.be/tab0000000003", title="Done Job 3", status="done", filepath=str(Path(tmp) / "done3.mp4"))
            store.save_jobs([j1, j2, j3])

            with patch("ytd_app.ui.Storage", return_value=store):
                win = MainWindow()
                win.show()

                with patch.object(win, "schedule_next"):
                    # 1. Verify initial Redo and Undo buttons
                    self.assertFalse(win.undo_btn.isEnabled())
                    self.assertFalse(win.redo_btn.isEnabled())
                    self.assertEqual(win.undo_btn.text(), "Hoàn tác")
                    self.assertEqual(win.redo_btn.text(), "Làm lại")

                    # 2. Test Tab Independence:
                    # Switch to "queued" tab
                    win.on_filter_pill_clicked("queued")
                    self.assertEqual(win.current_filter, "queued")
                    self.assertFalse(win.undo_btn.isEnabled())
                    self.assertFalse(win.redo_btn.isEnabled())

                    # Remove j1 in queued tab
                    win.remove_job_by_id(j1.job_id)
                    self.assertTrue(win.undo_btn.isEnabled())
                    self.assertEqual(win.undo_btn.text(), "Hoàn tác")
                    self.assertFalse(win.redo_btn.isEnabled())

                    # Switch to "done" tab
                    win.on_filter_pill_clicked("done")
                    self.assertEqual(win.current_filter, "done")
                    # In "done" tab, undo and redo should be disabled (isolated stack!)
                    self.assertFalse(win.undo_btn.isEnabled())
                    self.assertFalse(win.redo_btn.isEnabled())

                    # Switch back to "queued" tab
                    win.on_filter_pill_clicked("queued")
                    self.assertTrue(win.undo_btn.isEnabled())
                    self.assertFalse(win.redo_btn.isEnabled())

                    # Perform Undo in "queued" tab -> j1 restored
                    win.undo_last_remove()
                    self.assertIn(j1.job_id, win.jobs_by_id)
                    self.assertFalse(win.undo_btn.isEnabled())
                    self.assertTrue(win.redo_btn.isEnabled())
                    self.assertEqual(win.redo_btn.text(), "Làm lại")

                    # Perform Redo in "queued" tab -> j1 deleted again
                    win.redo_last_remove()
                    self.assertNotIn(j1.job_id, win.jobs_by_id)
                    self.assertTrue(win.undo_btn.isEnabled())
                    self.assertFalse(win.redo_btn.isEnabled())

                    # Undo once more to keep j1 in list
                    win.undo_last_remove()
                    self.assertIn(j1.job_id, win.jobs_by_id)

                    # 3. Test Multi-Select: Click, Ctrl+Click, Shift+Click
                    win.on_filter_pill_clicked("all")
                    visible = win.get_visible_jobs()
                    self.assertEqual(len(visible), 3)

                    # Plain click on first job
                    win.on_job_card_clicked(j1.job_id, Qt.KeyboardModifier.NoModifier)
                    self.assertEqual(win.selected_job_ids, {j1.job_id})
                    self.assertTrue(win.job_cards[j1.job_id].is_selected())
                    self.assertFalse(win.job_cards[j2.job_id].is_selected())

                    # Ctrl+Click on third job
                    win.on_job_card_clicked(j3.job_id, Qt.KeyboardModifier.ControlModifier)
                    self.assertEqual(win.selected_job_ids, {j1.job_id, j3.job_id})
                    self.assertTrue(win.job_cards[j1.job_id].is_selected())
                    self.assertTrue(win.job_cards[j3.job_id].is_selected())

                    # Shift+Click from j3 to j2
                    win.on_job_card_clicked(j2.job_id, Qt.KeyboardModifier.ShiftModifier)
                    self.assertEqual(win.selected_job_ids, {j2.job_id, j3.job_id})

                    # Select All
                    win.select_all_jobs()
                    self.assertEqual(len(win.selected_job_ids), 3)

                    # Deselect All
                    win.deselect_all_jobs()
                    self.assertEqual(len(win.selected_job_ids), 0)

                    # 4. Test Keyboard Shortcuts via keyPressEvent
                    # Select j2, press Delete
                    win.on_job_card_clicked(j2.job_id, Qt.KeyboardModifier.NoModifier)
                    del_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
                    win.keyPressEvent(del_event)
                    self.assertNotIn(j2.job_id, win.jobs_by_id)

                    # Press Ctrl + Z -> Undo
                    undo_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
                    win.keyPressEvent(undo_event)
                    self.assertIn(j2.job_id, win.jobs_by_id)

                    # Press Ctrl + Shift + Z -> Redo
                    redo_event = QKeyEvent(
                        QEvent.Type.KeyPress,
                        Qt.Key.Key_Z,
                        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
                    )
                    win.keyPressEvent(redo_event)
                    self.assertNotIn(j2.job_id, win.jobs_by_id)

                    # Press Ctrl + Y -> Redo alternate key
                    win.keyPressEvent(undo_event)
                    self.assertIn(j2.job_id, win.jobs_by_id)
                    redo_y_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
                    win.keyPressEvent(redo_y_event)
                    self.assertNotIn(j2.job_id, win.jobs_by_id)

                    # Restore j2
                    win.undo_last_remove()

                    # Test Ctrl + A via keyPressEvent
                    ctrl_a = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
                    win.keyPressEvent(ctrl_a)
                    self.assertEqual(len(win.selected_job_ids), 3)

                    # Test Ctrl + Shift + A via keyPressEvent
                    ctrl_shift_a = QKeyEvent(
                        QEvent.Type.KeyPress,
                        Qt.Key.Key_A,
                        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
                    )
                    win.keyPressEvent(ctrl_shift_a)
                    self.assertEqual(len(win.selected_job_ids), 0)

                    # Test Space shortcut on done job
                    win.on_job_card_clicked(j3.job_id, Qt.KeyboardModifier.NoModifier)
                    with patch.object(win, "play_job_file_by_id") as mock_play:
                        space_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
                        win.keyPressEvent(space_event)
                        mock_play.assert_called_once_with(j3.job_id)

                    # Test Enter shortcut on selected queued job
                    win.on_job_card_clicked(j1.job_id, Qt.KeyboardModifier.NoModifier)
                    with patch.object(win, "start_selected_jobs") as mock_start:
                        enter_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
                        win.keyPressEvent(enter_event)
                        mock_start.assert_called_once()

                    # 5. Test Input Focus Isolation: When focused on url_edit, Delete is not swallowed by job actions
                    win.url_edit.setFocus()
                    win.on_job_card_clicked(j1.job_id, Qt.KeyboardModifier.NoModifier)
                    job_count_before = len(win.jobs)
                    win.keyPressEvent(del_event)
                    self.assertEqual(len(win.jobs), job_count_before)

                    win.close()

    def test_delete_job_file_by_id_and_batch_files(self):
        from unittest.mock import patch
        from PyQt6.QtWidgets import QApplication, QMessageBox
        from ytd_app.ui.main_window import MainWindow
        from ytd_app.models import Job

        self.qapp = QApplication.instance() or QApplication([])

        with tempfile.TemporaryDirectory() as td:
            store = Storage(Path(td) / "test_store.json")
            f1 = Path(td) / "vid1.mp4"
            f1.write_text("sample content 1")
            f2 = Path(td) / "vid2.mp4"
            f2.write_text("sample content 2")

            j1 = Job(url="https://youtu.be/file0000000001", title="Done 1", status="done", filepath=str(f1))
            j2 = Job(url="https://youtu.be/file0000000002", title="Done 2", status="done", filepath=str(f2))
            store.save_jobs([j1, j2])

            with patch("ytd_app.ui.Storage", return_value=store):
                win = MainWindow()
                try:
                    with patch.object(win, "schedule_next"):
                        # 1. Single delete cancelled
                        with patch("PyQt6.QtWidgets.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
                            win.delete_job_file_by_id(j1.job_id)
                            self.assertTrue(f1.exists())
                            self.assertIn(j1.job_id, win.jobs_by_id)

                        # 2. Single delete confirmed
                        with patch("PyQt6.QtWidgets.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                            win.delete_job_file_by_id(j1.job_id)
                            self.assertFalse(f1.exists())
                            self.assertNotIn(j1.job_id, win.jobs_by_id)

                        # 3. Batch delete confirmed
                        win.selected_job_ids = {j2.job_id}
                        with patch("PyQt6.QtWidgets.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
                            win.delete_selected_job_files()
                            self.assertFalse(f2.exists())
                            self.assertNotIn(j2.job_id, win.jobs_by_id)
                finally:
                    win.close()

    def test_version_consistency_and_cookie_path_normalization(self):
        import json
        import ytd_app
        from ytd_app.ui.pages import parse_and_normalize_netscape_cookies
        from ytd_app.version import APP_VERSION

        # 1. Version consistency across package, manifest, and PE resource
        self.assertEqual(ytd_app.__version__, APP_VERSION)
        self.assertEqual(APP_VERSION, "3.2.2")

        root = Path(__file__).resolve().parent.parent
        version_info_path = root / "version_info.txt"
        if version_info_path.is_file():
            txt = version_info_path.read_text(encoding="utf-8")
            self.assertIn("(3, 2, 2, 0)", txt)
            self.assertIn("'3.2.2.0'", txt)

        manifest_path = root / "dist" / "version.json"
        if manifest_path.is_file():
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(data.get("version"), APP_VERSION)

        # 2. Path normalization with quotes and whitespace
        with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as tf:
            tf.write("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t1999999999\tSID\tsample_value\n")
            fpath = tf.name
        try:
            quoted_path = f'  "{fpath}"  '
            norm, cnt = parse_and_normalize_netscape_cookies(quoted_path)
            self.assertEqual(cnt, 1)
            self.assertIn("sample_value", norm)
        finally:
            Path(fpath).unlink(missing_ok=True)

    def test_startup_speed_optimizations_and_bug_fixes(self):
        """Test B1-B6 bug fixes, lazy import proxy, and zombie job recovery."""
        import json
        from ytd_app.storage import Storage, peek_theme_mode
        from ytd_app.engine import _fast_yt_dlp_version, environment_report

        # 1. Test peek_theme_mode
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            with patch("ytd_app.storage.config_dir", return_value=tmp_p):
                # When no file exists
                self.assertEqual(peek_theme_mode(), "system")
                # When dark mode is stored
                (tmp_p / "settings.json").write_text(json.dumps({"theme_mode": "dark"}), encoding="utf-8")
                self.assertEqual(peek_theme_mode(), "dark")
                # When light mode is stored
                (tmp_p / "settings.json").write_text(json.dumps({"theme_mode": "light"}), encoding="utf-8")
                self.assertEqual(peek_theme_mode(), "light")

        # 2. Test B2: Zombie Job recovery on startup in load_jobs()
        with tempfile.TemporaryDirectory() as tmp:
            store = Storage(base=Path(tmp))
            raw_jobs = [
                {"job_id": "z1", "url": "https://youtu.be/abc", "status": "downloading", "speed": "5 MB/s", "eta": "10s"},
                {"job_id": "z2", "url": "https://youtu.be/def", "status": "processing", "speed": "1 MB/s", "eta": "2s"},
                {"job_id": "z3", "url": "https://youtu.be/ghi", "status": "converting", "speed": "", "eta": ""},
                {"job_id": "normal", "url": "https://youtu.be/jkl", "status": "done"},
            ]
            store.jobs_path.write_text(json.dumps(raw_jobs), encoding="utf-8")
            recovered = store.load_jobs()
            by_id = {j.job_id: j for j in recovered}
            self.assertIn(by_id["z1"].status, {"queued", "paused"})
            self.assertEqual(by_id["z1"].speed, "")
            self.assertEqual(by_id["z1"].eta, "")
            self.assertIn(by_id["z2"].status, {"queued", "paused"})
            self.assertIn(by_id["z3"].status, {"queued", "paused"})
            self.assertEqual(by_id["normal"].status, "done")

        # 3. Test _fast_yt_dlp_version returns non-empty string
        fast_ver = _fast_yt_dlp_version()
        self.assertTrue(bool(fast_ver and fast_ver != "unknown"), f"Fast ver: {fast_ver}")

        # 4. Test environment_report includes yt_dlp_version
        with patch("ytd_app.engine.shutil.which", return_value=None):
            rep = environment_report()
            self.assertIn("yt_dlp_version", rep)
            self.assertTrue(bool(rep["yt_dlp_version"]))

        # 5. Test SplashScreen displays v3.2.1, shows on taskbar, and is not always-on-top
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication, QLabel
        from ytd_app.ui.splash import SplashScreen
        from ytd_app.version import APP_NAME
        app = QApplication.instance() or QApplication([])
        sp = SplashScreen()
        try:
            flags = sp.windowFlags()
            self.assertTrue(bool(flags & Qt.WindowType.FramelessWindowHint))
            self.assertFalse(bool(flags & Qt.WindowType.WindowStaysOnTopHint))
            self.assertNotEqual(flags & Qt.WindowType.WindowType_Mask, Qt.WindowType.SplashScreen)
            self.assertEqual(sp.windowTitle(), APP_NAME)

            sp.set_progress(100, "Hoàn tất!")
            self.assertEqual(sp.pbar.value(), 100)
            self.assertEqual(sp.status_label.text(), "Hoàn tất!")
            # Check version displayed in sub_label
            labels = sp.findChildren(QLabel)
            sub_texts = [lbl.text() for lbl in labels if "v3.2.2" in lbl.text()]
            self.assertTrue(len(sub_texts) > 0, f"Expected v3.2.2 in splash labels, found: {[l.text() for l in labels]}")
        finally:
            sp.close()

        # 6. Test Update tab UI fixes: & escaping, progress bar text hidden, no manifest_edit, about author/license, startup silent update & notification dots
        from ytd_app.ui import MainWindow
        from ytd_app.ui.widgets import tool_button
        from ytd_app.updater import UpdateInfo
        btn_amp = tool_button("Tự động cài FFmpeg & Deno")
        self.assertEqual(btn_amp.text(), "Tự động cài FFmpeg && Deno")

        with tempfile.TemporaryDirectory() as tmp:
            with patch("ytd_app.ui.main_window.Storage", side_effect=lambda: Storage(base=Path(tmp))):
                with patch("ytd_app.ui.main_window.MainWindow.check_environment", return_value={"ffmpeg": "ok", "ffprobe": "ok", "deno": "ok", "ejs": True, "yt_dlp_version": "2026.10"}):
                    win = MainWindow()
                    try:
                        self.assertFalse(hasattr(win, "manifest_edit"))
                        self.assertIn("@ybao04", win.about_author_lbl.text())
                        self.assertIn("GPL", win.about_author_lbl.text())
                        self.assertFalse(win.upd_pbar.isTextVisible())
                        self.assertTrue(win.auto_update_check_tab.isChecked())
                        # Silent update check always uses default GitHub repo even if legacy setting exists
                        win.settings.update_manifest_url = "https://legacy.example.com/manifest.json"
                        with patch.object(win.analyze_pool, "start") as mock_start:
                            win.check_remote_update_silent()
                            self.assertTrue(mock_start.called)
                            worker_arg = mock_start.call_args[0][0]
                            self.assertEqual(worker_arg.custom_url, "")
                        # Simulate receiving a new version notification
                        fake_info = UpdateInfo(
                            current_version="3.1",
                            latest_version="3.2",
                            has_update=True,
                            download_url="https://example.com/YouTubeDesktopDownloader.exe",
                            release_notes="New features",
                            source="https://api.github.com/repos/ybao2004/YT_Desktop_downloader/releases/latest",
                        )
                        win._on_silent_update_checked(fake_info)
                        self.assertFalse(win.sidebar.update_dot.isHidden())
                        self.assertIn(1, win.settings_sub_segment._dots)
                        self.assertFalse(win.settings_sub_segment._dots[1].isHidden())
                        self.assertIn("v3.2", win.upd_status_lbl.text())
                    finally:
                        win.close()

    def test_single_instance_locking_and_duplicate_prevention(self):
        """Test atomic Named Mutex single-instance lock and IPC duplicate prevention."""
        import main
        import sys

        if sys.platform == "win32":
            main.release_single_instance_lock()

            # 1. Primary acquire with custom test mutex name
            test_mutex = "Local\\Test_Single_Instance_Unit_Test"
            self.assertTrue(main.acquire_single_instance_lock(custom_name=test_mutex))
            self.assertIsNotNone(main._GLOBAL_MUTEX_HANDLE)

            # 2. Duplicate acquire while held
            self.assertFalse(main.acquire_single_instance_lock(custom_name=test_mutex))

            # 3. Clean release
            main.release_single_instance_lock()
            self.assertIsNone(main._GLOBAL_MUTEX_HANDLE)

            # 4. Acquire again after release
            self.assertTrue(main.acquire_single_instance_lock(custom_name=test_mutex))
            main.release_single_instance_lock()


if __name__ == "__main__":
    unittest.main()





