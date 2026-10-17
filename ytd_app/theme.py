"""Design token system, Light/Dark palettes, QSS generator, and ThemeManager."""
from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPalette
from PyQt6.QtWidgets import QApplication

LIGHT: dict[str, str] = {
    "bg": "#FAFAFA",
    "surface": "#FFFFFF",
    "sidebar": "#F4F4F5",
    "border": "#E4E4E7",
    "border_strong": "#D4D4D8",
    "hover": "#F4F4F5",
    "pressed": "#E4E4E7",
    "text": "#18181B",
    "text_secondary": "#3F3F46",
    "muted": "#71717A",
    "primary": "#18181B",
    "primary_hover": "#27272A",
    "on_primary": "#FFFFFF",
    "focus": "#18181B",
    "danger": "#DC2626",
    "danger_bg": "#FEF2F2",
    "success": "#16A34A",
    "warning": "#D97706",
    "info": "#2563EB",
    "purple": "#7C3AED",
    "scrollbar": "#D4D4D8",
    "scrollbar_hover": "#A1A1AA",
}

DARK: dict[str, str] = {
    "bg": "#09090B",
    "surface": "#18181B",
    "sidebar": "#111113",
    "border": "#27272A",
    "border_strong": "#3F3F46",
    "hover": "#27272A",
    "pressed": "#3F3F46",
    "text": "#FAFAFA",
    "text_secondary": "#D4D4D8",
    "muted": "#A1A1AA",
    "primary": "#FAFAFA",
    "primary_hover": "#E4E4E7",
    "on_primary": "#18181B",
    "focus": "#FAFAFA",
    "danger": "#F87171",
    "danger_bg": "#2D1517",
    "success": "#4ADE80",
    "warning": "#FBBF24",
    "info": "#60A5FA",
    "purple": "#A78BFA",
    "scrollbar": "#3F3F46",
    "scrollbar_hover": "#52525B",
}

# Status -> (light_hex, dark_hex)
STATUS_COLORS: dict[str, tuple[str, str]] = {
    "queued": ("#71717A", "#A1A1AA"),
    "downloading": ("#2563EB", "#60A5FA"),
    "paused": ("#D97706", "#FBBF24"),
    "processing": ("#7C3AED", "#A78BFA"),
    "converting": ("#7C3AED", "#A78BFA"),
    "done": ("#16A34A", "#4ADE80"),
    "error": ("#DC2626", "#F87171"),
    "cancelled": ("#71717A", "#A1A1AA"),
}


def tokens_for(mode: str) -> dict[str, str]:
    return DARK if mode == "dark" else LIGHT


def status_color(status: str, mode: str = "light") -> str:
    light_c, dark_c = STATUS_COLORS.get(status, ("#71717A", "#A1A1AA"))
    return dark_c if mode == "dark" else light_c


def resolve_mode(pref: str) -> str:
    pref_norm = (pref or "system").strip().lower()
    if pref_norm in ("light", "dark"):
        return pref_norm
    try:
        hints = QGuiApplication.styleHints()
        if hints is not None and hasattr(hints, "colorScheme"):
            scheme = hints.colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return "dark"
            if scheme == Qt.ColorScheme.Light:
                return "light"
    except Exception:
        pass
    # Windows registry fallback
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if int(val) == 1 else "dark"
    except Exception:
        return "light"


def build_palette(t: dict[str, str]) -> QPalette:
    pal = QPalette()
    bg = QColor(t["bg"])
    surface = QColor(t["surface"])
    text = QColor(t["text"])
    muted = QColor(t["muted"])
    hover = QColor(t["hover"])
    primary = QColor(t["primary"])
    on_primary = QColor(t["on_primary"])

    pal.setColor(QPalette.ColorRole.Window, bg)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, surface)
    pal.setColor(QPalette.ColorRole.AlternateBase, hover)
    pal.setColor(QPalette.ColorRole.ToolTipBase, primary)
    pal.setColor(QPalette.ColorRole.ToolTipText, on_primary)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.PlaceholderText, muted)
    pal.setColor(QPalette.ColorRole.Button, surface)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.Mid, QColor(t["border_strong"]))
    pal.setColor(QPalette.ColorRole.Dark, QColor(t["border_strong"]))
    pal.setColor(QPalette.ColorRole.BrightText, QColor(t["danger"]))
    pal.setColor(QPalette.ColorRole.Highlight, primary)
    pal.setColor(QPalette.ColorRole.HighlightedText, on_primary)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, muted)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, muted)
    return pal


