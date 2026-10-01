"""Light/dark colour palettes and the application stylesheet."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPalette, QPen

LIGHT = {
    "bg": "#F3F5FA", "surface": "#FFFFFF", "surface2": "#F0F2F8", "border": "#E2E6EF",
    "text": "#18202F", "muted": "#677086", "accent": "#4F5FE8", "accent_hover": "#3E4DD6",
    "accent_soft": "#E8EBFF", "positive": "#13A35A", "negative": "#E0414B", "warning": "#D98A0B",
    "positive_soft": "#E3F6EC", "negative_soft": "#FDE8EA", "warning_soft": "#FFF3DC",
    "today": "#FFF8E1", "row_alt": "#F8F9FC", "sidebar": "#FFFFFF", "selection": "#DCE1FF",
}

DARK = {
    "bg": "#0E1117", "surface": "#161A22", "surface2": "#1D222C", "border": "#272D39",
    "text": "#E7EAF1", "muted": "#8C95A8", "accent": "#7D8CFF", "accent_hover": "#93A0FF",
    "accent_soft": "#232849", "positive": "#3DD68C", "negative": "#FF6B73", "warning": "#F5B544",
    "positive_soft": "#15301F", "negative_soft": "#3A1C20", "warning_soft": "#3A2E14",
    "today": "#2A2614", "row_alt": "#191D26", "sidebar": "#12151C", "selection": "#2C3466",
}

_current = dict(LIGHT)


def is_dark() -> bool:
    return _current["bg"] == DARK["bg"]


def colors() -> dict:
    return _current


def c(name: str) -> QColor:
    return QColor(_current[name])


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        return False


def _arrow_image(color: str) -> str:
    """Write a small chevron PNG for combo-box arrows and return its path (QSS needs a file)."""
    folder = Path(tempfile.gettempdir()) / "BalanceTracker-ui"
    folder.mkdir(exist_ok=True)
    path = folder / f"chevron-{color.strip('#')}.png"
    if not path.exists():
        img = QImage(24, 24, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(color), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        path_ = QPainterPath(QPointF(6, 9))
        path_.lineTo(12, 15)
        path_.lineTo(18, 9)
        p.drawPath(path_)
        p.end()
        img.save(str(path))
    return path.as_posix()


def apply_theme(app, mode: str) -> None:
    dark = system_is_dark() if mode == "system" else mode == "dark"
    _current.clear()
    _current.update(DARK if dark else LIGHT)
    p = _current

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(p["bg"]))
    pal.setColor(QPalette.WindowText, QColor(p["text"]))
    pal.setColor(QPalette.Base, QColor(p["surface"]))
    pal.setColor(QPalette.AlternateBase, QColor(p["row_alt"]))
    pal.setColor(QPalette.Text, QColor(p["text"]))
    pal.setColor(QPalette.Button, QColor(p["surface"]))
    pal.setColor(QPalette.ButtonText, QColor(p["text"]))
    pal.setColor(QPalette.Highlight, QColor(p["selection"]))
    pal.setColor(QPalette.HighlightedText, QColor(p["text"]))
    pal.setColor(QPalette.ToolTipBase, QColor(p["surface2"]))
    pal.setColor(QPalette.ToolTipText, QColor(p["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(p["muted"]))
    app.setPalette(pal)
    try:
        arrow = _arrow_image(p["muted"])
    except OSError:
        arrow = ""
    app.setStyleSheet(STYLESHEET.format(arrow=arrow, **p))


STYLESHEET = """
* {{ font-size: 10pt; }}
QWidget {{ color: {text}; }}
QMainWindow, QDialog, #Page {{ background: {bg}; }}
QToolTip {{ background: {surface2}; color: {text}; border: 1px solid {border}; padding: 6px; border-radius: 6px; }}

/* ---------- sidebar ---------- */
#Sidebar {{ background: {sidebar}; border-right: 1px solid {border}; }}
#Brand {{ font-size: 14pt; font-weight: 700; }}
#BrandSub {{ color: {muted}; font-size: 9pt; }}
#NavButton {{
    text-align: left; padding: 10px 14px; border: none; border-radius: 10px;
    background: transparent; color: {muted}; font-weight: 600;
}}
#NavButton:hover {{ background: {surface2}; color: {text}; }}
#NavButton:checked {{ background: {accent_soft}; color: {accent}; }}
QPushButton#ThemeToggle {{
    border-radius: 18px; padding: 0; font-size: 14pt; background: {surface2}; border: 1px solid {border};
}}
QPushButton#ThemeToggle:hover {{ border-color: {accent}; color: {accent}; }}
#SidebarBalanceLabel {{ color: {muted}; font-size: 9pt; }}
#SidebarBalance {{ font-size: 15pt; font-weight: 700; }}

