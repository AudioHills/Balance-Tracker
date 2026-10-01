"""Reusable widgets: cards, money inputs and the custom charts."""
from __future__ import annotations

import math
from datetime import date

from PySide6.QtCore import QDate, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QTextCharFormat,
)
from PySide6.QtWidgets import (
    QCalendarWidget, QDoubleSpinBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import money
from . import theme


def label(text: str = "", obj: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


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


def eye_icon(is_open: bool, color: str, size: int = 18) -> QIcon:
    """Open eye = balance showing; eye with a slash = balance hidden."""
    s = size * 2
    pm = QPixmap(s, s)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color), s * 0.08, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
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


MASK = "******"


class StatCard(Card):
    def __init__(self, title: str, parent=None):
        super().__init__(parent, padding=16, spacing=4)
        self.title = label(title, "StatTitle")
        self.value = label("—", "StatValue")
        self.sub = label("", "StatSub", wrap=True)
        self.title_row = QHBoxLayout()
        self.title_row.setContentsMargins(0, 0, 0, 0)
        self.title_row.addWidget(self.title, 1)
        self.lay.addLayout(self.title_row)
        for w in (self.value, self.sub):
            self.lay.addWidget(w)
        self.lay.addStretch(1)
        self.setMinimumWidth(170)

    def set(self, value: str, sub: str = "", tone: str | None = None):
        self.value.setText(value)
        self.sub.setText(sub)
        color = theme.colors()[tone] if tone else theme.colors()["text"]
        self.value.setStyleSheet(f"color: {color};")


class Banner(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Banner")
        self.setWordWrap(True)
        self.hide()

    def show_message(self, text: str, tone: str = "warning"):
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)
        self.setText(text)
        self.show()


class MoneySpin(QDoubleSpinBox):
    def __init__(self, allow_negative: bool = False, parent=None):
        super().__init__(parent)
        self.setDecimals(2)
        self.setRange(-99_999_999 if allow_negative else 0, 99_999_999)
        self.setGroupSeparatorShown(True)
        self.setPrefix(money._symbol)
        self.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setMinimumWidth(140)

    def cents(self) -> int:
        return money.to_cents(self.value())

    def set_cents(self, cents: int):
        self.setValue(cents / 100)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.selectAll)


def calendar_icon(color: str, size: int = 18) -> QIcon:
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size * 2
    pen = QPen(QColor(color), s * 0.08)
    p.setPen(pen)
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
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(col["text"]))
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
    """A date box that opens a clickable calendar. API mirrors the bits of QDateEdit we use."""

    dateChanged = Signal(QDate)

    def __init__(self, d: QDate, parent=None):
        super().__init__(parent)
        self.setObjectName("DateField")
        self.setCursor(Qt.PointingHandCursor)
        self._date = d
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
        self.setToolTip("Click to pick a date")

    def open_calendar(self):
        if self._popup is None:
            self._popup = CalendarPopup(self)
            self._popup.picked.connect(self.setDate)
        self._popup.open_at(self, self._date, self._min, self._max)

    def date(self) -> QDate:
        return self._date

    def setDate(self, d: QDate):
        d = max(self._min, min(self._max, d))
        if d != self._date:
            self._date = d
            self._render()
            self.dateChanged.emit(d)

    def setMinimumDate(self, d: QDate):
        self._min = d
        if self._date < d:
            self.setDate(d)

    def setMaximumDate(self, d: QDate):
        self._max = d
        if self._date > d:
            self.setDate(d)

    def wheelEvent(self, e):  # scroll to nudge a day at a time
        step = 1 if e.angleDelta().y() > 0 else -1
        self.setDate(self._date.addDays(step))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Up, Qt.Key_Right, Qt.Key_Plus):
            self.setDate(self._date.addDays(1))
        elif e.key() in (Qt.Key_Down, Qt.Key_Left, Qt.Key_Minus):
            self.setDate(self._date.addDays(-1))
        elif e.key() == Qt.Key_T:
            self.setDate(QDate.currentDate())
        else:
            super().keyPressEvent(e)


def hbox(*widgets, spacing: int = 10, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, int):
            lay.addSpacing(w)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------
def _nice_ticks(lo: float, hi: float, count: int = 5):
    if hi <= lo:
        hi = lo + 1
    raw = (hi - lo) / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    start = math.floor(lo / step) * step
    ticks = []
    v = start
    while v <= hi + step * 0.5:
        ticks.append(v)
        v += step
    return ticks


