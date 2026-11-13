"""Media metadata extraction, download with yt-dlp, and smart FFmpeg codec conversion. No Qt dependencies."""
from __future__ import annotations

from collections import deque
import importlib.util
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

class _LazyYtDlpProxy:
    """Proxy object that delays importing yt_dlp until any attribute is accessed or patched."""
    def __getattr__(self, name: str):
        import yt_dlp as _real
        globals()["yt_dlp"] = _real
        return getattr(_real, name)

    def __setattr__(self, name: str, value):
        import yt_dlp as _real
        globals()["yt_dlp"] = _real
        setattr(_real, name, value)

    def __delattr__(self, name: str):
        import yt_dlp as _real
        globals()["yt_dlp"] = _real
        try:
            delattr(_real, name)
        except AttributeError:
            pass


yt_dlp = _LazyYtDlpProxy()


def _get_yt_dlp():
    """Lazily load the heavy yt_dlp library only when inspection or downloading actually begins."""
    global yt_dlp
    if isinstance(yt_dlp, _LazyYtDlpProxy):
        import yt_dlp as _imported
        yt_dlp = _imported
    return yt_dlp


def _fast_yt_dlp_version() -> str:
    """Retrieve yt-dlp version in milliseconds without triggering yt_dlp/__init__.py."""
    if yt_dlp is not None and hasattr(yt_dlp, "version"):
        return getattr(yt_dlp.version, "__version__", "unknown")
    if "yt_dlp" in sys.modules and hasattr(sys.modules["yt_dlp"], "version"):
        return getattr(sys.modules["yt_dlp"].version, "__version__", "unknown")
    try:
        import importlib.metadata
        return importlib.metadata.version("yt-dlp")
    except Exception:
        pass
    try:
        spec = importlib.util.find_spec("yt_dlp.version")
        if spec and spec.origin and Path(spec.origin).is_file():
            content = Path(spec.origin).read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", content)
            if m:
                return m.group(1)
    except Exception:
        pass
    try:
        return _get_yt_dlp().version.__version__
    except Exception:
        return "unknown"


from .hw_monitor import probe_working_encoders
from .models import Job, Settings
from .version import setup_bundled_environment

setup_bundled_environment()

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_ORIG_OS_REPLACE = os.replace
_ORIG_OS_RENAME = os.rename


def _safe_win_replace(src, dst, *, _is_rename: bool = False):
    """Windows-resilient file replace/rename that retries on transient WinError 5 / 32 locks
    (e.g. Windows Defender, Explorer thumbnail handler, or indexer scanning newly muxed `.temp.mp4` files).
    """
    fn = _ORIG_OS_RENAME if _is_rename else _ORIG_OS_REPLACE
    last_exc: Exception | None = None
    for attempt in range(16):
        try:
            return fn(src, dst)
        except PermissionError as exc:
            last_exc = exc
            time.sleep(0.08 + attempt * 0.04)
        except OSError as exc:
            if getattr(exc, "winerror", None) in (5, 32):
                last_exc = exc
                time.sleep(0.08 + attempt * 0.04)
            else:
                raise
    # Final fallback: copy bytes over destination and remove temp source
    try:
        src_p, dst_p = Path(os.fsdecode(src)), Path(os.fsdecode(dst))
        if src_p.is_file():
            shutil.copy2(src_p, dst_p)
            try:
                src_p.unlink()
            except OSError:
                pass
            return None
    except Exception:
        pass
    if last_exc is not None:
        raise last_exc
    return fn(src, dst)


if os.name == "nt" and getattr(os.replace, "__name__", "") != "_win_replace_wrapper":
    def _win_replace_wrapper(src, dst, *args, **kwargs):
        if not args and not kwargs:
            return _safe_win_replace(src, dst, _is_rename=False)
        return _ORIG_OS_REPLACE(src, dst, *args, **kwargs)

    def _win_rename_wrapper(src, dst, *args, **kwargs):
        if not args and not kwargs:
            return _safe_win_replace(src, dst, _is_rename=True)
        return _ORIG_OS_RENAME(src, dst, *args, **kwargs)

    os.replace = _win_replace_wrapper  # type: ignore[assignment]
    os.rename = _win_rename_wrapper    # type: ignore[assignment]


def send_to_trash(filepath: str | Path) -> bool:
    """Move a file or directory to the Windows Recycle Bin (with undo capability).
    Falls back to normal unlink/rmtree on non-Windows or if the shell API call fails.
    Returns True if successfully removed or moved to trash, False otherwise.
    """
    p = Path(filepath)
    if not p.exists():
        return False

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class _SHFILEOPSTRUCTW(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR),
                    ("fFlags", wintypes.WORD),
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", wintypes.LPVOID),
                    ("lpszProgressTitle", wintypes.LPCWSTR),
                ]

            FO_DELETE = 0x0003
            FOF_ALLOWUNDO = 0x0040
            FOF_NOCONFIRMATION = 0x0010
            FOF_SILENT = 0x0004
            FOF_NOERRORUI = 0x0400

            abs_path = str(p.resolve()) + "\0\0"
            fileop = _SHFILEOPSTRUCTW()
            fileop.hwnd = None
            fileop.wFunc = FO_DELETE
            fileop.pFrom = abs_path
            fileop.pTo = None
            fileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
            fileop.fAnyOperationsAborted = False
            fileop.hNameMappings = None
            fileop.lpszProgressTitle = None

            res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fileop))
            if res == 0 and not fileop.fAnyOperationsAborted and not p.exists():
                return True
        except Exception:
            pass

    # Fallback to standard removal if SHFileOperationW is unavailable, fails, or on non-Windows
    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink(missing_ok=True)
        return not p.exists()
    except Exception:
        return False



class DownloadCancelled(Exception):
    """Raised to interrupt a download or FFmpeg transcode."""


CODEC_LABELS = {
    "h264": "H.264",
    "avc1": "H.264",
    "h265": "H.265",
    "hevc": "H.265",
    "hev1": "H.265",
    "hvc1": "H.265",
    "av1": "AV1",
    "av01": "AV1",
    "vp9": "VP9",
    "vp09": "VP9",
    "auto": "Auto",
}

# Mapping from target job.video_codec to canonical ffprobe codec_name values
TARGET_TO_FFPROBE_CODECS = {
    "h264": {"h264", "avc1"},
    "h265": {"hevc", "h265", "hev1", "hvc1"},
    "av1": {"av1", "av01"},
    "vp9": {"vp9", "vp09"},
}


def normalize_codec_label(raw: str) -> str:
    val = (raw or "").strip().lower()
    if not val or val == "none":
        return ""
    for prefix, label in CODEC_LABELS.items():
        if val == prefix or val.startswith(prefix + "."):
            return label
    return val.upper()


