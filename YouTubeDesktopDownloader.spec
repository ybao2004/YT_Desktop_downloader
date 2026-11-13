# -*- mode: python ; coding: utf-8 -*-
import os
import shutil
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build_portable import EXCLUDED_MODULES

datas = [(str(ROOT / "ytd_app" / "assets"), "ytd_app/assets")]
binaries = []
hiddenimports = []

for pkg in ("yt_dlp", "yt_dlp_ejs"):
    datas += collect_data_files(pkg)
    hiddenimports += collect_submodules(pkg)

datas += collect_data_files("certifi")
hiddenimports += collect_submodules("certifi")

if os.environ.get("YTD_BUNDLE_BINS") == "1":
    for tool in ("ffmpeg", "deno"):
        found = shutil.which(tool)
        if found:
            binaries.append((str(Path(found).resolve()), "bin"))


a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(EXCLUDED_MODULES),
    noarchive=False,
    optimize=2,
)

# Strip heavy unused Qt6 binaries (software OpenGL renderer, PDF plugin) and Qt translations
# to minimize single-exe extraction time so SplashScreen opens immediately.
_EXCLUDED_BIN_SUBSTRS = ("opengl32sw.dll", "qt6pdf.dll", "qpdf.dll")
a.binaries = [
    b for b in a.binaries
    if not any(s in b[0].lower() for s in _EXCLUDED_BIN_SUBSTRS)
]
a.datas = [
    d for d in a.datas
    if "qt6/translations/" not in d[0].replace("\\", "/").lower()
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [("O", None, "OPTION"), ("O", None, "OPTION")],
    name="YouTubeDesktopDownloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir="%LOCALAPPDATA%\\YouTubeDesktopDownloader\\runtime",
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(ROOT / "version_info.txt"),
    icon=[str(ROOT / "ytd_app" / "assets" / "icons" / "app_icon.ico")],
)