/* ---------- typography ---------- */
#PageTitle {{ font-size: 20pt; font-weight: 700; }}
#PageSubtitle {{ color: {muted}; }}
#SectionTitle {{ font-size: 12pt; font-weight: 700; }}
#Muted {{ color: {muted}; }}
#Hint {{ color: {muted}; font-size: 9pt; }}

/* ---------- cards ---------- */
#Card {{ background: {surface}; border: 1px solid {border}; border-radius: 14px; }}
#StatTitle {{ color: {muted}; font-size: 9pt; font-weight: 600; }}
#StatValue {{ font-size: 18pt; font-weight: 700; }}
#StatSub {{ color: {muted}; font-size: 9pt; }}
#Banner {{ border-radius: 12px; padding: 12px 16px; font-weight: 600; }}
#Banner[tone="warning"] {{ background: {warning_soft}; color: {warning}; }}
#Banner[tone="negative"] {{ background: {negative_soft}; color: {negative}; }}
#Banner[tone="positive"] {{ background: {positive_soft}; color: {positive}; }}

/* ---------- buttons ---------- */
QPushButton {{
    background: {surface}; border: 1px solid {border}; border-radius: 9px;
    padding: 7px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: {surface2}; }}
QPushButton:disabled {{ color: {muted}; }}
QPushButton#Primary {{ background: {accent}; border: 1px solid {accent}; color: white; }}
QPushButton#Primary:hover {{ background: {accent_hover}; }}
QPushButton#Danger {{ color: {negative}; }}
QPushButton#Chip {{ border-radius: 14px; padding: 5px 12px; }}
QPushButton#Chip:checked {{ background: {accent_soft}; color: {accent}; border-color: {accent}; }}

/* ---------- inputs ---------- */
QLineEdit, QComboBox, QTimeEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 6px 8px;
    selection-background-color: {selection};
}}
QLineEdit:focus, QComboBox:focus, QTimeEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {accent};
}}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{arrow}"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border}; selection-background-color: {selection}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QCheckBox {{ spacing: 8px; }}
QPushButton#DateField {{
    text-align: left; font-weight: 500; padding: 6px 10px; border-radius: 8px;
    background: {surface}; border: 1px solid {border};
}}
QPushButton#DateField:hover {{ border-color: {accent}; background: {surface}; }}
#CalendarPopup {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
QCalendarWidget QWidget {{ alternate-background-color: {surface}; background: {surface}; }}
QCalendarWidget #qt_calendar_navigationbar {{ background: {surface}; padding: 2px; }}
QCalendarWidget QToolButton {{
    color: {text}; background: transparent; padding: 6px 10px; border-radius: 8px;
    font-weight: 700; font-size: 11pt;
}}
QCalendarWidget QToolButton:hover {{ background: {surface2}; }}
QCalendarWidget QToolButton::menu-indicator {{ image: none; width: 0; }}
QCalendarWidget #qt_calendar_prevmonth, QCalendarWidget #qt_calendar_nextmonth {{ qproperty-icon: none; min-width: 28px; }}
QCalendarWidget #qt_calendar_prevmonth {{ qproperty-text: "‹"; font-size: 16pt; }}
QCalendarWidget #qt_calendar_nextmonth {{ qproperty-text: "›"; font-size: 16pt; }}
QCalendarWidget QSpinBox {{ min-width: 70px; }}
QCalendarWidget QAbstractItemView {{
    background: {surface}; color: {text}; outline: 0; font-size: 10pt;
    selection-background-color: {accent}; selection-color: white;
}}
QCalendarWidget QAbstractItemView:disabled {{ color: {border}; }}
QCalendarWidget QTableView::item {{ padding: 0; }}

/* ---------- tables ---------- */
QTableView {{
    background: {surface}; border: 1px solid {border}; border-radius: 12px;
    gridline-color: transparent; alternate-background-color: {row_alt};
    selection-background-color: {selection}; selection-color: {text};
}}
QTableView::item {{ padding: 4px 8px; border: none; }}
QHeaderView::section {{
    background: {surface}; color: {muted}; border: none; border-bottom: 1px solid {border};
    padding: 8px; font-weight: 600; font-size: 9pt;
}}
QTableCornerButton::section {{ background: {surface}; border: none; }}

/* ---------- misc ---------- */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QMenu {{ background: {surface}; border: 1px solid {border}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {surface2}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}
QListWidget {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; }}
"""
