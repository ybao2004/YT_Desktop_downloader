"""Lightweight Single-File Executable packaging script (Mức 2) for YouTube Desktop Downloader.

Usage:
  python build_portable.py
      Builds an ultra-lightweight single executable `dist/YouTubeDesktopDownloader.exe` (~35-45 MB)
      by stripping unused PyQt6/Python modules, compiling bytecode with `--optimize 2`, and
      provisioning `ffmpeg.exe` + `deno.exe` on-demand into `~/youtube_desktop_downloader_data/bin/`.

  python build_portable.py --bundle-bins
      Optional fat build that embeds `ffmpeg.exe` and `deno.exe` inside the `.exe` (skips `ffprobe.exe`).
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

EXCLUDED_MODULES: tuple[str, ...] = (
    # Unused Python stdlib modules
    "tkinter",
    "_tkinter",
    "unittest",
    "pydoc",
    "pydoc_data",
    "sqlite3",
    "_sqlite3",
    "doctest",
    "pdb",
    "bdb",
    "lib2to3",
    "ensurepip",
    "venv",
    "idlelib",
    "turtle",
    "turtledemo",
    # Unused heavy PyQt6 modules
    "PyQt6.QtQml",
    "PyQt6.QtQuick",
    "PyQt6.QtQuickWidgets",
    "PyQt6.QtQuick3D",
    "PyQt6.QtSql",
    "PyQt6.QtTest",
    "PyQt6.QtOpenGL",
    "PyQt6.QtOpenGLWidgets",
    "PyQt6.QtPdf",
    "PyQt6.QtPdfWidgets",
    "PyQt6.QtMultimedia",
    "PyQt6.QtMultimediaWidgets",
    "PyQt6.QtBluetooth",
    "PyQt6.QtNfc",
    "PyQt6.QtPositioning",
    "PyQt6.QtRemoteObjects",
    "PyQt6.QtSensors",
    "PyQt6.QtSerialPort",
    "PyQt6.QtSpatialAudio",
    "PyQt6.QtWebChannel",
    "PyQt6.QtWebSockets",
    "PyQt6.QtDesigner",
    "PyQt6.QtHelp",
    "PyQt6.QtSvgWidgets",
)


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


def build_single_exe(skip_bins: bool = True, bundle_bins: bool = False) -> Path:
    mode_label = "Lightweight Level 2" if not bundle_bins else "Bundled Fat EXE"
    print(f"=== [1/2] Building Single-File Executable ({EXE_BASE_NAME}.exe v{APP_VERSION} - {mode_label}) ===")
    cleanup_legacy_dist_artifacts()

    spec_file = ROOT / f"{EXE_BASE_NAME}.spec"
    env = os.environ.copy()
    if bundle_bins and not skip_bins:
        env["YTD_BUNDLE_BINS"] = "1"
        embedded: list[str] = []
        # Skip ffprobe since engine.py uses `ffmpeg -i` fallback
        for tool in ("ffmpeg", "deno"):
            found = shutil.which(tool)
            if found:
                embedded.append(f"{Path(found).name} ({Path(found).resolve()})")
        if embedded:
            print("      Embedded runtime tools into single .exe:")
            for item in embedded:
                print(f"        + {item}")
        else:
            print("[WARN] No ffmpeg/deno found on PATH to embed!")
    else:
        env.pop("YTD_BUNDLE_BINS", None)
        print("      [Lightweight Level 2] Skipping embedded ffmpeg/ffprobe/deno (auto-provisioned on first run).")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(spec_file),
    ]
    subprocess.run(cmd, cwd=str(ROOT), env=env, check=True)

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
            f"YouTube Desktop Downloader v{APP_VERSION} (Lightweight Single .EXE - Mức 2):\n"
            "- Tăng tốc vượt trội thời gian mở Màn hình Khởi động (tối ưu font QSS & giải nén .exe).\n"
            "- Màn hình Khởi động hiển thị ngay trên Taskbar và không còn luôn nằm trên cùng.\n"
            "- Tinh gọn Tab Cập nhật trong Cài đặt, bỏ ô cấu hình nguồn cập nhật thủ công.\n"
            "- Tự động chuyển đổi Codec H.264 (mặc định), H.265/HEVC, AV1, VP9 với tăng tốc GPU."
        ),
    }
    manifest_path = DIST_DIR / "version.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      Manifest : {manifest_path}")
    print(f"      Single EXE: {out_exe} ({out_exe.stat().st_size / (1024 * 1024):.1f} MB)")
    return out_exe


def main():
    parser = argparse.ArgumentParser(description="Build Lightweight Single-File YouTube Desktop Downloader (.exe)")
    parser.add_argument(
        "--bundle-bins",
        action="store_true",
        help="Embed ffmpeg.exe and deno.exe inside the .exe instead of downloading on first run",
    )
    parser.add_argument(
        "--skip-bins",
        action="store_true",
        help="Explicitly skip embedding binaries (default in Mức 2)",
    )
    args = parser.parse_args()

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    bundle = bool(args.bundle_bins and not args.skip_bins)
    exe_path = build_single_exe(skip_bins=not bundle, bundle_bins=bundle)
    print(f"\n[OK] Single-File EXE Ready: {exe_path}")


if __name__ == "__main__":
    main()
