"""Windows native title-bar dark mode integration via DWM API."""
from __future__ import annotations

import sys
from PyQt6.QtWidgets import QWidget


def apply_title_bar_theme(window: QWidget, dark: bool) -> None:
    """Toggle Windows 10 (20H1+) / Windows 11 dark title bar on a top-level QWidget."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = int(window.winId())
        if not hwnd:
            return
        dwmapi = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if dark else 0)
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 (Win11 & Win10 2004+), fallback 19
        for attr in (20, 19):
            res = dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                ctypes.c_uint(attr),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if res == 0:
                break
    except Exception:
        pass
