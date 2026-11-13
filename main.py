"""Entry point: python main.py"""
from __future__ import annotations

import multiprocessing
import os
import sys
import time

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from ytd_app.storage import peek_theme_mode
from ytd_app.theme import build_palette, resolve_mode, tokens_for
from ytd_app.ui.app import load_bundled_fonts, setup_app
from ytd_app.ui.splash import SplashScreen, get_app_icon
from ytd_app.version import setup_bundled_environment

SINGLE_INSTANCE_KEY = "YouTubeDesktopDownloader_SingleInstance_AppKey"
SINGLE_INSTANCE_MUTEX = "Local\\YouTubeDesktopDownloader_SingleInstance_Mutex_v32"

_GLOBAL_MUTEX_HANDLE = None


def acquire_single_instance_lock(custom_name: str | None = None) -> bool:
    """Acquire single-instance mutex on Windows.
    Returns True if primary instance, False if another instance is already running.
    """
    global _GLOBAL_MUTEX_HANDLE
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            ERROR_ALREADY_EXISTS = 183
            name = custom_name or SINGLE_INSTANCE_MUTEX
            handle = kernel32.CreateMutexW(None, False, name)
            if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
                if handle:
                    kernel32.CloseHandle(handle)
                return False
            _GLOBAL_MUTEX_HANDLE = handle
        except Exception:
            pass
    return True


def release_single_instance_lock() -> None:
    """Release single-instance mutex on Windows."""
    global _GLOBAL_MUTEX_HANDLE
    if sys.platform == "win32" and _GLOBAL_MUTEX_HANDLE:
        try:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(_GLOBAL_MUTEX_HANDLE)
        except Exception:
            pass
        _GLOBAL_MUTEX_HANDLE = None


def notify_running_instance() -> None:
    """Notify the already running instance to bring its window to foreground and exit."""
    if sys.platform == "win32":
        try:
            import ctypes
            # Allow the existing instance to take foreground focus
            ASFW_ANY = ctypes.c_uint32(-1)
            ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
        except Exception:
            pass

    socket = QLocalSocket()
    # Retry connecting for up to 2.5s in case primary instance is still initializing
    start_time = time.time()
    while time.time() - start_time < 2.5:
        socket.connectToServer(SINGLE_INSTANCE_KEY)
        if socket.waitForConnected(150):
            socket.write(b"ACTIVATE\n")
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()
            return
        time.sleep(0.05)


def main():
    multiprocessing.freeze_support()
    setup_bundled_environment()

    # Explicit Windows AppUserModelID so Windows Taskbar displays the custom app icon
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "LocalTools.YouTubeDesktopDownloader.App.v32"
            )
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("YouTube Desktop Downloader")
    app.setOrganizationName("LocalTools")

    # 1. Atomic Single Instance Check
    is_primary = acquire_single_instance_lock()
    if not is_primary:
        notify_running_instance()
        sys.exit(0)

    # Secondary check via local socket probe (for non-Windows platforms)
    if sys.platform != "win32":
        probe_socket = QLocalSocket()
        probe_socket.connectToServer(SINGLE_INSTANCE_KEY)
        if probe_socket.waitForConnected(100):
            notify_running_instance()
            sys.exit(0)

    # 2. Immediately start single-instance local server
    local_server = QLocalServer()
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    if not local_server.listen(SINGLE_INSTANCE_KEY):
        time.sleep(0.05)
        QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
        local_server.listen(SINGLE_INSTANCE_KEY)

    window_ref: list = [None]
    splash_ref: list = [None]

    def bring_to_front():
        splash = splash_ref[0]
        window = window_ref[0]
        if window is not None:
            if splash is not None and splash.isVisible():
                splash.close()
            if window.isMinimized():
                window.showNormal()
            window.show()
            window.raise_()
            window.activateWindow()

            if sys.platform == "win32":
                try:
                    import ctypes
                    hwnd = int(window.winId())
                    if ctypes.windll.user32.IsIconic(hwnd):
                        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    else:
                        ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                except Exception:
                    pass
        elif splash is not None and splash.isVisible():
            if splash.isMinimized():
                splash.showNormal()
            splash.raise_()
            splash.activateWindow()

    def handle_new_connection():
        client = local_server.nextPendingConnection()
        if client:
            client.waitForReadyRead(500)
            client.disconnectFromServer()
            bring_to_front()

    local_server.newConnection.connect(handle_new_connection)

    # 3. Fast font & palette setup so splash uses final typography metrics from frame 0
    theme_pref = peek_theme_mode()
    resolved = resolve_mode(theme_pref)
    t = tokens_for(resolved)
    app.setPalette(build_palette(t))

    family = load_bundled_fonts()
    default_font = QFont(family)
    default_font.setPixelSize(13)
    default_font.setWeight(QFont.Weight.Normal)
    app.setFont(default_font)

    icon = get_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    splash = SplashScreen(mode=resolved)
    splash_ref[0] = splash
    splash.show()
    app.processEvents()

    splash.set_progress(35, "Đang khởi tạo các thành phần giao diện...")

    # Apply full application theme & load fonts while splash is visible
    setup_app(app, theme_pref=theme_pref)

    splash.set_progress(70, "Đang tải cấu hình...")

    # Lazily import and initialize main window after splash is visible
    from ytd_app.ui import MainWindow

    window = MainWindow()
    window_ref[0] = window

    # After initialization completes, update to 100% "Hoàn tất!" and hold for ~1s before opening MainWindow
    splash.set_progress(100, "Hoàn tất!")

    def on_ready():
        window.show()
        splash.close()

    QTimer.singleShot(1000, on_ready)

    ret = app.exec()
    local_server.close()
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    release_single_instance_lock()
    sys.exit(ret)


if __name__ == "__main__":
    main()
