"""Reusable custom widgets for YouTube Desktop Downloader."""
from __future__ import annotations

from .common import FolderChip, SectionCard, SettingRow, icon_button, tool_button
from .job_row import STATUS_TEXT, JobRow
from .metric_card import MetricCard, SparklineWidget
from .segmented import SegmentedControl
from .sidebar import Sidebar

__all__ = [
    "FolderChip",
    "JobRow",
    "MetricCard",
    "SectionCard",
    "SegmentedControl",
    "SettingRow",
    "Sidebar",
    "SparklineWidget",
    "STATUS_TEXT",
    "icon_button",
    "tool_button",
]
