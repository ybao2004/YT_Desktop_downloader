"""Hardware & system monitor page builder with responsive grid, QScrollArea, 60s sparklines, and system profile."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..widgets import FlowBar, MetricCard, SectionCard
from ...theme import density_metrics, theme_manager

if TYPE_CHECKING:
    from ..main_window import MainWindow


def build_hardware_page(win: MainWindow) -> QWidget:
    page = QWidget()
    page.setObjectName("pageContainer")
    outer_v = QVBoxLayout(page)
    m = density_metrics(theme_manager().ui_scale)
    outer_v.setContentsMargins(m["page_margin_x"], m["page_margin_top"], m["page_margin_x"], m["page_margin_bot"])
    outer_v.setSpacing(m["page_spacing"])

    header_bar = FlowBar(page, h_spacing=8, v_spacing=4)
    title = QLabel("Phần cứng")
    title.setObjectName("pageTitle")
    header_bar.addWidget(title)
    sub = QLabel("Giám sát tài nguyên thời gian thực (biểu đồ 60 giây gần nhất)")
    sub.setObjectName("mutedLabel")
    header_bar.addWidget(sub)
    outer_v.addWidget(header_bar)

    scroll = QScrollArea(page)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    content.setObjectName("scrollContents")
    layout = QVBoxLayout(content)
    layout.setContentsMargins(0, 0, 4, 8)
    layout.setSpacing(m["page_spacing"])

    # 1. Metric Cards Grid (responsive: 3+2 when wide, 2+2+1 when medium, 1-col when narrow)
    grid = QGridLayout()
    grid.setHorizontalSpacing(10 if theme_manager().ui_scale < 0.9 else 12)
    grid.setVerticalSpacing(10 if theme_manager().ui_scale < 0.9 else 12)

    win.metric_cpu = MetricCard("Vi xử lý (CPU)", "cpu", status_key="downloading")
    win.metric_gpu = MetricCard("Card đồ họa (GPU)", "microchip", status_key="converting")
    win.metric_ram = MetricCard("Bộ nhớ (RAM)", "memory-stick", status_key="done")
    win.metric_disk = MetricCard("Ổ đĩa lưu trữ", "hard-drive", status_key="paused")
    win.metric_net = MetricCard("Băng thông mạng", "activity", status_key="downloading")

    # Expose legacy attributes for compatibility with telemetry updates
    win.bar_cpu = win.metric_cpu.progress_bar
    win.lbl_cpu_detail = win.metric_cpu.detail_label
    win.bar_gpu = win.metric_gpu.progress_bar
    win.lbl_gpu_detail = win.metric_gpu.detail_label
    win.bar_ram = win.metric_ram.progress_bar
    win.lbl_ram_detail = win.metric_ram.detail_label
    win.bar_disk = win.metric_disk.progress_bar
    win.lbl_disk_detail = win.metric_disk.detail_label
    win.lbl_net_detail = win.metric_net.detail_label

    layout.addLayout(grid)

    # 2. System & Encoder Specification Card
    spec_card = SectionCard("Thông tin hệ thống & bộ mã hóa phần cứng")
    spec_grid = QGridLayout()
    spec_grid.setHorizontalSpacing(20)
    spec_grid.setVerticalSpacing(8)

    win.hw_cpu_name_label = QLabel("CPU: Đang nhận diện...")
    win.hw_cpu_name_label.setStyleSheet("font-weight: 500;")
    win.hw_cpu_name_label.setWordWrap(True)

    win.hw_gpu_name_label = QLabel("GPU: Đang nhận diện...")
    win.hw_gpu_name_label.setStyleSheet("font-weight: 500;")
    win.hw_gpu_name_label.setWordWrap(True)

    win.hw_os_ram_label = QLabel("Hệ điều hành & RAM: Đang kiểm tra...")
    win.hw_os_ram_label.setObjectName("mutedLabel")
    win.hw_os_ram_label.setWordWrap(True)

    win.hw_encoders_label = QLabel("Bộ mã hóa FFmpeg khả dụng: Đang kiểm tra phần cứng...")
    win.hw_encoders_label.setObjectName("mutedLabel")
    win.hw_encoders_label.setWordWrap(True)

    spec_card.body_layout.addLayout(spec_grid)
    layout.addWidget(spec_card)
    layout.addStretch(1)

    scroll.setWidget(content)
    outer_v.addWidget(scroll, 1)

    _last_mode = {"cols": ""}

    def reflow_hardware_grid(content_w: int = 900) -> None:
        if content_w >= 800:
            mode = "3col"
        elif content_w >= 540:
            mode = "2col"
        else:
            mode = "1col"
        if _last_mode["cols"] == mode:
            return
        _last_mode["cols"] = mode

        cards = (win.metric_cpu, win.metric_gpu, win.metric_ram, win.metric_disk, win.metric_net)
        for w in cards:
            grid.removeWidget(w)
        for w in (win.hw_cpu_name_label, win.hw_gpu_name_label, win.hw_os_ram_label, win.hw_encoders_label):
            spec_grid.removeWidget(w)

        if mode == "3col":
            grid.addWidget(win.metric_cpu, 0, 0, 1, 2)
            grid.addWidget(win.metric_gpu, 0, 2, 1, 2)
            grid.addWidget(win.metric_ram, 0, 4, 1, 2)
            grid.addWidget(win.metric_disk, 1, 0, 1, 3)
            grid.addWidget(win.metric_net, 1, 3, 1, 3)
            spec_grid.addWidget(win.hw_cpu_name_label, 0, 0)
            spec_grid.addWidget(win.hw_gpu_name_label, 0, 1)
            spec_grid.addWidget(win.hw_os_ram_label, 1, 0)
            spec_grid.addWidget(win.hw_encoders_label, 1, 1)
        elif mode == "2col":
            grid.addWidget(win.metric_cpu, 0, 0, 1, 1)
            grid.addWidget(win.metric_gpu, 0, 1, 1, 1)
            grid.addWidget(win.metric_ram, 1, 0, 1, 1)
            grid.addWidget(win.metric_disk, 1, 1, 1, 1)
            grid.addWidget(win.metric_net, 2, 0, 1, 2)
            spec_grid.addWidget(win.hw_cpu_name_label, 0, 0)
            spec_grid.addWidget(win.hw_gpu_name_label, 1, 0)
            spec_grid.addWidget(win.hw_os_ram_label, 2, 0)
            spec_grid.addWidget(win.hw_encoders_label, 3, 0)
        else:
            for r, c in enumerate(cards):
                grid.addWidget(c, r, 0, 1, 1)
            spec_grid.addWidget(win.hw_cpu_name_label, 0, 0)
            spec_grid.addWidget(win.hw_gpu_name_label, 1, 0)
            spec_grid.addWidget(win.hw_os_ram_label, 2, 0)
            spec_grid.addWidget(win.hw_encoders_label, 3, 0)

    def _apply_density(scale: float) -> None:
        dm = density_metrics(scale)
        outer_v.setContentsMargins(dm["page_margin_x"], dm["page_margin_top"], dm["page_margin_x"], dm["page_margin_bot"])
        outer_v.setSpacing(dm["page_spacing"])
        layout.setSpacing(dm["page_spacing"])
        sp = 9 if scale < 0.9 else 12
        grid.setHorizontalSpacing(sp)
        grid.setVerticalSpacing(sp)

    reflow_hardware_grid(900)
    win.reflow_hardware_grid = reflow_hardware_grid
    win.apply_hardware_density = _apply_density
    theme_manager().density_changed.connect(_apply_density)
    return page
