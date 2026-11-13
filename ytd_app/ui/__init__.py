"""Minimal professional PyQt6 UI package for YouTube Desktop Downloader.
Heavy widgets (MainWindow, JobRow, JobCardWidget) are lazily resolved via PEP 562 __getattr__
so importing splash, theme or setup_app does not pull in engine, yt-dlp, or psutil before splash shows.
"""
from __future__ import annotations

import typing

from ..storage import Storage
from .app import load_bundled_fonts, setup_app
from .splash import SplashScreen, get_app_icon

__all__ = [
    "JobCardWidget",
    "JobRow",
    "MainWindow",
    "STATUS_TEXT",
    "SplashScreen",
    "Storage",
    "get_app_icon",
    "load_bundled_fonts",
    "setup_app",
    "tool_button",
]


def __getattr__(name: str) -> typing.Any:
    if name in {"MainWindow", "JobRow", "JobCardWidget"}:
        from . import main_window
        val = getattr(main_window, name)
        globals()[name] = val
        return val
    if name in {"STATUS_TEXT", "tool_button"}:
        from . import widgets
        val = getattr(widgets, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
