@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   ĐÓNG GÓI PORTABLE — YOUTUBE DESKTOP DOWNLOADER v2.0
echo ============================================================

if exist ".venv\Scripts\python.exe" (
    set "PY_EXE=.venv\Scripts\python.exe"
) else (
    set "PY_EXE=python"
)

"%PY_EXE%" -m pip install --upgrade pip pyinstaller psutil -r requirements.txt
"%PY_EXE%" build_portable.py %*

echo.
echo Hoàn tất! Kiểm tra thư mục dist\ để lấy bản Portable (.zip và thư mục).
pause
