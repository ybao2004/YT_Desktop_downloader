"""Application version, default paths, single-exe environment setup, and bundled binary PATH management."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

APP_NAME = "YouTube Desktop Downloader"
APP_VERSION = "1.0.0"
DEFAULT_GITHUB_REPO = "ybao2004/YT_Desktop_downloader"
DEFAULT_UPDATE_MANIFEST_URL = "https://api.github.com/repos/ybao2004/YT_Desktop_downloader/releases/latest"

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CREATE_NEW_CONSOLE = 0x00000010 if os.name == "nt" else 0

_ORIG_POPEN = subprocess.Popen
_BINS_SYNC_STARTED = False


def _install_silent_popen_wrapper() -> None:
    """Ensure child processes spawned by yt-dlp (e.g. deno.exe, ffmpeg.exe) on Windows
    do not flash console windows when running as a windowed GUI application.
    """
    if os.name != "nt" or getattr(subprocess.Popen, "__name__", "") == "_SilentWindowsPopen":
        return

    class _SilentWindowsPopen(_ORIG_POPEN):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            flags = int(kwargs.get("creationflags", 0) or 0)
            if not (flags & CREATE_NEW_CONSOLE):
                kwargs["creationflags"] = flags | CREATE_NO_WINDOW
            super().__init__(*args, **kwargs)

    subprocess.Popen = _SilentWindowsPopen  # type: ignore[assignment]


def is_frozen() -> bool:
    """Return True when running from a PyInstaller executable."""
    return bool(getattr(sys, "frozen", False))


def app_root_dir() -> Path:
    """Return the directory containing the executable or main.py."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def default_download_dir() -> Path:
    """Default directory for downloaded media:
    `C:\\Users\\<User>\\Downloads\\YouTube Desktop Downloader`
    """
    return Path.home() / "Downloads" / "YouTube Desktop Downloader"


def app_data_dir() -> Path:
    """Default directory for all application files (settings, queue history, updates, runtime tools):
    `C:\\Users\\<User>\\youtube_desktop_downloader_data`
    """
    return Path.home() / "youtube_desktop_downloader_data"


def portable_data_dir() -> Path:
    """Alias returning `app_data_dir()` (`<User>/youtube_desktop_downloader_data`)."""
    return app_data_dir()


def is_portable_mode() -> bool:
    """Return True as the app now runs in unified single-exe portable mode."""
    return True


def bundled_bin_dir() -> Path:
    """Return the persistent `bin` directory inside `youtube_desktop_downloader_data/bin`."""
    return app_data_dir() / "bin"


def _meipass_bin_dir() -> Path | None:
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        candidate = Path(getattr(sys, "_MEIPASS")) / "bin"
        if candidate.is_dir():
            return candidate
    return None


def _sync_embedded_bins_async() -> None:
    """Copy embedded ffmpeg/ffprobe/deno from `_MEIPASS/bin` into `youtube_desktop_downloader_data/bin`
    in the background so application tools persist in the user's app data directory even if Windows
    Storage Sense cleans `%TEMP%` while the app is open.
    """
    global _BINS_SYNC_STARTED
    if _BINS_SYNC_STARTED:
        return
    meipass_bin = _meipass_bin_dir()
    if meipass_bin is None:
        return
    _BINS_SYNC_STARTED = True

    def _worker():
        try:
            target_dir = bundled_bin_dir()
            target_dir.mkdir(parents=True, exist_ok=True)
            for item in meipass_bin.iterdir():
                if not item.is_file():
                    continue
                dst = target_dir / item.name
                try:
                    if not dst.is_file() or dst.stat().st_size != item.stat().st_size:
                        tmp = dst.with_suffix(dst.suffix + ".tmp")
                        shutil.copy2(item, tmp)
                        os.replace(tmp, dst)
                except OSError:
                    pass
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


def setup_bundled_environment() -> None:
    """Configure PATH, SSL certificates, hot-updated packages, and silent subprocess spawning."""
    _install_silent_popen_wrapper()

    # 1. Load hot-updated Python packages (e.g. updated yt_dlp) from `youtube_desktop_downloader_data/packages`
    try:
        pkg_dir = app_data_dir() / "packages"
        if pkg_dir.is_dir():
            pkg_str = str(pkg_dir)
            if pkg_str not in sys.path:
                sys.path.insert(0, pkg_str)
    except Exception:
        pass

    # 2. Ensure SSL certificates work on clean Windows machines when frozen
    try:
        import certifi
        ca_bundle = certifi.where()
        if ca_bundle and Path(ca_bundle).is_file():
            os.environ.setdefault("SSL_CERT_FILE", ca_bundle)
            os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_bundle)
    except Exception:
        pass

    # 3. Prepend persistent data `bin/`, PyInstaller `_MEIPASS/bin`, and app root `bin/` to PATH
    paths_to_prepend: list[str] = []
    try:
        data_bin = bundled_bin_dir()
        data_bin.mkdir(parents=True, exist_ok=True)
        paths_to_prepend.append(str(data_bin))
    except Exception:
        pass

    meipass_bin = _meipass_bin_dir()
    if meipass_bin is not None:
        paths_to_prepend.append(str(meipass_bin))
        _sync_embedded_bins_async()

    root = app_root_dir()
    if (root / "bin").is_dir():
        paths_to_prepend.append(str(root / "bin"))
    if root.is_dir():
        paths_to_prepend.append(str(root))

    if not paths_to_prepend:
        return
    current_path = os.environ.get("PATH", "")
    existing = {p.strip().lower() for p in current_path.split(os.pathsep) if p.strip()}
    new_entries = [p for p in paths_to_prepend if p.lower() not in existing]
    if new_entries:
        os.environ["PATH"] = os.pathsep.join(new_entries + ([current_path] if current_path else []))


# Automatically register bundled environment on import
setup_bundled_environment()
