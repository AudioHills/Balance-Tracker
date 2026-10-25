"""Reusable widgets: layout helpers, cards, money and date inputs."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QTextCharFormat
from PySide6.QtWidgets import (
    QButtonGroup,
    QCalendarWidget,
    QDoubleSpinBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import money
from . import theme

MASK = "******"  # shown instead of a balance while it's hidden


# --------------------------------------------------------------------------
# Layout helpers
# --------------------------------------------------------------------------
def label(text: str = "", obj: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


def hbox(*parts, spacing: int = 10, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    """A row of widgets/layouts. None adds a stretch, an int adds fixed spacing."""
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in parts:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay


def clear_layout(lay: QLayout) -> None:
    """Remove (and delete) everything in a layout."""
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            # Hide now: deleteLater() waits for the event loop, and until then the widget would
            # still be drawn, at a default size, over the rest of its card.
            it.widget().hide()
            it.widget().deleteLater()
        elif it.layout():
            clear_layout(it.layout())
            it.layout().deleteLater()


def repolish(w: QWidget) -> None:
    """Re-apply the stylesheet after changing an objectName or dynamic property."""
    w.style().unpolish(w)
    w.style().polish(w)


def chips(options, on_click, parent: QWidget, checked: int = 0) -> list[QPushButton]:
    """Mutually exclusive chip buttons for [(text, value)]. Read the choice with chosen()."""
    group = QButtonGroup(parent)
    out = []
    for text, value in options:
        b = QPushButton(text)
        b.setObjectName("Chip")
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setProperty("value", value)
        b.clicked.connect(on_click)
        group.addButton(b)
        out.append(b)
    out[checked].setChecked(True)
    return out


def chosen(buttons: list[QPushButton]):
    """The value of the checked chip (the first one's if none is checked)."""
    return next((b.property("value") for b in buttons if b.isChecked()), buttons[0].property("value"))


def select_chip(buttons: list[QPushButton], value) -> None:
    for b in buttons:
        b.setChecked(b.property("value") == value)


# --------------------------------------------------------------------------
# Cards and read-outs
# --------------------------------------------------------------------------
class Card(QFrame):
    def __init__(self, parent=None, padding: int = 18, spacing: int = 10):
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(padding, padding, padding, padding)
        self.lay.setSpacing(spacing)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(16, 24, 40, 18))
        self.setGraphicsEffect(shadow)


class StatCard(Card):
    """A titled number with a short explanation underneath."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent, padding=16, spacing=4)
        self.title = label(title, "StatTitle")
        self.value = label("—", "StatValue")
        self.sub = label("", "StatSub", wrap=True)
        self.title_row = QHBoxLayout()
        self.title_row.setContentsMargins(0, 0, 0, 0)
        self.title_row.addWidget(self.title, 1)
        self.lay.addLayout(self.title_row)
        self.lay.addWidget(self.value)
        self.lay.addWidget(self.sub)
        self.lay.addStretch(1)
        self.setMinimumWidth(170)

    def set(self, value: str, sub: str = "", tone: str | None = None):
        self.value.setText(value)
        self.sub.setText(sub)
        self.value.setStyleSheet(f"color: {theme.colors()[tone or 'text']};")


class Metric(QWidget):
    """A small titled figure for use inside a card (a lighter StatCard)."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.title = label(title, "StatTitle")
        self.value = label("—", "MetricValue")
        self.sub = label("", "Hint", wrap=True)
        for w in (self.title, self.value, self.sub):
            lay.addWidget(w)
        lay.addStretch(1)

    def set(self, value: str, sub: str = "", tone: str | None = None):
        self.value.setText(value)
        self.sub.setText(sub)
        self.value.setStyleSheet(f"color: {theme.colors()[tone or 'text']};")


class Banner(QLabel):
    """A coloured message strip (tone: warning | negative | positive)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setWordWrap(True)
        self.hide()

    def show_message(self, text: str, tone: str = "warning"):
        self.setProperty("tone", tone)
        repolish(self)
        self.setText(text)
        self.show()


def eye_icon(is_open: bool, color: str, size: int = 18) -> QIcon:
    """Open eye = balance showing; eye with a slash = balance hidden."""
    s = size * 2
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), s * 0.08, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    path = QPainterPath(QPointF(s * 0.08, s * 0.5))
    path.quadTo(QPointF(s * 0.5, s * 0.08), QPointF(s * 0.92, s * 0.5))
    path.quadTo(QPointF(s * 0.5, s * 0.92), QPointF(s * 0.08, s * 0.5))
    p.drawPath(path)
    p.drawEllipse(QPointF(s * 0.5, s * 0.5), s * 0.13, s * 0.13)
    if not is_open:
        p.drawLine(QPointF(s * 0.16, s * 0.84), QPointF(s * 0.84, s * 0.16))
    p.end()
    return QIcon(pm)


class EyeButton(QPushButton):
    """Small flat button that shows/hides a balance."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EyeButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(30, 26)
        self.setIconSize(QSize(18, 18))
        self.set_state(False)

    def set_state(self, hidden: bool):
        self.setIcon(eye_icon(not hidden, theme.colors()["muted"]))
        self.setToolTip("Show balance" if hidden else "Hide balance")


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------
class MoneySpin(QDoubleSpinBox):
    """An amount box in the current currency, read and written in cents."""

    def __init__(self, allow_negative: bool = False, parent=None):
        super().__init__(parent)
        self.setDecimals(2)
        self.setRange(-99_999_999 if allow_negative else 0, 99_999_999)
        self.setGroupSeparatorShown(True)
        self.setPrefix(money.symbol())
        self.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setMinimumWidth(140)

    def cents(self) -> int:
        return money.to_cents(self.value())

    def set_cents(self, cents: int):
        self.setValue(cents / 100)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        QTimer.singleShot(0, self.selectAll)