class BalanceChart(QWidget):
    """Step chart of the end-of-day balance, with hover read-out."""

    dayClicked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.points: list = []  # [(date, cents)]
        self.today: date | None = None
        self.threshold: int = 0
        self.hover: int | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.CrossCursor)

    def set_data(self, points, today: date, threshold: int):
        self.points = points
        self.today = today
        self.threshold = threshold
        self.hover = None
        self.update()

    # geometry ------------------------------------------------------------
    def _plot_rect(self) -> QRectF:
        return QRectF(64, 14, max(10, self.width() - 64 - 16), max(10, self.height() - 14 - 30))

    def _ranges(self):
        vals = [p[1] for p in self.points] + [0, self.threshold]
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.08 or 1000
        ticks = _nice_ticks(lo - pad, hi + pad)
        return ticks[0], ticks[-1], ticks

    def _x(self, i: int, r: QRectF) -> float:
        n = max(1, len(self.points))
        return r.left() + r.width() * i / n

    def _y(self, v: float, lo: float, hi: float, r: QRectF) -> float:
        return r.bottom() - (v - lo) / (hi - lo) * r.height()

    # painting ------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = theme.colors()
        r = self._plot_rect()
        if not self.points:
            p.setPen(QColor(col["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter, "Add a starting balance to see your forecast")
            return
        lo, hi, ticks = self._ranges()
        small = QFont(self.font())
        small.setPointSizeF(8.5)
        p.setFont(small)

        # grid + y labels
        for t in ticks:
            y = self._y(t, lo, hi, r)
            p.setPen(QPen(QColor(col["border"]), 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(col["muted"]))
            p.drawText(QRectF(0, y - 9, r.left() - 10, 18), Qt.AlignRight | Qt.AlignVCenter,
                       money.fmt_short(int(t)))

        # x labels: first of each month
        months = [(i, d) for i, (d, _) in enumerate(self.points) if d.day == 1]
        every = max(1, math.ceil(len(months) / max(1, r.width() / 70)))
        for k, (i, d) in enumerate(months):
            x = self._x(i, r)
            p.setPen(QPen(QColor(col["border"]), 1, Qt.DotLine))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            if k % every == 0:
                p.setPen(QColor(col["muted"]))
                text = d.strftime("%b") if d.month != 1 else d.strftime("%b %Y")
                p.drawText(QRectF(x + 4, r.bottom() + 6, 80, 18), Qt.AlignLeft, text)

        # step path
        path = QPainterPath()
        for i, (_, v) in enumerate(self.points):
            x0, x1 = self._x(i, r), self._x(i + 1, r)
            y = self._y(v, lo, hi, r)
            if i == 0:
                path.moveTo(x0, y)
            else:
                path.lineTo(x0, y)
            path.lineTo(x1, y)

        zero_y = self._y(0, lo, hi, r)
        fill = QPainterPath(path)
        fill.lineTo(r.right(), r.bottom())
        fill.lineTo(r.left(), r.bottom())
        fill.closeSubpath()
        grad = QLinearGradient(0, r.top(), 0, r.bottom())
        a = QColor(col["accent"])
        a.setAlpha(70)
        grad.setColorAt(0, a)
        a.setAlpha(0)
        grad.setColorAt(1, a)
        p.save()
        p.setClipRect(QRectF(r.left(), r.top(), r.width(), zero_y - r.top()))
        p.fillPath(fill, grad)
        p.restore()

        today_x = None
        if self.today:
            idx = next((i for i, (d, _) in enumerate(self.points) if d >= self.today), None)
            if idx is not None:
                today_x = self._x(idx, r)

        # line: faded in the past, solid in the future; red below zero
        regions = [
            (QRectF(r.left(), r.top() - 4, r.width(), zero_y - r.top() + 4), col["accent"]),
            (QRectF(r.left(), zero_y, r.width(), r.bottom() - zero_y + 4), col["negative"]),
        ]
        for rect, color in regions:
            for past in (True, False):
                clip = QRectF(rect)
                if today_x is not None:
                    if past:
                        clip.setRight(today_x)
                    else:
                        clip.setLeft(today_x)
                elif past:
                    continue
                if clip.width() <= 0 or clip.height() <= 0:
                    continue
                qc = QColor(color)
                if past and today_x is not None:
                    qc.setAlpha(110)
                p.save()
                p.setClipRect(clip)
                p.setPen(QPen(qc, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPath(path)
                p.restore()

        # zero + threshold lines
        if lo < 0 < hi:
            p.setPen(QPen(QColor(col["negative"]), 1))
            p.drawLine(QPointF(r.left(), zero_y), QPointF(r.right(), zero_y))
        if self.threshold > 0:
            ty = self._y(self.threshold, lo, hi, r)
            p.setPen(QPen(QColor(col["warning"]), 1, Qt.DashLine))
            p.drawLine(QPointF(r.left(), ty), QPointF(r.right(), ty))
            p.drawText(QRectF(r.right() - 160, ty - 18, 156, 16), Qt.AlignRight,
                       f"Cushion {money.fmt_short(self.threshold)}")

        # today marker
        if today_x is not None:
            p.setPen(QPen(QColor(col["muted"]), 1, Qt.DashLine))
            p.drawLine(QPointF(today_x, r.top()), QPointF(today_x, r.bottom()))
            p.setPen(QColor(col["muted"]))
            p.drawText(QRectF(today_x + 4, r.top(), 60, 16), Qt.AlignLeft, "Today")

        # hover read-out
        if self.hover is not None and 0 <= self.hover < len(self.points):
            d, v = self.points[self.hover]
            x = (self._x(self.hover, r) + self._x(self.hover + 1, r)) / 2
            y = self._y(v, lo, hi, r)
            p.setPen(QPen(QColor(col["muted"]), 1))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            dot = QColor(col["negative"] if v < 0 else col["accent"])
            p.setPen(QPen(QColor(col["surface"]), 2))
            p.setBrush(dot)
            p.drawEllipse(QPointF(x, y), 5, 5)
            text1 = d.strftime("%a %b %d, %Y")
            text2 = money.fmt(v)
            bold = QFont(self.font())
            bold.setBold(True)
            w, h = 150, 46
            bx = x + 12 if x + 12 + w < r.right() else x - 12 - w
            by = min(max(r.top(), y - h - 8), r.bottom() - h)
            p.setPen(QPen(QColor(col["border"]), 1))
            p.setBrush(QColor(col["surface"]))
            p.drawRoundedRect(QRectF(bx, by, w, h), 8, 8)
            p.setPen(QColor(col["muted"]))
            p.setFont(small)
            p.drawText(QRectF(bx + 10, by + 6, w - 20, 16), Qt.AlignLeft, text1)
            p.setFont(bold)
            p.setPen(dot)
            p.drawText(QRectF(bx + 10, by + 22, w - 20, 18), Qt.AlignLeft, text2)

    def _index_at(self, x: float):
        r = self._plot_rect()
        if not self.points or x < r.left() or x > r.right():
            return None
        return min(len(self.points) - 1, int((x - r.left()) / r.width() * len(self.points)))

    def mouseMoveEvent(self, e):
        self.hover = self._index_at(e.position().x())
        self.update()

    def leaveEvent(self, _):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        i = self._index_at(e.position().x())
        if i is not None:
            self.dayClicked.emit(self.points[i][0])


class MonthlyBars(QWidget):
    """Bar chart of unplanned spending per month (negative = overspent)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bars: list = []  # [(label, cents)]
        self.setMinimumHeight(200)

    def set_data(self, bars):
        self.bars = bars
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = theme.colors()
        r = QRectF(8, 22, self.width() - 16, self.height() - 22 - 26)
        if not self.bars:
            p.setPen(QColor(col["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter, "Check in a few times to see trends here")
            return
        vals = [abs(v) for _, v in self.bars] or [1]
        top = max(vals) or 1
        n = len(self.bars)
        slot = r.width() / n
        bw = min(46, slot * 0.6)
        small = QFont(self.font())
        small.setPointSizeF(8.5)
        p.setFont(small)
        for i, (lab, v) in enumerate(self.bars):
            h = abs(v) / top * (r.height() - 16)
            x = r.left() + slot * i + (slot - bw) / 2
            color = QColor(col["negative"] if v < 0 else col["positive"])
            if v != 0:
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawRoundedRect(QRectF(x, r.bottom() - max(h, 3), bw, max(h, 3)), 5, 5)
            p.setPen(color if v else QColor(col["muted"]))
            p.drawText(QRectF(x - 30, r.bottom() - h - 20, bw + 60, 16), Qt.AlignCenter,
                       money.fmt_short(abs(v)) if v else "—")
            p.setPen(QColor(col["muted"]))
            p.drawText(QRectF(x - 30, r.bottom() + 6, bw + 60, 16), Qt.AlignCenter, lab)
        p.setPen(QPen(QColor(col["border"]), 1))
        p.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.right(), r.bottom()))
