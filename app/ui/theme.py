"""Light/dark palettes and the app stylesheet."""

from __future__ import annotations

from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = {
    "bg": "#F4F5F7",
    "surface": "#FFFFFF",
    "surface_hover": "#F8F9FB",
    "border": "#E2E5EA",
    "text": "#1B1F24",
    "muted": "#687180",
    "faint": "#C9CED6",
    "accent": "#0E8F6A",
    "accent_hover": "#0B7A5A",
    "accent_text": "#FFFFFF",
    "danger": "#C93C3C",
    "danger_bg": "#FDF0F0",
    "input": "#FFFFFF",
}

DARK = {
    "bg": "#141619",
    "surface": "#1D2024",
    "surface_hover": "#23272C",
    "border": "#2E3238",
    "text": "#E6E8EB",
    "muted": "#98A0AB",
    "faint": "#3D434B",
    "accent": "#2FBF8F",
    "accent_hover": "#3FD3A1",
    "accent_text": "#0B1A14",
    "danger": "#F07373",
    "danger_bg": "#3A2224",
    "input": "#17191C",
}

# Current palette; custom-painted widgets read from this.
current: dict[str, str] = dict(LIGHT)

_QSS = Template("""
QWidget { color: $text; font-size: 10pt; }
QMainWindow, QDialog, #Page { background: $bg; }
QScrollArea, #CardList { background: transparent; border: none; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 4px; }

QLineEdit, QComboBox, QSpinBox {
    background: $input; border: 1px solid $border; border-radius: 8px;
    padding: 7px 10px; selection-background-color: $accent; selection-color: $accent_text;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid $accent; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border; selection-background-color: $surface_hover; selection-color: $text; }

QPushButton {
    background: $surface; border: 1px solid $border; border-radius: 8px; padding: 7px 14px;
}
QPushButton:hover { background: $surface_hover; }
QPushButton:disabled { color: $muted; }
QPushButton#Primary { background: $accent; color: $accent_text; border: 1px solid $accent; font-weight: 600; }
QPushButton#Primary:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#Danger { color: $danger; }
QPushButton#Danger:hover { background: $danger_bg; }
QPushButton#Flat { background: transparent; border: none; color: $muted; padding: 6px 8px; }
QPushButton#Flat:hover { color: $text; }

QTabBar { qproperty-drawBase: 0; }
QTabBar::tab {
    background: transparent; color: $muted; padding: 8px 14px; margin-right: 4px;
    border: none; border-bottom: 2px solid transparent; font-weight: 600;
}
QTabBar::tab:selected { color: $text; border-bottom: 2px solid $accent; }
QTabBar::tab:hover:!selected { color: $text; }

#Card { background: $surface; border: 1px solid $border; border-radius: 12px; }
#Card:hover { border: 1px solid $faint; background: $surface_hover; }
#Card[problem="true"] { border-left: 4px solid $danger; }
#Title { font-size: 11pt; font-weight: 600; }
#BigTitle { font-size: 15pt; font-weight: 600; }
#Muted { color: $muted; }
#Error { color: $danger; }
#ProblemText { color: $danger; font-weight: 600; }
#Banner { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 8px 12px; }
#BannerError { background: $danger_bg; color: $danger; border-radius: 8px; padding: 8px 12px; }
#Empty { color: $muted; font-size: 11pt; }
#Footer { border-top: 1px solid $border; }
#Section { color: $muted; font-weight: 600; font-size: 9pt; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $faint; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid $muted; border-radius: 4px; background: $input; }
QCheckBox::indicator:checked { background: $accent; border: 1px solid $accent; }
""")


def system_is_dark() -> bool:
    hints = QGuiApplication.styleHints()
    try:
        return hints.colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        return QGuiApplication.palette().window().color().lightness() < 128


def apply(app: QApplication, mode: str) -> None:
    dark = system_is_dark() if mode == "system" else mode == "dark"
    current.clear()
    current.update(DARK if dark else LIGHT)
    t = current

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(t["bg"]))
    pal.setColor(QPalette.WindowText, QColor(t["text"]))
    pal.setColor(QPalette.Base, QColor(t["input"]))
    pal.setColor(QPalette.AlternateBase, QColor(t["surface"]))
    pal.setColor(QPalette.Text, QColor(t["text"]))
    pal.setColor(QPalette.Button, QColor(t["surface"]))
    pal.setColor(QPalette.ButtonText, QColor(t["text"]))
    pal.setColor(QPalette.Highlight, QColor(t["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor(t["accent_text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(t["muted"]))
    pal.setColor(QPalette.Link, QColor(t["accent"]))
    pal.setColor(QPalette.LinkVisited, QColor(t["accent"]))
    pal.setColor(QPalette.ToolTipBase, QColor(t["surface"]))
    pal.setColor(QPalette.ToolTipText, QColor(t["text"]))
    app.setPalette(pal)
    app.setStyleSheet(_QSS.substitute(t))
