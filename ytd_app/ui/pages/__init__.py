"""Workspace page builders for MainWindow."""
from __future__ import annotations

from .downloads import build_downloads_page
from .guide import build_guide_page
from .hardware import build_hardware_page
from .log import build_log_page
from .settings import build_settings_page

__all__ = [
    "build_downloads_page",
    "build_guide_page",
    "build_hardware_page",
    "build_log_page",
    "build_settings_page",
]