def extract_youtube_video_id(url: str) -> str:
    """Extract canonical 11-character YouTube video ID from a URL if present, for collision detection."""
    try:
        parsed = urlparse((url or "").strip())
        host = (parsed.hostname or "").lower()
        if host == "youtu.be":
            vid = parsed.path.strip("/").split("/")[0]
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
                return vid
        if "youtube" in host:
            qs = parse_qs(parsed.query)
            if "v" in qs and qs["v"]:
                vid = qs["v"][0]
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
                    return vid
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v"):
                vid = parts[1]
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
                    return vid
    except Exception:
        pass
    return ""


def is_youtube_url(url: str) -> bool:
    try:
        obj = urlparse(url.strip())
        host = (obj.hostname or "").lower()
        return obj.scheme in ("http", "https") and (
            host in {"youtu.be", "youtube.com", "youtube-nocookie.com"}
            or host.endswith(".youtube.com")
            or host.endswith(".youtube-nocookie.com")
        )
    except ValueError:
        return False


_URL_TOKEN_RE = re.compile(
    r"(?:https?://[^\s,;<>\[\]\"'()]+|(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)/[^\s,;<>\[\]\"'()]+)",
    re.IGNORECASE,
)


def _is_meaningful_youtube_link(url: str) -> bool:
    if not is_youtube_url(url):
        return False
    if extract_youtube_video_id(url):
        return True
    parsed = urlparse(url.strip())
    path = (parsed.path or "").strip("/")
    qs = parse_qs(parsed.query)
    if "list" in qs and qs["list"]:
        return True
    if path and path.lower() not in ("", "watch", "playlist"):
        return True
    return False


def extract_youtube_urls(raw_text: str) -> tuple[list[str], int, int]:
    """Extract and deduplicate valid YouTube URLs from arbitrary single/multi-line text.

    Returns:
        (valid_unique_urls, duplicate_count, invalid_count)
    """
    if not raw_text or not raw_text.strip():
        return [], 0, 0

    valid_urls: list[str] = []
    seen_keys: set[str] = set()
    duplicate_count = 0
    invalid_count = 0

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        matches = _URL_TOKEN_RE.findall(line)
        if not matches:
            invalid_count += 1
            continue

        line_valid_found = 0
        for token in matches:
            cleaned = token.rstrip(".,;!?)]}'\"")
            if not cleaned.lower().startswith(("http://", "https://")):
                cleaned = "https://" + cleaned
            if not _is_meaningful_youtube_link(cleaned):
                invalid_count += 1
                continue
            line_valid_found += 1
            vid = extract_youtube_video_id(cleaned)
            dedup_key = f"vid:{vid}" if vid else cleaned
            if dedup_key in seen_keys:
                duplicate_count += 1
            else:
                seen_keys.add(dedup_key)
                valid_urls.append(cleaned)

    return valid_urls, duplicate_count, invalid_count


def friendly_size(size) -> str:
    try:
        size = float(size)
        if size < 0:
            return "—"
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}"
            size /= 1024
    except (TypeError, ValueError):
        return "—"
    return "—"


