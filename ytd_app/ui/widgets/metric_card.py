"""Hardware metric card with 60-second QPainter sparkline chart."""
from __future__ import annotations

from collections import deque

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from ...theme import progress_bar_qss, status_color, theme_manager


class SparklineWidget(QWidget):
    """Smooth 60-second sparkline rendered with QPainter."""

    def __init__(
        self,
        status_key: str = "downloading",
        max_samples: int = 40,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._status_key = status_key
        self._samples: deque[float] = deque([0.0] * max_samples, maxlen=max_samples)
        self.setMinimumHeight(42)
        self.setMaximumHeight(48)
        theme_manager().changed.connect(lambda _m: self.update())

    def push_sample(self, pct: float) -> None:
        clamped = max(0.0, min(100.0, float(pct)))
        self._samples.append(clamped)
        self.update()

    def samples(self) -> list[float]:
        return list(self._samples)

    def paintEvent(self, _event) -> None:
        w = self.width()
        h = self.height()
        if w <= 4 or h <= 4 or len(self._samples) < 2:
            return

        mode = theme_manager().mode
        line_hex = status_color(self._status_key, mode)
        line_color = QColor(line_hex)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pad_top = 4.0
        pad_bottom = 3.0
        usable_h = max(1.0, h - pad_top - pad_bottom)
        n = len(self._samples)
        step_x = w / float(n - 1)

        points: list[QPointF] = []
        for idx, val in enumerate(self._samples):
            x = idx * step_x
            y = pad_top + usable_h * (1.0 - (val / 100.0))
            points.append(QPointF(x, y))

        line_path = QPainterPath()
        line_path.moveTo(points[0])
        for pt in points[1:]:
            line_path.lineTo(pt)

        area_path = QPainterPath(line_path)
        area_path.lineTo(QPointF(w, h))
        area_path.lineTo(QPointF(0.0, h))
        area_path.closeSubpath()

        grad = QLinearGradient(0.0, 0.0, 0.0, float(h))
        top_fill = QColor(line_color)
        top_fill.setAlpha(55 if mode == "light" else 75)
        bot_fill = QColor(line_color)
        bot_fill.setAlpha(0)
        grad.setColorAt(0.0, top_fill)
        grad.setColorAt(1.0, bot_fill)

        painter.fillPath(area_path, grad)
        pen = QPen(line_color, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(line_path)
        painter.end()


class MetricCard(QFrame):
    """Card showing title + icon, large primary number, thin progress bar, subtitle, and sparkline."""

    def __init__(
        self,
        title: str,
        icon_name: str,
        status_key: str = "downloading",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self._icon_name = icon_name
        self._status_key = status_key

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(16, 16)
        top.addWidget(self.icon_label)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("mutedLabel")
        top.addWidget(self.title_label)
        top.addStretch(1)
        layout.addLayout(top)

        self.value_label = QLabel("0%")
        self.value_label.setObjectName("metricValue")
        layout.addWidget(self.value_label)

        self.detail_label = QLabel("—")
        self.detail_label.setObjectName("mutedLabel")
        layout.addWidget(self.detail_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self.sparkline = SparklineWidget(status_key=status_key, parent=self)
        layout.addWidget(self.sparkline)

        self._apply_theme()
        theme_manager().changed.connect(self._apply_theme)

    def set_metric(self, value_text: str, detail_text: str, percent: float) -> None:
        pct_int = max(0, min(100, round(percent)))
        self.value_label.setText(value_text)
        self.detail_label.setText(detail_text)
        self.progress_bar.setValue(pct_int)
        self.sparkline.push_sample(percent)

    def _apply_theme(self, *_args) -> None:
        mode = theme_manager().mode
        t = theme_manager().tokens
        self.icon_label.setPixmap(icons.render_svg_pixmap(self._icon_name, t["muted"], size=15, dpr=2.0))
        self.progress_bar.setStyleSheet(progress_bar_qss(self._status_key, mode))
