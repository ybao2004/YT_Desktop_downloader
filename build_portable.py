"""Unified Single-File Executable packaging script for YouTube Desktop Downloader.

Usage:
  python build_portable.py
      Builds a single self-contained executable `dist/YouTubeDesktopDownloader.exe`
      embedding Python, PyQt6, yt-dlp, yt-dlp-ejs, certifi, FFmpeg, FFprobe, and Deno
      so the single `.exe` file can be copied to any Windows PC and run immediately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ytd_app.version import APP_VERSION, DEFAULT_GITHUB_REPO

ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
EXE_BASE_NAME = "YouTubeDesktopDownloader"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def cleanup_legacy_dist_artifacts() -> None:
    """Remove old multi-file folder, .zip, or duplicate _Single.exe builds so `dist/`
    contains only the unified `YouTubeDesktopDownloader.exe` and `version.json`.
    """
    if not DIST_DIR.exists():
        return
    for item in DIST_DIR.iterdir():
        try:
            if item.is_dir() and item.name == EXE_BASE_NAME:
                shutil.rmtree(item, ignore_errors=True)
            elif item.is_file() and (
                item.suffix.lower() == ".zip"
                or item.name.endswith("_Single.exe")
            ):
                item.unlink(missing_ok=True)
        except OSError:
            pass


def build_single_exe(skip_bins: bool = False) -> Path:
    print(f"=== [1/2] Building Unified Single-File Executable ({EXE_BASE_NAME}.exe v{APP_VERSION}) ===")
    cleanup_legacy_dist_artifacts()

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name",
        EXE_BASE_NAME,
        "--collect-all",
        "yt_dlp",
        "--collect-all",
        "yt_dlp_ejs",
        "--collect-all",
        "certifi",
        "--add-data",
        f"{ROOT / 'ytd_app' / 'assets'}{os.pathsep}ytd_app/assets",
    ]

    if not skip_bins:
        embedded: list[str] = []
        for tool in ("ffmpeg", "ffprobe", "deno"):
            found = shutil.which(tool)
            if found:
                src = Path(found).resolve()
                cmd.extend(["--add-binary", f"{src}{os.pathsep}bin"])
                embedded.append(f"{src.name} ({src})")
        if embedded:
            print("      Embedded runtime tools into single .exe:")
            for item in embedded:
                print(f"        + {item}")
        else:
            print("[WARN] No ffmpeg/ffprobe/deno found on PATH to embed!")

    cmd.append(str(ROOT / "main.py"))
    subprocess.run(cmd, cwd=str(ROOT), check=True)

    out_exe = DIST_DIR / f"{EXE_BASE_NAME}.exe"
    if not out_exe.is_file():
        raise FileNotFoundError(f"Expected output executable not found: {out_exe}")

    print("=== [2/2] Generating Remote Update Manifest (dist/version.json) ===")
    manifest = {
        "version": APP_VERSION,
        "download_url": f"https://github.com/{DEFAULT_GITHUB_REPO}/releases/download/v{APP_VERSION}/{out_exe.name}",
        "html_url": f"https://github.com/{DEFAULT_GITHUB_REPO}/releases/tag/v{APP_VERSION}",
        "sha256": sha256_file(out_exe),
        "notes": (
            f"YouTube Desktop Downloader v{APP_VERSION} (Single .EXE All-in-One):\n"
            "- Đóng gói duy nhất 1 file YouTubeDesktopDownloader.exe (tích hợp sẵn FFmpeg, FFprobe, Deno, yt-dlp).\n"
            "- Gửi sang bất kỳ máy tính Windows nào cũng chạy được ngay không cần cài đặt.\n"
            "- Tự động chuyển đổi Codec H.264 (mặc định), H.265/HEVC, AV1, VP9 với tăng tốc GPU."
        ),
    }
    manifest_path = DIST_DIR / "version.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      Manifest : {manifest_path}")
    print(f"      Single EXE: {out_exe} ({out_exe.stat().st_size / (1024 * 1024):.1f} MB)")
    return out_exe


def main():
    parser = argparse.ArgumentParser(description="Build Unified Single-File YouTube Desktop Downloader (.exe)")
    parser.add_argument("--skip-bins", action="store_true", help="Build without embedding ffmpeg/ffprobe/deno")
    args = parser.parse_args()

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    exe_path = build_single_exe(skip_bins=args.skip_bins)
    print(f"\n[OK] Unified Single-File EXE Ready: {exe_path}")


if __name__ == "__main__":
    main()