def build_stylesheet(t: dict[str, str]) -> str:
    from pathlib import Path

    is_dark = t.get("bg") == DARK["bg"]
    chk_name = "check-mark-dark.svg" if is_dark else "check-mark-light.svg"
    chk_path = (Path(__file__).resolve().parent / "assets" / "icons" / chk_name).as_posix()
    return f"""
QMainWindow, QDialog {{
    background-color: {t['bg']};
    color: {t['text']};
}}

QWidget {{
    font-family: "Inter", "Segoe UI Variable Text", "Segoe UI", -apple-system, sans-serif;
    font-size: 13px;
    color: {t['text']};
}}

QWidget#rootContainer, QWidget#pageContainer, QWidget#scrollContents {{
    background-color: transparent;
}}

QToolTip {{
    background-color: {t['primary']};
    color: {t['on_primary']};
    border: 1px solid {t['border_strong']};
    border-radius: 6px;
    padding: 5px 9px;
    font-size: 12px;
    font-weight: 500;
}}

/* Sidebar */
QFrame#sidebar {{
    background-color: {t['sidebar']};
    border-right: 1px solid {t['border']};
}}

QLabel#brandTop {{
    font-size: 15px;
    font-weight: 600;
    color: {t['text']};
}}

QLabel#brandBottom {{
    font-size: 12px;
    font-weight: 500;
    color: {t['muted']};
}}

QLabel#versionLabel {{
    font-size: 11px;
    font-weight: 500;
    color: {t['muted']};
    padding: 2px 10px;
}}

QPushButton#navItem {{
    text-align: left;
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 7px 10px;
    font-size: 13px;
    font-weight: 500;
    color: {t['text_secondary']};
    min-height: 20px;
}}

QPushButton#navItem:hover {{
    background-color: {t['hover']};
    color: {t['text']};
}}

QPushButton#navItem:checked {{
    background-color: {t['surface']};
    border: 1px solid {t['border']};
    color: {t['text']};
    font-weight: 600;
}}

/* Typography */
QLabel#pageTitle {{
    font-size: 20px;
    font-weight: 600;
    color: {t['text']};
}}

QLabel#sectionTitle {{
    font-size: 12px;
    font-weight: 600;
    color: {t['muted']};
    letter-spacing: 0.4px;
}}

QLabel#cardTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {t['text']};
}}

QLabel#mutedLabel {{
    font-size: 12px;
    font-weight: 400;
    color: {t['muted']};
}}

QLabel#statBarItem {{
    font-size: 12px;
    font-weight: 500;
    color: {t['muted']};
    padding: 0 4px;
}}

QLabel#metricValue {{
    font-size: 22px;
    font-weight: 600;
    color: {t['text']};
}}

/* Surface Cards & Containers */
QFrame#surfaceCard, QFrame#previewCard, QFrame#listCard, QFrame#metricCard {{
    background-color: {t['surface']};
    border: 1px solid {t['border']};
    border-radius: 10px;
}}

QFrame#dividerLine {{
    background-color: {t['border']};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}

/* Job Row in List */
QFrame#jobRow {{
    background-color: transparent;
    border: none;
    border-bottom: 1px solid {t['border']};
}}

QFrame#jobRow:hover {{
    background-color: {t['hover']};
}}

QLabel#cardThumbnail, QLabel#thumbnail {{
    background-color: {t['hover']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    color: {t['muted']};
    font-size: 11px;
    font-weight: 500;
}}

QLabel#metaBadge, QLabel#codecBadge {{
    background-color: {t['hover']};
    border: 1px solid {t['border']};
    border-radius: 5px;
    padding: 2px 7px;
    font-size: 11px;
    font-weight: 500;
    color: {t['text_secondary']};
}}

/* Inputs & Combos */
QLineEdit, QSpinBox, QComboBox {{
    background-color: {t['surface']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    padding: 5px 10px;
    color: {t['text']};
    font-weight: 400;
    min-height: 22px;
    selection-background-color: {t['primary']};
    selection-color: {t['on_primary']};
}}

QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{
    border-color: {t['border_strong']};
}}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {t['focus']};
}}

QLineEdit#urlInput {{
    font-size: 14px;
    font-weight: 400;
    padding: 7px 12px;
    min-height: 24px;
    border-radius: 8px;
}}

QLineEdit#searchInput {{
    padding: 4px 10px;
    min-height: 20px;
    border-radius: 7px;
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background-color: {t['surface']};
    color: {t['text']};
    border: 1px solid {t['border_strong']};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {t['hover']};
    selection-color: {t['text']};
    outline: 0;
}}

/* Segmented Control */
QFrame#segmentedFrame {{
    background-color: {t['hover']};
    border: 1px solid {t['border']};
    border-radius: 8px;
}}

QPushButton#segmentButton {{
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px 11px;
    font-size: 12px;
    font-weight: 500;
    color: {t['muted']};
    min-height: 20px;
}}

QPushButton#segmentButton:hover {{
    color: {t['text']};
}}

QPushButton#segmentButton:checked {{
    background-color: {t['surface']};
    color: {t['text']};
    font-weight: 600;
}}

/* Buttons */
QPushButton {{
    background-color: {t['surface']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    padding: 5px 12px;
    font-size: 13px;
    font-weight: 500;
    color: {t['text']};
    min-height: 22px;
}}

QPushButton:hover {{
    background-color: {t['hover']};
    border-color: {t['border_strong']};
}}

QPushButton:pressed {{
    background-color: {t['pressed']};
}}

QPushButton:disabled {{
    color: {t['muted']};
    background-color: {t['hover']};
    border-color: {t['border']};
}}

QPushButton#primaryButton {{
    background-color: {t['primary']};
    border: 1px solid {t['primary']};
    color: {t['on_primary']};
    font-weight: 600;
    padding: 7px 16px;
    min-height: 24px;
}}

QPushButton#primaryButton:hover {{
    background-color: {t['primary_hover']};
    border-color: {t['primary_hover']};
}}

QPushButton#primaryButton:disabled {{
    background-color: {t['hover']};
    border-color: {t['border']};
    color: {t['muted']};
}}

QPushButton#secondaryAccentButton {{
    background-color: {t['surface']};
    border: 1px solid {t['border_strong']};
    border-radius: 8px;
    padding: 6px 13px;
    font-weight: 500;
    color: {t['text']};
}}

QPushButton#secondaryAccentButton:hover {{
    background-color: {t['hover']};
}}

QPushButton#ghostButton, QPushButton#folderChip {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 4px 9px;
    font-size: 12px;
    font-weight: 500;
    color: {t['text_secondary']};
    min-height: 20px;
}}

QPushButton#ghostButton:hover, QPushButton#folderChip:hover {{
    background-color: {t['hover']};
    color: {t['text']};
}}

QPushButton#ghostButton:checked {{
    background-color: {t['hover']};
    border-color: {t['border']};
    color: {t['text']};
    font-weight: 600;
}}

QPushButton#iconButton, QPushButton#cardActionButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 7px;
    font-size: 12px;
    font-weight: 500;
    color: {t['text_secondary']};
    min-height: 20px;
}}

QPushButton#iconButton:hover, QPushButton#cardActionButton:hover {{
    background-color: {t['hover']};
    border-color: {t['border']};
    color: {t['text']};
}}

QPushButton#cardDangerButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 7px;
    font-size: 12px;
    font-weight: 500;
    color: {t['danger']};
    min-height: 20px;
}}

QPushButton#cardDangerButton:hover {{
    background-color: {t['danger_bg']};
    border-color: {t['danger']};
}}

/* Filter Chips */
QPushButton#tabButton {{
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
    font-weight: 500;
    color: {t['muted']};
    min-height: 20px;
}}

QPushButton#tabButton:hover {{
    color: {t['text']};
    background-color: {t['hover']};
}}

QPushButton#tabButton:checked {{
    background-color: {t['hover']};
    color: {t['text']};
    font-weight: 600;
}}

/* Checkboxes */
QCheckBox {{
    spacing: 8px;
    color: {t['text']};
    font-weight: 400;
}}

QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border-radius: 4px;
    border: 1px solid {t['border_strong']};
    background-color: {t['surface']};
}}

QCheckBox::indicator:hover {{
    border-color: {t['text']};
}}

QCheckBox::indicator:checked {{
    background-color: {t['primary']};
    border: 1px solid {t['primary']};
    image: url("{chk_path}");
}}

/* Progress Bar (thin 4px) */
QProgressBar {{
    background-color: {t['hover']};
    border: none;
    border-radius: 2px;
    min-height: 4px;
    max-height: 4px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {t['info']};
    border-radius: 2px;
}}

/* ScrollAreas & ScrollBars */
QScrollArea {{
    border: none;
    background-color: transparent;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px 0;
}}

QScrollBar::handle:vertical {{
    background: {t['scrollbar']};
    min-height: 28px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: {t['scrollbar_hover']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

/* Tables & Text Views */
QTableWidget {{
    background-color: {t['surface']};
    alternate-background-color: {t['bg']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    gridline-color: {t['border']};
    color: {t['text']};
    selection-background-color: {t['hover']};
    selection-color: {t['text']};
}}

QHeaderView::section {{
    background-color: {t['bg']};
    color: {t['muted']};
    font-weight: 600;
    font-size: 11px;
    border: none;
    border-bottom: 1px solid {t['border']};
    padding: 6px 8px;
}}

QPlainTextEdit, QTextBrowser {{
    background-color: {t['surface']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    padding: 10px;
    color: {t['text']};
}}

QPlainTextEdit {{
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
}}

/* Menus */
QMenu {{
    background-color: {t['surface']};
    border: 1px solid {t['border_strong']};
    border-radius: 8px;
    padding: 4px;
    color: {t['text']};
}}

QMenu::item {{
    padding: 6px 24px 6px 10px;
    border-radius: 5px;
    font-size: 12px;
}}

QMenu::item:selected {{
    background-color: {t['hover']};
    color: {t['text']};
}}

QMenu::separator {{
    height: 1px;
    background: {t['border']};
    margin: 4px 6px;
}}

/* Status Bar */
QStatusBar {{
    background-color: {t['surface']};
    color: {t['muted']};
    font-size: 12px;
    border-top: 1px solid {t['border']};
    padding: 2px 10px;
}}

QStatusBar::item {{
    border: none;
}}
"""


