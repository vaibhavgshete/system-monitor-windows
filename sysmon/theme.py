"""Adwaita-like light/dark palettes, the global stylesheet, and tinted SVG icons.

All widgets read colours from `current()` at paint time and listen to `manager.changed`.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QImage, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    dark: bool
    window: str
    view: str
    text: str
    dim: str
    border: str
    accent: str
    selection: str
    hover: str
    button: str
    button_hover: str
    button_checked: str
    graph_bg: str
    graph_grid: str
    trough: str
    destructive: str


LIGHT = Theme(
    dark=False,
    window="#ffffff",
    view="#ffffff",
    text="#2e2e33",
    dim="#8a8a8f",
    border="#e3e3e6",
    accent="#3584e4",
    selection="#d0e1f8",
    hover="#f2f2f4",
    button="#ebebed",
    button_hover="#e0e0e3",
    button_checked="#e3e3e6",
    graph_bg="#fbfbfc",
    graph_grid="#e6e6e9",
    trough="#e8e8eb",
    destructive="#e01b24",
)

DARK = Theme(
    dark=True,
    window="#242424",
    view="#1e1e1e",
    text="#f2f2f2",
    dim="#9a9a9e",
    border="#363636",
    accent="#78aeed",
    selection="#2e4a6b",
    hover="#2c2c2e",
    button="#353537",
    button_hover="#404043",
    button_checked="#454548",
    graph_bg="#1b1b1c",
    graph_grid="#333336",
    trough="#3a3a3c",
    destructive="#ff5c5c",
)

# GNOME System Monitor's default per-CPU colours, in order.
_CPU_COLORS = [
    "#e01b24", "#ff7800", "#f6d32d", "#33d17a", "#26a269", "#62a0ea",
    "#1c71d8", "#613583", "#9141ac", "#c061cb", "#ffbe6f", "#f9f06b",
]

MEMORY_COLOR = "#9141ac"
SWAP_COLOR = "#33d17a"
NET_RX_COLOR = "#1c71d8"
NET_TX_COLOR = "#e01b24"
DISK_READ_COLOR = "#26a269"
DISK_WRITE_COLOR = "#ff7800"
_GPU_COLORS = ["#26a269", "#1c71d8", "#e5a50a", "#c061cb"]


def gpu_color(i: int) -> QColor:
    return QColor(_GPU_COLORS[i % len(_GPU_COLORS)])


def cpu_color(i: int) -> QColor:
    if i < len(_CPU_COLORS):
        return QColor(_CPU_COLORS[i])
    # Beyond 12 cores: spread extra hues evenly using the golden angle.
    h = ((i - len(_CPU_COLORS)) * 0.618034 + 0.08) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.55, 0.92)
    return QColor.fromRgbF(r, g, b)


# --- icons ---------------------------------------------------------------------------------

_SVG = {
    "processes": '<rect x="1" y="2" width="3" height="3" rx="1"/><rect x="6" y="2.5" width="9" height="2" rx="1"/>'
    '<rect x="1" y="6.5" width="3" height="3" rx="1"/><rect x="6" y="7" width="9" height="2" rx="1"/>'
    '<rect x="1" y="11" width="3" height="3" rx="1"/><rect x="6" y="11.5" width="9" height="2" rx="1"/>',
    "resources": '<path d="M8 2a7 7 0 0 0-4.95 11.95l1.41-1.41A5 5 0 1 1 13 9a5 5 0 0 1-1.46 3.54l1.41 1.41A7 7 0 0 0 8 2z"/>'
    '<path d="M11.3 4.9 7.2 8.3a1.2 1.2 0 1 0 1.6 1.6z"/>',
    "filesystems": '<path fill-rule="evenodd" d="M3.5 1h9A2.5 2.5 0 0 1 15 3.5v9a2.5 2.5 0 0 1-2.5 2.5h-9A2.5 2.5 0 0 1 1 12.5v-9A2.5 2.5 0 0 1 3.5 1zM3 3v7h10V3zm8.5 8.5a1 1 0 1 0 0 2 1 1 0 0 0 0-2z"/>',
    "search": '<path fill-rule="evenodd" d="M6.5 1a5.5 5.5 0 0 1 4.4 8.8l3.9 3.9-1.4 1.4-3.9-3.9A5.5 5.5 0 1 1 6.5 1zm0 2a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z"/>',
    "menu": '<rect x="2" y="3" width="12" height="2" rx="1"/><rect x="2" y="7" width="12" height="2" rx="1"/>'
    '<rect x="2" y="11" width="12" height="2" rx="1"/>',
    "app": '<path d="M8 1.2 14.8 8 8 14.8 1.2 8z"/>',
    "info": '<path fill-rule="evenodd" d="M8 1a7 7 0 1 1 0 14A7 7 0 0 1 8 1zm0 2a5 5 0 1 0 0 10A5 5 0 0 0 8 3z"/>'
    '<rect x="7" y="7" width="2" height="4.5" rx="1"/><circle cx="8" cy="5.2" r="1.1"/>',
}


def icon(name: str, color: str | None = None, size: int = 16) -> QIcon:
    """Render one of the built-in symbolic icons in `color` (theme text colour by default)."""
    fill = color or current().text
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="{fill}">{_SVG[name]}</svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.GlobalColor.transparent)
        pm.setDevicePixelRatio(scale)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(p, QRectF(0, 0, size, size))
        p.end()
        result.addPixmap(pm)
    return result


LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def app_icon() -> QIcon:
    """Window/taskbar icon from assets/logo.png, pre-scaled smoothly for every size Windows asks for."""
    logo = QImage(str(LOGO_PATH))
    if logo.isNull():
        return _fallback_icon()
    result = QIcon()
    for size in ICON_SIZES:
        result.addPixmap(
            QPixmap.fromImage(
                logo.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        )
    return result


def _fallback_icon() -> QIcon:
    """Used only if the logo file is missing: a white gauge on an accent-coloured rounded square."""
    result = QIcon()
    gauge = QSvgRenderer(
        QByteArray(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="#ffffff">{_SVG["resources"]}</svg>'.encode()
        )
    )
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#3584e4"))
        p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
        m = size * 0.16
        gauge.render(p, QRectF(m, m * 0.7, size - 2 * m, size - 2 * m))
        p.end()
        result.addPixmap(pm)
    return result


# --- theme manager ---------------------------------------------------------------------------


class ThemeManager(QObject):
    """Holds the active theme. mode is 'system', 'light' or 'dark'."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._mode = "system"
        self._theme = LIGHT
        self._hooked = False

    @property
    def theme(self) -> Theme:
        return self._theme

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        if not self._hooked and QGuiApplication.instance() is not None:
            QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _s: self._apply())
            self._hooked = True
        self._apply()

    def _system_is_dark(self) -> bool:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark

    def _apply(self) -> None:
        dark = self._system_is_dark() if self._mode == "system" else self._mode == "dark"
        self._theme = DARK if dark else LIGHT
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setPalette(_qpalette(self._theme))
            app.setStyleSheet(stylesheet(self._theme))
        self.changed.emit()


