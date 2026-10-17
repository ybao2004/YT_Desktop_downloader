"""Remote version checker, single-exe hot-swap updater, and in-process yt-dlp runtime updater."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .version import APP_VERSION, DEFAULT_GITHUB_REPO, app_data_dir, app_root_dir, is_frozen

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass
class UpdateInfo:
    current_version: str
    latest_version: str
    has_update: bool
    download_url: str = ""
    release_notes: str = ""
    html_url: str = ""
    sha256: str = ""
    source: str = ""


def parse_version_tuple(version_str: str) -> tuple[int, ...]:
    cleaned = re.sub(r"^[^0-9]*", "", (version_str or "").strip())
    nums = [int(part) for part in re.findall(r"\d+", cleaned)]
    return tuple(nums) if nums else (0,)


def is_newer_version(latest: str, current: str = APP_VERSION) -> bool:
    return parse_version_tuple(latest) > parse_version_tuple(current)


def resolve_manifest_url(custom_url: str = "") -> str:
    url = (custom_url or "").strip().rstrip("/")
    if url:
        gh_match = re.fullmatch(
            r"https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/releases)?",
            url,
            re.IGNORECASE,
        )
        if gh_match:
            return f"https://api.github.com/repos/{gh_match.group(1)}/releases/latest"
        if url.startswith(("http://", "https://", "file://")):
            return url
        if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", url):
            return f"https://api.github.com/repos/{url}/releases/latest"
    return f"https://api.github.com/repos/{DEFAULT_GITHUB_REPO}/releases/latest"


def check_for_updates(custom_url: str = "", timeout: float = 10.0) -> UpdateInfo:
    """Query either a GitHub Releases API endpoint or a JSON manifest URL for a newer version."""
    target_url = resolve_manifest_url(custom_url)
    req = urllib.request.Request(
        target_url,
        headers={
            "User-Agent": f"YouTubeDesktopDownloader/{APP_VERSION}",
            "Accept": "application/vnd.github+json, application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = json.loads(resp.read().decode("utf-8", errors="replace"))

    if not isinstance(raw, dict):
        raise ValueError("Phản hồi kiểm tra cập nhật không hợp lệ")

    # Case 1: GitHub Releases API format (`tag_name`, `assets`, `body`, `html_url`)
    if "tag_name" in raw:
        latest_ver = str(raw.get("tag_name") or "").lstrip("vV").strip() or APP_VERSION
        notes = str(raw.get("body") or "Không có ghi chú phát hành.")
        html_url = str(raw.get("html_url") or "")
        download_url = ""
        assets = raw.get("assets") or []
        exe_candidates: list[str] = []
        zip_candidates: list[str] = []
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "").lower()
            b_url = str(asset.get("browser_download_url") or "")
            if not b_url:
                continue
            if name.endswith(".exe"):
                exe_candidates.append(b_url)
            elif name.endswith(".zip"):
                zip_candidates.append(b_url)
        # Always prioritize single .exe asset first
        if exe_candidates:
            download_url = exe_candidates[0]
        elif zip_candidates:
            download_url = zip_candidates[0]
        return UpdateInfo(
            current_version=APP_VERSION,
            latest_version=latest_ver,
            has_update=is_newer_version(latest_ver, APP_VERSION),
            download_url=download_url,
            release_notes=notes,
            html_url=html_url,
            source=target_url,
        )

    # Case 2: Custom JSON Manifest format (`version`, `download_url`, `notes`, `sha256`, `html_url`)
    latest_ver = str(raw.get("version") or raw.get("latest_version") or APP_VERSION).lstrip("vV").strip()
    download_url = str(raw.get("download_url") or raw.get("url") or "")
    notes = str(raw.get("notes") or raw.get("release_notes") or "")
    sha256 = str(raw.get("sha256") or "")
    html_url = str(raw.get("html_url") or "")
    return UpdateInfo(
        current_version=APP_VERSION,
        latest_version=latest_ver,
        has_update=is_newer_version(latest_ver, APP_VERSION),
        download_url=download_url,
        release_notes=notes,
        html_url=html_url,
        sha256=sha256,
        source=target_url,
    )


def download_update_package(
    info: UpdateInfo,
    progress_cb: Callable[[float, str], None] | None = None,
) -> Path:
    """Download the remote update (.exe or .zip) into `youtube_desktop_downloader_data/updates/`
    and verify SHA256 if provided.
    """
    if not info.download_url:
        raise ValueError("Bản phát hành này không đính kèm đường dẫn tải gói tự động.")

    updates_dir = app_data_dir() / "updates"
    updates_dir.mkdir(parents=True, exist_ok=True)
    ext = ".zip" if info.download_url.lower().endswith(".zip") else ".exe"
    dest_file = updates_dir / f"update_v{info.latest_version}{ext}"

    req = urllib.request.Request(
        info.download_url,
        headers={"User-Agent": f"YouTubeDesktopDownloader/{APP_VERSION}"},
    )
    hasher = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        received = 0
        with dest_file.open("wb") as out:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                out.write(chunk)
                hasher.update(chunk)
                received += len(chunk)
                if progress_cb:
                    pct = (100.0 * received / total) if total > 0 else 50.0
                    progress_cb(min(99.0, pct), f"Đang tải gói cập nhật ({received / (1024*1024):.1f} MB)...")

    if info.sha256:
        actual = hasher.hexdigest().lower()
        if actual != info.sha256.strip().lower():
            dest_file.unlink(missing_ok=True)
            raise ValueError("Mã kiểm tra SHA-256 của gói cập nhật không khớp!")

    if progress_cb:
        progress_cb(100.0, "Đã tải xong gói cập nhật.")
    return dest_file


def stage_portable_update(package_path: Path) -> Path:
    """Prepare the update in `youtube_desktop_downloader_data/updates/staged/` and generate a
    Windows hot-swap script `apply_update.bat` that waits for the single `.exe` to unlock,
    replaces it, and relaunches the application.
    """
    updates_root = app_data_dir() / "updates"
    stage_dir = updates_root / "staged"
    if stage_dir.exists():
        shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True, exist_ok=True)

    target_root = app_root_dir()
    target_exe = Path(sys.executable).resolve() if is_frozen() else (target_root / "YouTubeDesktopDownloader.exe")

    if zipfile.is_zipfile(package_path):
        with zipfile.ZipFile(package_path, "r") as zf:
            zf.extractall(stage_dir)
        items = list(stage_dir.iterdir())
        if len(items) == 1 and items[0].is_dir():
            stage_dir = items[0]
        copy_cmd = f'xcopy "{stage_dir}\\*" "{target_root}\\" /E /Y /I /Q >nul 2>&1'
    else:
        staged_exe = stage_dir / target_exe.name
        shutil.copy2(package_path, staged_exe)
        copy_cmd = f'copy /Y "{staged_exe}" "{target_exe}" >nul 2>&1'

    script_path = updates_root / "apply_update.bat"
    relaunch_cmd = (
        f'start "" "{target_exe}"'
        if is_frozen()
        else f'start "" "{sys.executable}" "{target_root / "main.py"}"'
    )
    bat_content = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "echo Đang áp dụng bản cập nhật mới...\r\n"
        "for /L %%i in (1,1,15) do (\r\n"
        "    timeout /t 1 /nobreak >nul\r\n"
        f"    {copy_cmd} && goto :updated\r\n"
        ")\r\n"
        ":updated\r\n"
        f"{relaunch_cmd}\r\n"
        "exit\r\n"
    )
    script_path.write_text(bat_content, encoding="utf-8")
    return script_path


def launch_staged_updater(script_path: Path) -> None:
    """Launch the batch updater in a detached process so the main app can exit cleanly."""
    if os.name == "nt":
        subprocess.Popen(
            ["cmd.exe", "/c", str(script_path)],
            cwd=str(app_data_dir()),
            creationflags=CREATE_NO_WINDOW,
        )


def update_ytdlp_core() -> tuple[bool, str]:
    """Update the in-process `yt_dlp` Python library used by the app.
    - When running from Python/venv, updates via pip first.
    - When running as a frozen single `.exe` (or on any machine without Python), downloads the
      latest pure-Python `yt_dlp-*-py3-none-any.whl` from PyPI into `youtube_desktop_downloader_data/packages`
      and hot-reloads `yt_dlp` in memory.
    """
    if not is_frozen():
        try:
            res = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=90,
                creationflags=CREATE_NO_WINDOW,
            )
            if res.returncode == 0:
                return True, "Đã cập nhật thành công gói yt-dlp[default] lên phiên bản mới nhất."
        except Exception:
            pass

    # Pure-Python wheel hot-update into `youtube_desktop_downloader_data/packages` (works on ANY PC without Python)
    try:
        req = urllib.request.Request(
            "https://pypi.org/pypi/yt-dlp/json",
            headers={"User-Agent": f"YouTubeDesktopDownloader/{APP_VERSION}"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            pypi_data = json.loads(resp.read().decode("utf-8", errors="replace"))
        latest_ver = str((pypi_data.get("info") or {}).get("version") or "")
        wheel_url = ""
        for item in pypi_data.get("urls") or []:
            if isinstance(item, dict) and str(item.get("filename") or "").endswith(".whl"):
                wheel_url = str(item.get("url") or "")
                break
        if not wheel_url:
            raise ValueError("Không tìm thấy gói wheel yt-dlp trên PyPI.")

        pkg_root = app_data_dir() / "packages"
        pkg_root.mkdir(parents=True, exist_ok=True)
        whl_tmp = pkg_root / "yt_dlp_latest.whl"
        dl_req = urllib.request.Request(
            wheel_url,
            headers={"User-Agent": f"YouTubeDesktopDownloader/{APP_VERSION}"},
        )
        with urllib.request.urlopen(dl_req, timeout=45) as resp:
            whl_tmp.write_bytes(resp.read())

        extract_tmp = pkg_root / "_extract_tmp"
        if extract_tmp.exists():
            shutil.rmtree(extract_tmp, ignore_errors=True)
        extract_tmp.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(whl_tmp, "r") as zf:
            zf.extractall(extract_tmp)
        whl_tmp.unlink(missing_ok=True)

        src_ytdlp = extract_tmp / "yt_dlp"
        dst_ytdlp = pkg_root / "yt_dlp"
        if src_ytdlp.is_dir():
            if dst_ytdlp.exists():
                shutil.rmtree(dst_ytdlp, ignore_errors=True)
            shutil.move(str(src_ytdlp), str(dst_ytdlp))
        shutil.rmtree(extract_tmp, ignore_errors=True)

        pkg_str = str(pkg_root)
        if pkg_str not in sys.path:
            sys.path.insert(0, pkg_str)
        try:
            import yt_dlp.version
            importlib.reload(yt_dlp.version)
        except Exception:
            pass
        return True, f"Đã cập nhật thành công lõi yt-dlp lên bản {latest_ver} (lưu tại {dst_ytdlp})."
    except Exception as exc:
        return False, f"Không cập nhật được lõi yt-dlp: {exc}"
