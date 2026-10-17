"""Application-level UI bootstrap: Fusion style, bundled Inter font, and ThemeManager."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication

from ..theme import theme_manager

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_FONTS_LOADED = False


def load_bundled_fonts() -> str:
    """Register bundled Inter static TTF fonts and return the resolved family name."""
    global _FONTS_LOADED
    family = "Inter"
    if not _FONTS_LOADED and FONTS_DIR.is_dir():
        for ttf in sorted(FONTS_DIR.glob("*.ttf")):
            font_id = QFontDatabase.addApplicationFont(str(ttf))
            if font_id >= 0:
                fams = QFontDatabase.applicationFontFamilies(font_id)
                if fams:
                    family = fams[0]
        _FONTS_LOADED = True
    return family


def setup_app(app: QApplication, theme_pref: str = "system") -> None:
    """Configure Fusion style, load Inter font, and apply initial color theme."""
    try:
        app.setStyle("Fusion")
    except Exception:
        pass
    family = load_bundled_fonts()
    default_font = QFont(family)
    default_font.setPixelSize(13)
    default_font.setWeight(QFont.Weight.Normal)
    app.setFont(default_font)
    theme_manager().apply(theme_pref)