def to_qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def from_qdate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


def calendar_icon(color: str, size: int = 18) -> QIcon:
    s = size * 2
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), s * 0.08))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(s * 0.12, s * 0.2, s * 0.76, s * 0.68), s * 0.1, s * 0.1)
    p.drawLine(QPointF(s * 0.12, s * 0.4), QPointF(s * 0.88, s * 0.4))
    p.drawLine(QPointF(s * 0.32, s * 0.1), QPointF(s * 0.32, s * 0.28))
    p.drawLine(QPointF(s * 0.68, s * 0.1), QPointF(s * 0.68, s * 0.28))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    for i in range(3):
        for j in range(2):
            p.drawEllipse(QPointF(s * (0.3 + i * 0.2), s * (0.56 + j * 0.16)), s * 0.045, s * 0.045)
    p.end()
    return QIcon(pm)


class CalendarPopup(QFrame):
    """Floating month calendar shown under a DateField."""

    picked = Signal(QDate)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("CalendarPopup")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        self.cal = QCalendarWidget()
        self.cal.setObjectName("Calendar")
        self.cal.setGridVisible(False)
        self.cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.cal.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        self.cal.setMinimumSize(320, 250)
        self.cal.clicked.connect(self._pick)
        self.cal.activated.connect(self._pick)
        lay.addWidget(self.cal)
        today = QPushButton("Today")
        today.setObjectName("Chip")
        today.clicked.connect(lambda: self._pick(QDate.currentDate()))
        lay.addLayout(hbox(None, today))

    def _pick(self, d: QDate):
        if self.cal.minimumDate() <= d <= self.cal.maximumDate():
            self.picked.emit(d)
            self.hide()

    def open_at(self, anchor: QWidget, current: QDate, lo: QDate, hi: QDate):
        col = theme.colors()
        self.cal.setDateRange(lo, hi)
        self.cal.setSelectedDate(current)
        for day in (Qt.Saturday, Qt.Sunday):
            wk = QTextCharFormat()
            wk.setForeground(QColor(col["muted"]))
            self.cal.setWeekdayTextFormat(day, wk)
        self.cal.setDateTextFormat(QDate(), QTextCharFormat())  # clear old marks
        tf = QTextCharFormat()
        tf.setFontWeight(QFont.Bold)
        tf.setForeground(QColor(col["accent"]))
        self.cal.setDateTextFormat(QDate.currentDate(), tf)
        hdr = QTextCharFormat()
        hdr.setForeground(QColor(col["muted"]))
        hdr.setBackground(QColor(col["surface"]))
        self.cal.setHeaderTextFormat(hdr)
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 4))
        screen = anchor.screen().availableGeometry() if anchor.screen() else None
        if screen is not None:
            if pos.y() + self.height() > screen.bottom():
                pos = anchor.mapToGlobal(QPoint(0, -self.height() - 4))
            pos.setX(min(pos.x(), screen.right() - self.width()))
        self.move(pos)
        self.show()
        self.cal.setFocus()


class DateField(QPushButton):
    """A date box that opens a clickable calendar. API mirrors the bits of QDateEdit we use,
    plus value() for a Python date."""

    dateChanged = Signal(QDate)

    def __init__(self, d: QDate | date, parent=None):
        super().__init__(parent)
        self.setObjectName("DateField")
        self.setCursor(Qt.PointingHandCursor)
        self._date = _qdate(d)
        self._min = QDate(1990, 1, 1)
        self._max = QDate(2100, 12, 31)
        self.setMinimumWidth(190)
        self.setIconSize(QSize(18, 18))
        self._popup = None
        self.clicked.connect(self.open_calendar)
        self._render()

    def _render(self):
        self.setText(self._date.toString("ddd MMM d, yyyy"))
        self.setIcon(calendar_icon(theme.colors()["muted"]))
        self.setToolTip("Click to pick a date · arrow keys move a day · T for today")

    def open_calendar(self):
        if self._popup is None:
            self._popup = CalendarPopup(self)
            self._popup.picked.connect(self.setDate)
        self._popup.open_at(self, self._date, self._min, self._max)

    def date(self) -> QDate:
        return self._date

    def value(self) -> date:
        return from_qdate(self._date)

    def setDate(self, d: QDate | date):
        d = max(self._min, min(self._max, _qdate(d)))
        if d != self._date:
            self._date = d
            self._render()
            self.dateChanged.emit(d)

    def setMinimumDate(self, d: QDate | date):
        self._min = _qdate(d)
        if self._date < self._min:
            self.setDate(self._min)

    def setMaximumDate(self, d: QDate | date):
        self._max = _qdate(d)
        if self._date > self._max:
            self.setDate(self._max)

    def wheelEvent(self, e):  # scroll to nudge a day at a time
        self.setDate(self._date.addDays(1 if e.angleDelta().y() > 0 else -1))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Up, Qt.Key_Right, Qt.Key_Plus):
            self.setDate(self._date.addDays(1))
        elif e.key() in (Qt.Key_Down, Qt.Key_Left, Qt.Key_Minus):
            self.setDate(self._date.addDays(-1))
        elif e.key() == Qt.Key_T:
            self.setDate(QDate.currentDate())
        else:
            super().keyPressEvent(e)


def _qdate(d: QDate | date) -> QDate:
    return to_qdate(d) if isinstance(d, date) else d


def date_edit(d: date) -> DateField:
    return DateField(d)
