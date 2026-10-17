"""Hardware & system monitor page builder with metric cards, 60s sparklines, and system profile."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..widgets import MetricCard, SectionCard

if TYPE_CHECKING:
    from ..main_window import MainWindow


def build_hardware_page(win: MainWindow) -> QWidget:
    page = QWidget()
    page.setObjectName("pageContainer")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(24, 20, 24, 16)
    layout.setSpacing(14)

    header = QHBoxLayout()
    title = QLabel("Phần cứng")
    title.setObjectName("pageTitle")
    header.addWidget(title)
    sub = QLabel("Giám sát tài nguyên thời gian thực (biểu đồ 60 giây gần nhất)")
    sub.setObjectName("mutedLabel")
    header.addSpacing(8)
    header.addWidget(sub)
    header.addStretch(1)
    layout.addLayout(header)

    # 1. Metric Cards Grid (2 rows: 3 cards on top, 2 cards below)
    grid = QGridLayout()
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(12)

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

    grid.addWidget(win.metric_cpu, 0, 0, 1, 2)
    grid.addWidget(win.metric_gpu, 0, 2, 1, 2)
    grid.addWidget(win.metric_ram, 0, 4, 1, 2)
    grid.addWidget(win.metric_disk, 1, 0, 1, 3)
    grid.addWidget(win.metric_net, 1, 3, 1, 3)

    layout.addLayout(grid)

    # 2. System & Encoder Specification Card
    spec_card = SectionCard("Thông tin hệ thống & bộ mã hóa phần cứng")
    spec_grid = QGridLayout()
    spec_grid.setHorizontalSpacing(24)
    spec_grid.setVerticalSpacing(8)

    win.hw_cpu_name_label = QLabel("CPU: Đang nhận diện...")
    win.hw_cpu_name_label.setStyleSheet("font-weight: 500;")
    spec_grid.addWidget(win.hw_cpu_name_label, 0, 0)

    win.hw_gpu_name_label = QLabel("GPU: Đang nhận diện...")
    win.hw_gpu_name_label.setStyleSheet("font-weight: 500;")
    spec_grid.addWidget(win.hw_gpu_name_label, 0, 1)

    win.hw_os_ram_label = QLabel("Hệ điều hành & RAM: Đang kiểm tra...")
    win.hw_os_ram_label.setObjectName("mutedLabel")
    spec_grid.addWidget(win.hw_os_ram_label, 1, 0)

    win.hw_encoders_label = QLabel("Bộ mã hóa FFmpeg khả dụng: Đang kiểm tra phần cứng...")
    win.hw_encoders_label.setObjectName("mutedLabel")
    win.hw_encoders_label.setWordWrap(True)
    spec_grid.addWidget(win.hw_encoders_label, 1, 1)

    spec_card.body_layout.addLayout(spec_grid)
    layout.addWidget(spec_card)
    layout.addStretch(1)
    return page
