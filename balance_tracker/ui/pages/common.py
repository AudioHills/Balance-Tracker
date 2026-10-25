"""Building blocks shared by the main pages."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from ..widgets import label

if TYPE_CHECKING:
    from ..main_window import MainWindow


class Page:
    """A scrollable main page with a title row.

    `body` is the page's vertical layout and `header` the title row (add buttons to its right).
    The window calls refresh() whenever the data changes while the page is showing, and again
    when a page that missed changes is shown (`dirty`).
    """

    def __init__(self, ctx: MainWindow, title: str, subtitle: str = ""):
        self.ctx = ctx
        self.dirty = True
        self.widget = QScrollArea()
        self.widget.setWidgetResizable(True)
        inner = QWidget()
        inner.setObjectName("Page")
        self.widget.setWidget(inner)
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(32, 28, 32, 28)
        self.body.setSpacing(18)
        self.header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(label(title, "PageTitle"))
        self.subtitle = label(subtitle, "PageSubtitle", wrap=True)
        titles.addWidget(self.subtitle)
        self.header.addLayout(titles, 1)
        self.body.addLayout(self.header)

    def refresh(self) -> None:
        raise NotImplementedError

    def focus_search(self) -> bool:
        """Put the cursor in this page's search box (Ctrl+F). False if it has none."""
        return False


def table(headers: list[str], stretch_col: int = 1) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setFocusPolicy(Qt.NoFocus)
    t.verticalHeader().setDefaultSectionSize(38)
    h = t.horizontalHeader()
    h.setHighlightSections(False)
    for i in range(len(headers)):
        h.setSectionResizeMode(i, QHeaderView.Stretch if i == stretch_col else QHeaderView.ResizeToContents)
    t.setContextMenuPolicy(Qt.CustomContextMenu)
    return t


def borderless(t: QTableWidget) -> QTableWidget:
    """For a table that sits inside a card."""
    t.setAlternatingRowColors(False)
    t.setStyleSheet("QTableView { border: none; }")
    return t


def cell(text: str, align=Qt.AlignLeft, color: str | None = None, bold=False, italic=False, data=None):
    it = QTableWidgetItem(text)
    it.setTextAlignment(align | Qt.AlignVCenter)
    if color:
        it.setForeground(QBrush(QColor(theme.colors()[color])))
    if bold or italic:
        f = QFont()
        f.setBold(bold)
        f.setItalic(italic)
        it.setFont(f)
    if data is not None:
        it.setData(Qt.UserRole, data)
    return it


def add_row(t: QTableWidget, *cells: QTableWidgetItem | None) -> int:
    r = t.rowCount()
    t.insertRow(r)
    for c, it in enumerate(cells):
        if it is not None:
            t.setItem(r, c, it)
    return r


def row_data(t: QTableWidget, row: int, col: int = 0):
    """The Qt.UserRole value stored on a row (None for an empty or invalid row)."""
    it = t.item(row, col) if row >= 0 else None
    return it.data(Qt.UserRole) if it else None


def bal_color(bal: int, threshold: int) -> str:
    """Theme colour for a balance: red when overdrawn, amber below the cushion."""
    if bal < 0:
        return "negative"
    if bal < threshold:
        return "warning"
    return "text"


def signed_tone(cents: int) -> str:
    """Red for spent beyond the plan, green for ahead of it."""
    return "negative" if cents < 0 else "positive"
