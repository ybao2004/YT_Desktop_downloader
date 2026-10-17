"""Lucide SVG icon loader with dynamic color tinting and HiDPI caching."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

from ..theme import theme_manager

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ICONS_DIR = ASSETS_DIR / "icons"

_ICON_CACHE: dict[tuple[str, str, int, int], QIcon] = {}
_SVG_TEXT_CACHE: dict[str, str] = {}


def available_icons() -> list[str]:
    if not ICONS_DIR.is_dir():
        return []
    return sorted(p.stem for p in ICONS_DIR.glob("*.svg"))


def _load_svg_text(name: str) -> str:
    if name in _SVG_TEXT_CACHE:
        return _SVG_TEXT_CACHE[name]
    path = ICONS_DIR / f"{name}.svg"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    _SVG_TEXT_CACHE[name] = text
    return text


def render_svg_pixmap(name: str, color: str, size: int = 16, dpr: float = 1.0) -> QPixmap:
    svg_text = _load_svg_text(name)
    px_size = max(1, round(size * dpr))
    pixmap = QPixmap(px_size, px_size)
    pixmap.fill(Qt.GlobalColor.transparent)
    if not svg_text:
        pixmap.setDevicePixelRatio(dpr)
        return pixmap

    tinted = svg_text.replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(tinted.encode("utf-8")))
    if renderer.isValid():
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        renderer.render(painter, QRectF(0, 0, px_size, px_size))
        painter.end()
    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def icon(name: str, color: str | None = None, size: int = 16) -> QIcon:
    """Return a cached QIcon rendered from `assets/icons/{name}.svg`."""
    tokens = theme_manager().tokens
    resolved_color = color or tokens["text_secondary"]
    dpr = 2.0
    app = QGuiApplication.instance()
    if app is not None:
        try:
            screen = app.primaryScreen()
            if screen is not None:
                dpr = max(1.0, float(screen.devicePixelRatio()))
        except Exception:
            dpr = 2.0

    key = (name, resolved_color, size, round(dpr * 100))
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached

    qicon = QIcon()
    normal_pix = render_svg_pixmap(name, resolved_color, size=size, dpr=dpr)
    disabled_pix = render_svg_pixmap(name, tokens["muted"], size=size, dpr=dpr)
    qicon.addPixmap(normal_pix, QIcon.Mode.Normal, QIcon.State.Off)
    qicon.addPixmap(disabled_pix, QIcon.Mode.Disabled, QIcon.State.Off)
    _ICON_CACHE[key] = qicon
    return qicon
