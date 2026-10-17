@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [1/2] Tao moi truong Python...
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Khong tim thay Python. Cai Python 3.11 tro len.
    pause
    exit /b 1
  )
)
echo [2/2] Cai dat/cap nhat thu vien...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Khong the cai cac thu vien. Kiem tra ket noi internet.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" main.py
if errorlevel 1 pause