def friendly_eta(value) -> str:
    try:
        sec = int(value)
        if sec < 0:
            return "—"
        hours, rem = divmod(sec, 3600)
        minutes, seconds = divmod(rem, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
    except (TypeError, ValueError):
        return "—"


def parse_timestamp_seconds(text: str) -> float | None:
    """Parse 'SS', 'MM:SS', or 'HH:MM:SS' into total seconds. Return None if empty."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    parts = cleaned.split(":")
    if len(parts) > 3:
        raise ValueError("Định dạng thời gian không hợp lệ (hãy dùng MM:SS hoặc HH:MM:SS)")
    try:
        nums = [float(p) for p in parts]
    except ValueError as exc:
        raise ValueError("Định dạng thời gian không hợp lệ (hãy dùng MM:SS hoặc HH:MM:SS)") from exc
    if any(n < 0 for n in nums):
        raise ValueError("Thời gian cắt không được âm")
    total = 0.0
    for n in nums:
        total = total * 60.0 + n
    return total


def _safe_format_id(value: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,90}", value or ""):
        raise ValueError("Mã định dạng không hợp lệ")
    return value


def build_format(job: Job) -> str:
    """Build yt-dlp format selector.
    When a specific video_codec (e.g. h264, h265, av1, vp9) is requested without an explicit format_id:
    - If a resolution cap is specified (e.g. 1080p), prefer a stream with that target codec at that resolution first,
      then fall back to any stream at that resolution (FFmpeg will transcode afterward if needed).
    - If quality is 'best', prefer the highest resolution available, while preferring the target codec if tied
      (reinforced via `format_sort` in `download_media`).
    - If `job.mute_audio` is True, select video-only (`bv*`) streams without merging audio (`+ba`).
    """
    mute = bool(getattr(job, "mute_audio", False))

    if job.format_id:
        fmt = _safe_format_id(job.format_id)
        if job.mode == "audio" or job.format_has_audio or mute:
            return fmt
        ext = job.format_ext
        if ext == "mp4" or job.container == "mp4":
            return f"{fmt}+ba[ext=m4a]"
        if ext == "webm" or job.container == "webm":
            return f"{fmt}+ba[ext=webm]"
        return f"{fmt}+ba"

    if job.mode == "audio":
        return "bestaudio"

    limiter = ""
    if job.quality not in ("best", ""):
        if not str(job.quality).isdigit():
            raise ValueError("Giới hạn độ phân giải không hợp lệ")
        limiter = f"[height<={int(job.quality)}]"

    target_codec = (job.video_codec or "auto").lower()
    vcodec_filter = ""
    if target_codec == "h264":
        vcodec_filter = "[vcodec^=avc1]"
    elif target_codec == "h265":
        vcodec_filter = "[vcodec^=hev1]"
    elif target_codec == "av1":
        vcodec_filter = "[vcodec^=av01]"
    elif target_codec == "vp9":
        vcodec_filter = "[vcodec^=vp9]"

    if mute:
        if target_codec == "auto" or not vcodec_filter:
            if job.container == "mp4":
                return f"bv*[ext=mp4]{limiter}/b[ext=mp4]{limiter}/bv*{limiter}/b{limiter}"
            if job.container == "webm":
                return f"bv*[ext=webm]{limiter}/b[ext=webm]{limiter}/bv*{limiter}/b{limiter}"
            return f"bv*{limiter}/b{limiter}"

        if job.container == "mp4":
            if limiter:
                return (
                    f"bv*{vcodec_filter}{limiter}/"
                    f"bv*[ext=mp4]{limiter}/"
                    f"bv*{limiter}/"
                    f"b[ext=mp4]{limiter}/b{limiter}"
                )
            return "bv*[ext=mp4]/bv*/b"
        if job.container == "webm":
            if limiter:
                return (
                    f"bv*{vcodec_filter}{limiter}/"
                    f"bv*[ext=webm]{limiter}/"
                    f"bv*{limiter}/b{limiter}"
                )
            return "bv*[ext=webm]/bv*/b"
        if limiter:
            return f"bv*{vcodec_filter}{limiter}/bv*{limiter}/b{limiter}"
        return "bv*/b"

    # When user leaves codec as 'auto' (or legacy behavior):
    if target_codec == "auto" or not vcodec_filter:
        if job.container == "mp4":
            return f"bv*[ext=mp4]{limiter}+ba[ext=m4a]/b[ext=mp4]{limiter}"
        if job.container == "webm":
            return f"bv*[ext=webm]{limiter}+ba[ext=webm]/b[ext=webm]{limiter}"
        return f"bv*{limiter}+ba/b{limiter}"

    if job.container == "mp4":
        if limiter:
            return (
                f"bv*{vcodec_filter}{limiter}+ba[ext=m4a]/"
                f"bv*[ext=mp4]{limiter}+ba[ext=m4a]/"
                f"bv*{limiter}+ba/"
                f"b[ext=mp4]{limiter}/b{limiter}"
            )
        return (
            "bv*[ext=mp4]+ba[ext=m4a]/"
            "bv*+ba/b"
        )
    if job.container == "webm":
        if limiter:
            return (
                f"bv*{vcodec_filter}{limiter}+ba[ext=webm]/"
                f"bv*[ext=webm]{limiter}+ba[ext=webm]/"
                f"bv*{limiter}+ba/b{limiter}"
            )
        return "bv*[ext=webm]+ba[ext=webm]/bv*+ba/b"

    if limiter:
        return f"bv*{vcodec_filter}{limiter}+ba/bv*{limiter}+ba/b{limiter}"
    return "bv*+ba/b"


def metadata_view(info: dict) -> dict:
    formats = []
    for f in info.get("formats") or []:
        if not isinstance(f, dict):
            continue
        v = f.get("vcodec") or "none"
        a = f.get("acodec") or "none"
        if v == "none" and a == "none":
            continue
        height = f.get("height") or 0
        fps = f.get("fps") or 0
        bitrate = f.get("tbr") or f.get("abr") or 0
        formats.append({
            "id": str(f.get("format_id") or ""),
            "ext": str(f.get("ext") or ""),
            "resolution": f"{height}p" if height else "Chỉ audio",
            "height": height,
            "fps": str(round(fps, 1)) if fps else "—",
            "video": v,
            "audio": a,
            "bitrate": f"{bitrate:.0f} kb/s" if isinstance(bitrate, (int, float)) and bitrate else "—",
            "size": friendly_size(f.get("filesize") or f.get("filesize_approx")),
            "has_audio": a != "none",
            "has_video": v != "none",
        })
    return {
        "url": info.get("webpage_url") or "",
        "title": info.get("title") or "Không có tiêu đề",
        "channel": info.get("channel") or info.get("uploader") or "",
        "duration": friendly_eta(info.get("duration")),
        "thumbnail": info.get("thumbnail") or "",
        "id": str(info.get("id") or ""),
        "formats": formats,
    }


def _entry_url(entry: dict) -> str:
    for key in ("webpage_url", "url"):
        candidate = entry.get(key)
        if isinstance(candidate, str) and is_youtube_url(candidate):
            return candidate
    raw_id = str(entry.get("id") or "")
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw_id):
        return f"https://www.youtube.com/watch?v={raw_id}"
    return ""


_SUPPORTED_COOKIE_BROWSERS = ("firefox", "edge", "brave", "chrome", "opera", "vivaldi")


def _is_bot_auth_error(exc: Exception) -> bool:
    msg = str(exc or "").lower()
    return (
        "not a bot" in msg
        or "sign in to confirm" in msg
        or "--cookies-from-browser" in msg
        or "confirm your age" in msg
    )


def _run_ytdlp_extract_with_fallback(
    base_options: dict,
    url: str,
    *,
    download: bool,
    cookies_from_browser: str = "auto",
    log=None,
) -> dict:
    """Run `yt_dlp.YoutubeDL(options).extract_info(url, download=download)` with automatic
    multi-stage fallback if YouTube triggers a 'Sign in to confirm you're not a bot' check:
      1. Try initial `base_options` (which already includes `cookiefile` or explicit `cookiesfrombrowser` if set).
      2. On bot-check error, retry with embedded/TV Innertube clients (`web_embedded`, `mweb`, `tv`).
      3. If still blocked and no `cookiefile` is set, try browser cookies (`firefox`, `edge`, `brave`, `chrome`).
    """
    browser_pref = (cookies_from_browser or "").strip().lower()
    initial_opts = dict(base_options)
    if not initial_opts.get("cookiefile") and browser_pref in _SUPPORTED_COOKIE_BROWSERS:
        initial_opts["cookiesfrombrowser"] = (browser_pref,)

    ytd = _get_yt_dlp()
    try:
        with ytd.YoutubeDL(initial_opts) as ydl:
            res = ydl.extract_info(url, download=download)
            if isinstance(res, dict):
                return res
            raise RuntimeError("Không nhận được dữ liệu phản hồi từ YouTube")
    except Exception as first_exc:
        if not _is_bot_auth_error(first_exc):
            raise

        if log:
            log("YouTube yêu cầu xác minh chống Bot — đang tự động thử luồng dự phòng (Embedded/TV Client)...")

        # Fallback Stage 1: Embedded / TV player clients
        try:
            alt_opts = dict(initial_opts)
            ext_args = dict(alt_opts.get("extractor_args") or {})
            yt_args = dict(ext_args.get("youtube") or {})
            yt_args["player_client"] = ["web_embedded", "tv", "mweb"]
            ext_args["youtube"] = yt_args
            alt_opts["extractor_args"] = ext_args
            with ytd.YoutubeDL(alt_opts) as ydl:
                res = ydl.extract_info(url, download=download)
                if isinstance(res, dict):
                    return res
        except Exception as alt_exc:
            if not _is_bot_auth_error(alt_exc):
                raise

        # Fallback Stage 2: Automatic browser cookies if allowed
        if not initial_opts.get("cookiefile") and browser_pref != "":
            candidates = (
                [browser_pref]
                if browser_pref in _SUPPORTED_COOKIE_BROWSERS
                else ["firefox", "edge", "brave", "chrome"]
            )
            for b_name in candidates:
                try:
                    if log:
                        log(f"Đang thử tự động xác thực Cookie từ trình duyệt {b_name.title()}...")
                    b_opts = dict(base_options)
                    b_opts["cookiesfrombrowser"] = (b_name,)
                    with ytd.YoutubeDL(b_opts) as ydl:
                        res = ydl.extract_info(url, download=download)
                        if isinstance(res, dict):
                            if log:
                                log(f"Xác thực thành công bằng Cookie trình duyệt {b_name.title()}!")
                            return res
                except Exception:
                    continue

        raise RuntimeError(
            "YouTube yêu cầu xác minh chống Bot trên mạng này. "
            "Cách khắc phục: Mở Cài đặt → chọn 'Lấy Cookie từ trình duyệt' (ưu tiên Firefox, hoặc đóng Edge/Chrome trước khi tải) "
            "hoặc nạp tệp cookies.txt (Netscape)."
        ) from first_exc


def inspect_url(
    url: str,
    playlist: bool = False,
    max_entries: int = 150,
    cookie_file: str = "",
    cookies_from_browser: str = "auto",
) -> dict:
    if not is_youtube_url(url):
        raise ValueError("Chỉ chấp nhận URL YouTube hợp lệ (https://youtube.com hoặc youtu.be)")
    options: dict = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": not playlist,
        "extract_flat": "in_playlist" if playlist else False,
        "playlistend": max_entries if playlist else None,
        "socket_timeout": 20,
        "retries": 3,
    }
    if cookie_file:
        c_path = Path(cookie_file).expanduser()
        if c_path.is_file():
            options["cookiefile"] = str(c_path)
    info = _run_ytdlp_extract_with_fallback(
        options,
        url,
        download=False,
        cookies_from_browser=cookies_from_browser,
    )
    if not isinstance(info, dict):
        raise ValueError("YouTube không trả về dữ liệu video")
    if info.get("_type") in ("playlist", "multi_video") or (playlist and "entries" in info):
        entries = []
        for item in info.get("entries") or []:
            if not isinstance(item, dict):
                continue
            video_url = _entry_url(item)
            if video_url:
                entries.append({
                    "url": video_url,
                    "title": item.get("title") or video_url,
                    "thumbnail": item.get("thumbnail") or "",
                })
            if len(entries) >= max_entries:
                break
        if not entries:
            raise ValueError("Không tìm thấy video có thể thêm vào hàng đợi")
        return {
            "type": "playlist",
            "title": info.get("title") or "Playlist",
            "thumbnail": info.get("thumbnail") or "",
            "entries": entries,
        }
    return {"type": "video", "video": metadata_view(info)}


class SignalLogger:
    def __init__(self, report):
        self.report = report

    def debug(self, msg):
        if not msg.startswith("[debug]") and ("Destination" in msg or "Merging" in msg):
            self.report(msg)

    def info(self, msg):
        if msg:
            self.report(str(msg))

    def warning(self, msg):
        self.report("Cảnh báo: " + str(msg))

    def error(self, msg):
        self.report("Lỗi: " + str(msg))


def _format_fps_str(raw_fps: str | float | int) -> str:
    try:
        s = str(raw_fps or "").strip()
        if not s or s in ("0/0", "0", "N/A"):
            return ""
        if "/" in s:
            num_s, den_s = s.split("/", 1)
            den = float(den_s)
            if den <= 0:
                return ""
            val = float(num_s) / den
        else:
            val = float(s)
        if val <= 0 or val > 1000:
            return ""
        rounded = round(val)
        if abs(val - rounded) < 0.08:
            return f"{rounded}fps"
        return f"{val:.2f}fps"
    except Exception:
        return ""


def probe_media_info(filepath: Path) -> dict[str, str | float]:
    """Inspect actual video codec, audio codec, duration (seconds), resolution, fps, and bitrate
    using ffprobe, with automatic fallback to `ffmpeg -i` stderr parsing if ffprobe is unavailable.
    """
    if not filepath.is_file():
        return {
            "video_codec": "",
            "audio_codec": "",
            "duration": 0.0,
            "resolution": "",
            "fps": "",
            "bitrate": "",
        }

    vcodec = ""
    acodec = ""
    duration = 0.0
    resolution = ""
    fps_str = ""
    bitrate_str = ""

    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            res = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type,codec_name,width,height,r_frame_rate,avg_frame_rate,bit_rate:format=duration,bit_rate",
                    "-of",
                    "json",
                    str(filepath),
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            if res.returncode == 0 and res.stdout:
                data = json.loads(res.stdout)
                v_br = 0
                a_br = 0
                for stream in data.get("streams") or []:
                    stype = stream.get("codec_type")
                    sname = (stream.get("codec_name") or "").lower()
                    if stype == "video" and not vcodec:
                        vcodec = sname
                        w = int(stream.get("width") or 0)
                        h = int(stream.get("height") or 0)
                        if w > 0 and h > 0:
                            resolution = f"{w}x{h}"
                        fps_str = _format_fps_str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "")
                        if not fps_str:
                            fps_str = _format_fps_str(stream.get("r_frame_rate") or "")
                        try:
                            v_br = int(stream.get("bit_rate") or 0)
                        except Exception:
                            pass
                    elif stype == "audio" and not acodec:
                        acodec = sname
                        try:
                            a_br = int(stream.get("bit_rate") or 0)
                        except Exception:
                            pass
                fmt_obj = data.get("format") or {}
                dur_raw = fmt_obj.get("duration")
                if dur_raw and str(dur_raw) != "N/A":
                    duration = float(dur_raw)
                try:
                    fmt_br = int(fmt_obj.get("bit_rate") or 0)
                except Exception:
                    fmt_br = 0
                best_bps = fmt_br or (v_br + a_br) or v_br or a_br
                if best_bps > 0:
                    bitrate_str = f"{max(1, round(best_bps / 1000))} kbps"
        except Exception:
            pass

    # Fallback to `ffmpeg -i` if ffprobe was missing or didn't report codec/duration/resolution
    if not vcodec or duration <= 0.0 or not resolution or not bitrate_str:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            try:
                res = subprocess.run(
                    [ffmpeg, "-nostdin", "-hide_banner", "-i", str(filepath)],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    creationflags=CREATE_NO_WINDOW,
                )
                text = (res.stderr or "") + "\n" + (res.stdout or "")
                if not vcodec:
                    m_v = re.search(r"Stream #\d+:\d+.*?Video:\s*([a-zA-Z0-9_]+)", text)
                    if m_v:
                        vcodec = m_v.group(1).lower()
                if not resolution:
                    m_res = re.search(r"Stream #\d+:\d+.*?Video:.*?,\s*(\d{2,5}x\d{2,5})\b", text)
                    if m_res:
                        resolution = m_res.group(1)
                if not fps_str:
                    m_fps = re.search(r"Stream #\d+:\d+.*?Video:.*?,\s*(\d+(?:\.\d+)?)\s*fps\b", text)
                    if m_fps:
                        fps_str = _format_fps_str(m_fps.group(1))
                if not acodec:
                    m_a = re.search(r"Stream #\d+:\d+.*?Audio:\s*([a-zA-Z0-9_]+)", text)
                    if m_a:
                        acodec = m_a.group(1).lower()
                if duration <= 0.0:
                    m_d = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
                    if m_d:
                        duration = int(m_d.group(1)) * 3600 + int(m_d.group(2)) * 60 + float(m_d.group(3))
                if not bitrate_str:
                    m_br = re.search(r"bitrate:\s*(\d+)\s*kb/s", text, re.IGNORECASE)
                    if m_br:
                        bitrate_str = f"{int(m_br.group(1))} kbps"
            except Exception:
                pass

    return {
        "video_codec": vcodec,
        "audio_codec": acodec,
        "duration": duration,
        "resolution": resolution,
        "fps": fps_str,
        "bitrate": bitrate_str,
    }


def get_cached_encoders() -> dict[str, list[str]]:
    return probe_working_encoders()


def select_encoder_candidates(target_codec: str, hw_accel: str = "auto") -> list[tuple[str, list[str]]]:
    """Return ordered list of (encoder_name, extra_ffmpeg_args) to try for target_codec."""
    working = get_cached_encoders().get(target_codec, [])
    hw_pref = (hw_accel or "auto").lower()

    def build_args(enc: str) -> list[str]:
        if enc == "h264_nvenc":
            return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "21", "-pix_fmt", "yuv420p"]
        if enc == "h264_qsv":
            return ["-c:v", "h264_qsv", "-global_quality", "21", "-pix_fmt", "nv12"]
        if enc == "h264_amf":
            return ["-c:v", "h264_amf", "-quality", "balanced", "-pix_fmt", "yuv420p"]
        if enc == "libx264":
            return ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p"]

        if enc == "hevc_nvenc":
            return ["-c:v", "hevc_nvenc", "-preset", "p4", "-cq", "23", "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]
        if enc == "hevc_qsv":
            return ["-c:v", "hevc_qsv", "-global_quality", "23", "-pix_fmt", "nv12", "-tag:v", "hvc1"]
        if enc == "hevc_amf":
            return ["-c:v", "hevc_amf", "-quality", "balanced", "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]
        if enc == "libx265":
            return ["-c:v", "libx265", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]

        if enc == "av1_nvenc":
            return ["-c:v", "av1_nvenc", "-preset", "p4", "-cq", "26", "-pix_fmt", "yuv420p"]
        if enc == "av1_qsv":
            return ["-c:v", "av1_qsv", "-global_quality", "26", "-pix_fmt", "nv12"]
        if enc == "av1_amf":
            return ["-c:v", "av1_amf", "-pix_fmt", "yuv420p"]
        if enc == "libsvtav1":
            return ["-c:v", "libsvtav1", "-preset", "8", "-crf", "28", "-pix_fmt", "yuv420p"]

        if enc == "vp9_qsv":
            return ["-c:v", "vp9_qsv", "-pix_fmt", "nv12"]
        if enc == "libvpx-vp9":
            return ["-c:v", "libvpx-vp9", "-crf", "28", "-b:v", "0", "-deadline", "good", "-cpu-used", "2", "-pix_fmt", "yuv420p"]

        return ["-c:v", enc]

    fallback_sw = {
        "h264": "libx264",
        "h265": "libx265",
        "av1": "libsvtav1",
        "vp9": "libvpx-vp9",
    }.get(target_codec, "libx264")

    ordered: list[str] = []
    if hw_pref == "cpu":
        ordered.append(fallback_sw)
    elif hw_pref in {"nvenc", "qsv", "amf"}:
        for enc in working:
            if hw_pref in enc:
                ordered.append(enc)
        for enc in working:
            if enc not in ordered:
                ordered.append(enc)
    else:
        ordered.extend(working)

    if fallback_sw not in ordered:
        ordered.append(fallback_sw)

    return [(enc, build_args(enc)) for enc in ordered]


def ensure_video_codec(
    filepath: Path,
    job: Job,
    settings: Settings,
    control,
    progress,
    log,
    force_transcode: bool = False,
    clip_range: tuple[float | None, float | None] = (None, None),
    known_duration: float = 0.0,
    known_vcodec: str = "",
) -> tuple[Path, str]:
    """Verify if `filepath` matches `job.video_codec` (or apply clip trimming if requested).
    If not matching, transcode with FFmpeg (using GPU acceleration with CPU fallback) and emit real-time progress.
    Returns (final_filepath, detected_codec_label).
    """
    info = probe_media_info(filepath)
    actual_vcodec = str(info.get("video_codec") or known_vcodec or "").lower()
    actual_acodec = str(info.get("audio_codec") or "").lower()
    duration = float(info.get("duration") or 0.0) or float(known_duration or 0.0)
    if info.get("resolution"):
        job.detected_resolution = str(info["resolution"])
    if info.get("fps"):
        job.detected_fps = str(info["fps"])
    if info.get("bitrate"):
        job.detected_bitrate = str(info["bitrate"])

    target = (job.video_codec or "auto").lower()
    start_sec, end_sec = clip_range
    needs_trim = start_sec is not None or end_sec is not None

    if job.mode == "audio":
        if not needs_trim:
            return filepath, normalize_codec_label(actual_acodec or job.container)
        trimmed = _run_ffmpeg_trim_only(filepath, start_sec, end_sec, duration, control, progress, log)
        return trimmed, normalize_codec_label(actual_acodec or job.container)

    accepted_names = TARGET_TO_FFPROBE_CODECS.get(target, set())
    codec_matches = (target == "auto") or any(
        actual_vcodec == name or actual_vcodec.startswith(name + ".")
        for name in accepted_names
    )
    mute = bool(getattr(job, "mute_audio", False))
    has_audio_stream = actual_acodec not in ("", "none")

    if codec_matches and not force_transcode:
        if needs_trim or (mute and has_audio_stream):
            trimmed = _run_ffmpeg_trim_only(
                filepath,
                start_sec,
                end_sec,
                duration,
                control,
                progress,
                log,
                strip_audio=mute,
            )
            post_info = probe_media_info(trimmed)
            if post_info.get("bitrate"):
                job.detected_bitrate = str(post_info["bitrate"])
            return trimmed, normalize_codec_label(actual_vcodec or target)
        return filepath, normalize_codec_label(actual_vcodec or target)

    # Need to transcode to target codec!
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log("Cảnh báo: Không tìm thấy FFmpeg để chuyển đổi codec; giữ nguyên file gốc.")
        return filepath, normalize_codec_label(actual_vcodec)

    if target == "auto":
        target = "h264"

    target_ext = job.container if job.container in ("mp4", "mkv", "webm") else filepath.suffix.lstrip(".") or "mp4"
    # WebM only supports VP8/VP9/AV1. If user chose H.264/H.265 with WebM, output as MP4.
    if target in ("h264", "h265") and target_ext == "webm":
        target_ext = "mp4"

    out_path = filepath.with_suffix(f".{target_ext}")
    temp_out = filepath.with_name(f"{filepath.stem}.transcode_temp.{target_ext}")

    # Calculate expected output duration when trimming
    effective_duration = duration
    if start_sec is not None and end_sec is not None and end_sec > start_sec:
        effective_duration = end_sec - start_sec
    elif start_sec is not None and duration > start_sec:
        effective_duration = duration - start_sec
    elif end_sec is not None:
        effective_duration = end_sec

    candidates = select_encoder_candidates(target, settings.hw_accel)
    last_error = ""

    for enc_name, v_args in candidates:
        if temp_out.exists():
            try:
                temp_out.unlink()
            except OSError:
                pass

        is_gpu = any(tag in enc_name for tag in ("nvenc", "qsv", "amf"))
        accel_badge = "GPU" if is_gpu else "CPU"
        codec_display = CODEC_LABELS.get(target, target.upper())
        log(f"Đang chuyển đổi Codec ({actual_vcodec or 'nguồn'} → {codec_display}) bằng {enc_name} ({accel_badge})...")

        cmd = [ffmpeg, "-nostdin", "-y", "-hide_banner"]
        if start_sec is not None and start_sec > 0:
            cmd.extend(["-ss", f"{start_sec:.2f}"])
        cmd.extend(["-i", str(filepath)])
        if end_sec is not None and end_sec > 0:
            clip_dur = end_sec - (start_sec or 0.0)
            if clip_dur > 0:
                cmd.extend(["-t", f"{clip_dur:.2f}"])

        # Ensure even dimensions (required by NVENC/AMF/x264/x265 for Shorts/vertical videos)
        cmd.extend(["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"])
        cmd.extend(v_args)
        cmd.extend(["-map_metadata", "0"])

        # Audio stream compatibility (or strip audio when mute_audio is enabled)
        if mute:
            cmd.append("-an")
        elif target_ext == "mp4" and actual_acodec not in {"aac", "mp3", "alac", ""}:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])

        if target_ext == "mp4":
            cmd.extend(["-movflags", "+faststart"])

        cmd.extend(["-progress", "pipe:1", "-nostats", str(temp_out)])

        success, err_text = _execute_ffmpeg_with_progress(
            cmd,
            effective_duration,
            f"Đang đổi {codec_display} ({accel_badge})",
            control,
            progress,
            temp_out,
        )
        if success and temp_out.is_file() and temp_out.stat().st_size > 0:
            try:
                if filepath.exists() and filepath != out_path:
                    filepath.unlink()
                os.replace(temp_out, out_path)
            except OSError:
                out_path = temp_out
            post_info = probe_media_info(out_path)
            if post_info.get("resolution"):
                job.detected_resolution = str(post_info["resolution"])
            if post_info.get("fps"):
                job.detected_fps = str(post_info["fps"])
            if post_info.get("bitrate"):
                job.detected_bitrate = str(post_info["bitrate"])
            log(f"Hoàn tất chuyển đổi sang {codec_display} ({enc_name}).")
            return out_path, codec_display
        last_error = err_text
        log(f"Bộ mã hóa {enc_name} không khả dụng ({err_text[-140:].strip() if err_text else 'lỗi'}), đang thử phương án dự phòng...")

    if temp_out.exists():
        try:
            temp_out.unlink()
        except OSError:
            pass
    raise RuntimeError(f"Không thể chuyển đổi sang codec {target.upper()}: {last_error[-300:]}")


def _run_ffmpeg_trim_only(
    filepath: Path,
    start_sec: float | None,
    end_sec: float | None,
    duration: float,
    control,
    progress,
    log,
    *,
    strip_audio: bool = False,
) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return filepath
    temp_out = filepath.with_name(f"{filepath.stem}.trim_temp{filepath.suffix}")
    cmd = [ffmpeg, "-nostdin", "-y", "-hide_banner"]
    if start_sec is not None and start_sec > 0:
        cmd.extend(["-ss", f"{start_sec:.2f}"])
    cmd.extend(["-i", str(filepath)])
    if end_sec is not None and end_sec > 0:
        clip_dur = end_sec - (start_sec or 0.0)
        if clip_dur > 0:
            cmd.extend(["-t", f"{clip_dur:.2f}"])
    if strip_audio:
        cmd.extend(["-c:v", "copy", "-an"])
    else:
        cmd.extend(["-c", "copy"])
    cmd.extend(["-progress", "pipe:1", "-nostats", str(temp_out)])
    eff_dur = (end_sec - (start_sec or 0.0)) if end_sec else max(1.0, duration - (start_sec or 0.0))
    stage_lbl = "Đang xóa âm thanh" if (strip_audio and start_sec is None and end_sec is None) else "Đang cắt đoạn"
    ok, _ = _execute_ffmpeg_with_progress(cmd, eff_dur, stage_lbl, control, progress, temp_out)
    if ok and temp_out.is_file() and temp_out.stat().st_size > 0:
        os.replace(temp_out, filepath)
        log("Đã xóa âm thanh khỏi video thành công." if strip_audio else "Đã cắt đoạn media thành công.")
    elif temp_out.exists():
        try:
            temp_out.unlink()
        except OSError:
            pass
    return filepath


def _parse_ffmpeg_out_time(val: str) -> float | None:
    """Parse `out_time=HH:MM:SS.mmmmmm` into seconds."""
    m = re.match(r"(\d+):(\d+):(\d+(?:\.\d+)?)", (val or "").strip())
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def _execute_ffmpeg_with_progress(
    cmd: list[str],
    total_duration: float,
    stage_label: str,
    control,
    progress,
    temp_file: Path,
) -> tuple[bool, str]:
    """Run an FFmpeg command with `-progress pipe:1`, draining BOTH stdout and stderr in daemon threads
    so FFmpeg can never deadlock on a full pipe buffer and cancel/pause responds within 0.2s.
    """
    progress({"status": "converting", "progress": 1.0, "speed": stage_label, "eta": "—"})
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )

    stdout_q: queue.Queue[str | None] = queue.Queue()
    stderr_lines: deque[str] = deque(maxlen=80)
    inferred_duration = float(total_duration or 0.0)

    def _read_stdout():
        try:
            if proc.stdout:
                for line in proc.stdout:
                    stdout_q.put(line)
        except Exception:
            pass
        finally:
            stdout_q.put(None)

    def _read_stderr():
        nonlocal inferred_duration
        try:
            if proc.stderr:
                for line in proc.stderr:
                    s = line.strip()
                    if s:
                        stderr_lines.append(s)
                        if inferred_duration <= 0.0 and "Duration:" in s:
                            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", s)
                            if m:
                                inferred_duration = (
                                    int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                                )
        except Exception:
            pass

    t_out = threading.Thread(target=_read_stdout, daemon=True)
    t_err = threading.Thread(target=_read_stderr, daemon=True)
    t_out.start()
    t_err.start()

    speed_str = ""
    fps_str = ""
    last_sec = 0.0
    eof_reached = False

    def _cleanup_on_cancel():
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            pass
        if temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass

    try:
        while not eof_reached:
            if control.cancel_event.is_set():
                _cleanup_on_cancel()
                raise DownloadCancelled("Người dùng hủy trong lúc chuyển đổi FFmpeg")

            while not control.run_event.wait(timeout=0.2):
                if control.cancel_event.is_set():
                    _cleanup_on_cancel()
                    raise DownloadCancelled("Người dùng hủy")

            try:
                raw_line = stdout_q.get(timeout=0.2)
            except queue.Empty:
                if proc.poll() is not None and stdout_q.empty():
                    break
                continue

            if raw_line is None:
                eof_reached = True
                break

            line = raw_line.strip()
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()

            if key == "fps" and val and val not in ("0.0", "0", "N/A"):
                fps_str = f"{val} fps"
            elif key == "speed" and val and val != "N/A":
                speed_str = val
            elif key in ("out_time_us", "out_time_ms"):
                try:
                    sec = int(val) / 1_000_000.0
                    if sec > 0:
                        last_sec = sec
                except ValueError:
                    pass
            elif key == "out_time" and val and val != "N/A":
                parsed_t = _parse_ffmpeg_out_time(val)
                if parsed_t is not None and parsed_t > 0:
                    last_sec = parsed_t
            elif key == "progress":
                eff_dur = inferred_duration if inferred_duration > 0 else total_duration
                if val == "end":
                    pct = 99.5
                elif eff_dur > 0 and last_sec > 0:
                    pct = min(99.5, max(1.0, 100.0 * last_sec / eff_dur))
                else:
                    pct = min(95.0, max(5.0, last_sec))
                eta_str = "—"
                if speed_str.endswith("x") and eff_dur > last_sec > 0:
                    try:
                        sp_mult = float(speed_str[:-1])
                        if sp_mult > 0:
                            eta_str = friendly_eta((eff_dur - last_sec) / sp_mult)
                    except ValueError:
                        pass
                metric_display = stage_label
                if fps_str or speed_str:
                    extra = " • ".join(x for x in (fps_str, speed_str) if x)
                    metric_display = f"{stage_label} ({extra})"
                progress({
                    "status": "converting",
                    "progress": round(pct, 1),
                    "speed": metric_display,
                    "eta": eta_str,
                })

        # Wait for FFmpeg to finish flushing/muxing (e.g. +faststart moov atom), while staying responsive to cancel
        wait_deadline = time.monotonic() + 180.0
        while proc.poll() is None:
            if control.cancel_event.is_set():
                _cleanup_on_cancel()
                raise DownloadCancelled("Người dùng hủy")
            if time.monotonic() > wait_deadline:
                proc.kill()
                break
            time.sleep(0.15)

        t_err.join(timeout=1.0)
        stderr_out = "\n".join(stderr_lines)
        return proc.returncode == 0, stderr_out
    except DownloadCancelled:
        raise
    except Exception as exc:
        try:
            proc.kill()
        except Exception:
            pass
        return False, str(exc)
    finally:
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except Exception:
                    pass
        try:
            proc.wait(timeout=1.0)
        except Exception:
            pass


def transcode_existing_job(job: Job, target_codec: str, settings: Settings, control, progress, log) -> str:
    """Transcode an already-downloaded video file on disk to `target_codec` (h264, h265, av1, vp9),
    or strip its audio track in-place when `target_codec == 'mute'`.
    """
    if not job.filepath or not Path(job.filepath).is_file():
        raise ValueError("Không tìm thấy file gốc trên ổ đĩa để xử lý")
    src_path = Path(job.filepath)
    if target_codec == "mute":
        info = probe_media_info(src_path)
        dur = float(info.get("duration") or 0.0)
        out_path = _run_ffmpeg_trim_only(
            src_path,
            None,
            None,
            dur,
            control,
            progress,
            log,
            strip_audio=True,
        )
        job.mute_audio = True
        post_info = probe_media_info(out_path)
        if post_info.get("bitrate"):
            job.detected_bitrate = str(post_info["bitrate"])
        return str(out_path)
    job.video_codec = target_codec
    out_path, codec_label = ensure_video_codec(
        src_path,
        job,
        settings,
        control,
        progress,
        log,
        force_transcode=True,
    )
    job.detected_codec = codec_label
    return str(out_path)


def download_media(job: Job, settings: Settings, control, progress, log) -> str:
    """Synchronous function; must be invoked by a worker thread."""
    if not is_youtube_url(job.url):
        raise ValueError("URL YouTube không hợp lệ")
    path = Path(job.directory).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    path = path.resolve()

    start_sec = parse_timestamp_seconds(job.clip_start)
    end_sec = parse_timestamp_seconds(job.clip_end)
    if start_sec is not None and end_sec is not None and end_sec <= start_sec:
        raise ValueError("Thời gian kết thúc cắt đoạn phải lớn hơn thời gian bắt đầu")

    def checkpoint():
        if control.cancel_event.is_set():
            raise DownloadCancelled("Người dùng hủy")
        while not control.run_event.wait(timeout=0.2):
            if control.cancel_event.is_set():
                raise DownloadCancelled("Người dùng hủy")
        if control.cancel_event.is_set():
            raise DownloadCancelled("Người dùng hủy")

    def progress_hook(data):
        checkpoint()
        status = data.get("status")
        info_dict = data.get("info_dict") or {}
        hook_title = info_dict.get("title") or ""
        hook_thumb = info_dict.get("thumbnail") or ""
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            received = data.get("downloaded_bytes") or 0
            percent = min(99.0, 100.0 * received / total) if total else 0.0
            payload = {
                "status": "downloading",
                "progress": round(percent, 1),
                "speed": friendly_size(data.get("speed")) + "/s" if data.get("speed") else "—",
                "eta": friendly_eta(data.get("eta")),
                "size": friendly_size(total) if total else "—",
            }
            if hook_title:
                payload["title"] = str(hook_title)
            if hook_thumb:
                payload["thumbnail_url"] = str(hook_thumb)
            progress(payload)
        elif status == "finished":
            payload = {"status": "processing", "progress": 99.0, "speed": "—", "eta": "—"}
            if hook_title:
                payload["title"] = str(hook_title)
            if hook_thumb:
                payload["thumbnail_url"] = str(hook_thumb)
            progress(payload)

    def postprocessor_hook(data):
        checkpoint()
        info_dict = data.get("info_dict") or {}
        hook_title = info_dict.get("title") or ""
        hook_thumb = info_dict.get("thumbnail") or ""
        if data.get("status") in ("started", "processing"):
            payload = {"status": "processing", "progress": 99.0, "speed": "—", "eta": "—"}
            if hook_title:
                payload["title"] = str(hook_title)
            if hook_thumb:
                payload["thumbnail_url"] = str(hook_thumb)
            progress(payload)

    outtmpl_pattern = (
        "%(title)s [%(id)s].%(ext)s"
        if getattr(settings, "append_id_suffix", False)
        else "%(title)s.%(ext)s"
    )

    options: dict = {
        "format": build_format(job),
        "outtmpl": str(path / outtmpl_pattern),
        "windowsfilenames": True,
        "trim_file_name": 200,
        "noplaylist": True,
        "continuedl": True,
        "overwrites": False,
        "quiet": True,
        "noprogress": True,
        "retries": 8,
        "fragment_retries": 8,
        "concurrent_fragment_downloads": max(1, min(8, int(getattr(settings, "fragment_connections", 4) or 4))),
        "buffersize": 1024 * 64,
        "http_chunk_size": 10485760,
        "socket_timeout": 20,
        "logger": SignalLogger(log),
        "progress_hooks": [progress_hook],
        "postprocessor_hooks": [postprocessor_hook],
    }

    ffmpeg_bin = shutil.which("ffmpeg")
    deno_bin = shutil.which("deno")
    if not ffmpeg_bin or not deno_bin:
        from .version import is_frozen
        if is_frozen():
            from .updater import ensure_runtime_binaries
            ensure_runtime_binaries(progress_cb=log, force=False)
            ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        options["ffmpeg_location"] = str(Path(ffmpeg_bin).resolve().parent)

    # Prefer target video codec at the highest available resolution so YouTube's native H.264 stream
    # is selected directly when available (avoiding unnecessary AV1 -> H.264 transcoding on <=1080p videos).
    if job.mode == "video" and not job.format_id:
        target_c = (job.video_codec or "auto").lower()
        sort_map = {
            "h264": "h264",
            "h265": "h265",
            "av1": "av01",
            "vp9": "vp9",
        }
        if target_c in sort_map:
            if getattr(job, "mute_audio", False):
                options["format_sort"] = ["res", "fps", f"vcodec:{sort_map[target_c]}"]
            else:
                options["format_sort"] = ["res", "fps", f"vcodec:{sort_map[target_c]}", "acodec:m4a"]

    if settings.cookie_file:
        cookie_path = Path(settings.cookie_file).expanduser()
        if not cookie_path.is_file():
            raise ValueError("Không tìm thấy tệp cookie đã cấu hình")
        options["cookiefile"] = str(cookie_path)

    postprocessors: list[dict] = []
    if job.mode == "video":
        options["merge_output_format"] = job.container
        if job.container == "mkv":
            postprocessors.append({"key": "FFmpegVideoRemuxer", "preferedformat": "mkv"})
    elif job.container != "original":
        bitrate_val = str(job.audio_bitrate or "192")
        if bitrate_val not in {"128", "192", "320"}:
            bitrate_val = "192"
        postprocessors.append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": job.container,
            **({"preferredquality": bitrate_val} if job.container in ("mp3", "m4a") else {}),
        })

    if job.subtitles:
        langs = [s.strip() for s in (job.sub_langs or "vi,en").split(",") if s.strip()]
        options["writesubtitles"] = True
        options["writeautomaticsub"] = True
        options["subtitleslangs"] = langs or ["vi", "en"]
        if job.mode == "video":
            postprocessors.append({"key": "FFmpegEmbedSubtitle"})

    if job.embed_metadata:
        postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})

    if postprocessors:
        options["postprocessors"] = postprocessors

    checkpoint()
    data = _run_ytdlp_extract_with_fallback(
        options,
        job.url,
        download=True,
        cookies_from_browser=getattr(settings, "cookies_from_browser", "auto"),
        log=log,
    )
    if not isinstance(data, dict):
        raise RuntimeError("Không nhận được thông tin file sau khi tải")
    meta_update: dict = {"status": "processing", "progress": 99.2}
    if data.get("title"):
        meta_update["title"] = str(data["title"])
    if data.get("thumbnail"):
        meta_update["thumbnail_url"] = str(data["thumbnail"])
    progress(meta_update)
    output = find_output_file(data, path, job)

    checkpoint()
    if output is None:
        raise RuntimeError("yt-dlp đã kết thúc nhưng không tìm thấy file đúng định dạng trong thư mục đích")

    known_dur = float(data.get("duration") or 0.0)
    known_vc = str(data.get("vcodec") or "")
    w_info = int(data.get("width") or 0)
    h_info = int(data.get("height") or 0)
    fps_info = data.get("fps")
    tbr_info = data.get("tbr") or data.get("vbr") or data.get("abr")
    for req_dl in data.get("requested_downloads") or []:
        if isinstance(req_dl, dict):
            if known_vc in ("none", "") and req_dl.get("vcodec") not in (None, "none", ""):
                known_vc = str(req_dl["vcodec"])
            if (w_info <= 0 or h_info <= 0) and req_dl.get("width") and req_dl.get("height"):
                w_info = int(req_dl["width"])
                h_info = int(req_dl["height"])
            if not fps_info and req_dl.get("fps"):
                fps_info = req_dl["fps"]
            if not tbr_info and (req_dl.get("tbr") or req_dl.get("vbr") or req_dl.get("abr")):
                tbr_info = req_dl.get("tbr") or req_dl.get("vbr") or req_dl.get("abr")
    if w_info > 0 and h_info > 0 and not job.detected_resolution:
        job.detected_resolution = f"{w_info}x{h_info}"
    if fps_info and not job.detected_fps:
        job.detected_fps = _format_fps_str(fps_info)
    if tbr_info and not job.detected_bitrate:
        try:
            job.detected_bitrate = f"{max(1, round(float(tbr_info)))} kbps"
        except Exception:
            pass

    # Verify video codec and convert to target codec (e.g. H.264 default, H.265, AV1, VP9) or trim clip if needed
    final_output, detected_codec = ensure_video_codec(
        output,
        job,
        settings,
        control,
        progress,
        log,
        force_transcode=False,
        clip_range=(start_sec, end_sec),
        known_duration=known_dur,
        known_vcodec=known_vc,
    )
    if detected_codec:
        job.detected_codec = detected_codec
    progress({
        "status": "processing",
        "progress": 99.8,
        "detected_codec": job.detected_codec,
        "detected_resolution": job.detected_resolution,
        "detected_fps": job.detected_fps,
        "detected_bitrate": job.detected_bitrate,
    })
    return str(final_output)


def find_output_file(info: dict, path: Path, job: Job) -> Path | None:
    candidates = []
    for key in ("filepath", "_filename"):
        if info.get(key):
            candidates.append(Path(str(info[key])))
    for part in info.get("requested_downloads") or []:
        if isinstance(part, dict) and part.get("filepath"):
            candidates.append(Path(str(part["filepath"])))
    expected_ext = job.container if job.container != "original" else ""
    title = str(info.get("title") or "")
    if title:
        candidates.extend(
            p for p in path.iterdir()
            if p.is_file() and (p.stem == title or p.stem.startswith(title[:50]))
        )
    ident = str(info.get("id") or "")
    if ident and re.fullmatch(r"[A-Za-z0-9_-]+", ident):
        candidates.extend(
            p for p in path.iterdir()
            if p.is_file() and f"[{ident}]" in p.name
        )

    def _is_temp_or_partial(p: Path) -> bool:
        low = p.name.lower()
        if low.endswith((".part", ".ytdl", ".temp", ".vtt", ".srt", ".ass", ".meta")):
            return True
        if ".temp." in low or ".transcode_temp." in low or ".trim_temp." in low:
            return True
        if re.search(r"\.f\d+\.[a-z0-9]+$", low):
            return True
        return False

    found = [item for item in candidates if item.is_file() and not _is_temp_or_partial(item)]
    if not found:
        return None
    if expected_ext:
        match = [item for item in found if item.suffix.lower() == f".{expected_ext}"]
        if match:
            found = match
    return max(found, key=lambda p: p.stat().st_mtime)


def environment_report() -> dict[str, bool | str]:
    setup_bundled_environment()
    ffmpeg_path = shutil.which("ffmpeg") or ""
    ffprobe_path = shutil.which("ffprobe") or (f"{ffmpeg_path} (ffmpeg -i)" if ffmpeg_path else "")
    return {
        "ffmpeg": ffmpeg_path,
        "ffprobe": ffprobe_path,
        "deno": shutil.which("deno") or "",
        "ejs": bool(importlib.util.find_spec("yt_dlp_ejs")),
        "yt_dlp_version": _fast_yt_dlp_version(),
    }