manager = ThemeManager()


def current() -> Theme:
    return manager.theme


def _qpalette(t: Theme) -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: t.window,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.view,
        QPalette.ColorRole.AlternateBase: t.hover,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.button,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.Highlight: t.selection,
        QPalette.ColorRole.HighlightedText: t.text,
        QPalette.ColorRole.ToolTipBase: t.view,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.PlaceholderText: t.dim,
        QPalette.ColorRole.Mid: t.border,
        QPalette.ColorRole.Accent: t.accent,
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(t.dim))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(t.dim))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(t.dim))
    return p


def stylesheet(t: Theme) -> str:
    return f"""
    QMainWindow, QDialog {{ background: {t.window}; }}
    QWidget {{ color: {t.text}; }}
    QLabel[dim="true"] {{ color: {t.dim}; }}
    #Separator {{ background: {t.border}; }}

    QToolButton#SectionHeader {{
        border: none; background: transparent; font-weight: 700; font-size: 11pt;
        padding: 2px 4px 2px 0;
    }}

    #HeaderBar {{ background: {t.window}; border-bottom: 1px solid {t.border}; }}
    #Switcher QToolButton {{
        border: none; border-radius: 6px; padding: 6px 14px;
        font-weight: 600; background: transparent;
    }}
    #Switcher QToolButton:hover {{ background: {t.hover}; }}
    #Switcher QToolButton:checked {{ background: {t.button_checked}; }}

    QToolButton#HeaderButton {{
        border: none; border-radius: 6px; padding: 6px; background: transparent;
    }}
    QToolButton#HeaderButton:hover {{ background: {t.hover}; }}
    QToolButton#HeaderButton:checked, QToolButton#HeaderButton:pressed {{ background: {t.button_checked}; }}
    QToolButton#HeaderButton::menu-indicator {{ image: none; width: 0; }}

    QPushButton {{
        background: {t.button}; border: none; border-radius: 6px;
        padding: 7px 16px; font-weight: 600;
    }}
    QPushButton:hover {{ background: {t.button_hover}; }}
    QPushButton:disabled {{ color: {t.dim}; }}
    QPushButton#Destructive {{ background: {t.destructive}; color: #ffffff; }}
    QPushButton#Destructive:hover {{ background: #c01c28; }}
    QPushButton#Suggested {{ background: {t.accent}; color: #ffffff; }}

    QLineEdit {{
        background: {t.button}; border: 2px solid transparent; border-radius: 8px;
        padding: 5px 8px; selection-background-color: {t.accent}; selection-color: #ffffff;
    }}
    QLineEdit:focus {{ border: 2px solid {t.accent}; }}

    QTreeView {{
        background: {t.view}; border: none; outline: 0;
        selection-background-color: {t.selection}; selection-color: {t.text};
    }}
    QTreeView::item {{ padding: 3px 2px; border: none; }}
    QTreeView::item:hover:!selected {{ background: {t.hover}; }}
    QTreeView::item:selected {{ background: {t.selection}; color: {t.text}; }}
    QHeaderView {{ background: {t.view}; border: none; }}
    QHeaderView::section {{
        background: {t.view}; color: {t.dim}; border: none;
        border-bottom: 1px solid {t.border}; padding: 6px 4px;
    }}
    QHeaderView::section:hover {{ color: {t.text}; }}

    QScrollArea {{ border: none; background: {t.window}; }}
    QScrollArea > QWidget > QWidget {{ background: {t.window}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.trough}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {t.dim}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t.trough}; border-radius: 3px; min-width: 30px; }}
    QScrollBar::handle:horizontal:hover {{ background: {t.dim}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

    QMenu {{ background: {t.view}; border: 1px solid {t.border}; padding: 6px; }}
    QMenu::item {{ padding: 6px 28px 6px 24px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {t.hover}; }}
    QMenu::item:disabled {{ color: {t.dim}; }}
    QMenu::separator {{ height: 1px; background: {t.border}; margin: 6px 4px; }}

    QComboBox {{
        background: {t.button}; border: none; border-radius: 6px; padding: 6px 10px; min-width: 120px;
    }}
    QComboBox:hover {{ background: {t.button_hover}; }}
    QComboBox QAbstractItemView {{
        background: {t.view}; border: 1px solid {t.border};
        selection-background-color: {t.hover}; selection-color: {t.text};
    }}
    QToolTip {{ background: {t.view}; color: {t.text}; border: 1px solid {t.border}; padding: 4px; }}
    """