LIGHT_STYLESHEET = build_stylesheet(LIGHT)
DARK_STYLESHEET = build_stylesheet(DARK)


def status_badge_qss(status: str, mode: str = "light") -> str:
    col = status_color(status, mode)
    return f"QLabel {{ color: {col}; background: transparent; border: none; font-size: 12px; font-weight: 600; }}"


def progress_bar_qss(status: str, mode: str = "light") -> str:
    col = status_color(status, mode)
    t = tokens_for(mode)
    return f"""
        QProgressBar {{
            background-color: {t['hover']};
            border: none;
            border-radius: 2px;
            min-height: 4px;
            max-height: 4px;
        }}
        QProgressBar::chunk {{
            background-color: {col};
            border-radius: 2px;
        }}
    """


class ThemeManager(QObject):
    """Central theme controller supporting 'system', 'light', and 'dark'."""

    changed = pyqtSignal(str)  # emits resolved mode ("light" or "dark")

    def __init__(self) -> None:
        super().__init__()
        self._preference: str = "system"
        self._mode: str = resolve_mode("system")
        try:
            hints = QGuiApplication.styleHints()
            if hints is not None and hasattr(hints, "colorSchemeChanged"):
                hints.colorSchemeChanged.connect(self._on_system_scheme_changed)
        except Exception:
            pass

    @property
    def preference(self) -> str:
        return self._preference

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def tokens(self) -> dict[str, str]:
        return tokens_for(self._mode)

    def apply(self, preference: str = "system") -> str:
        self._preference = (preference or "system").strip().lower()
        if self._preference not in ("system", "light", "dark"):
            self._preference = "system"
        resolved = resolve_mode(self._preference)
        self._mode = resolved
        t = tokens_for(resolved)
        app = QApplication.instance()
        if app is not None:
            app.setPalette(build_palette(t))
            app.setStyleSheet(build_stylesheet(t))
        self.changed.emit(resolved)
        return resolved

    def _on_system_scheme_changed(self, *_args) -> None:
        if self._preference == "system":
            self.apply("system")


_THEME_MANAGER: ThemeManager | None = None


def theme_manager() -> ThemeManager:
    global _THEME_MANAGER
    if _THEME_MANAGER is None:
        _THEME_MANAGER = ThemeManager()
    return _THEME_MANAGER
