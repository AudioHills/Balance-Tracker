"""Custom-painted charts: the balance forecast, monthly bars and the category breakdown."""
from __future__ import annotations

import math
from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from .. import money
from . import theme


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
        # never pad below zero when nothing is negative (debt totals, a healthy balance)
        ticks = _nice_ticks(lo - pad if lo < 0 else 0, hi + pad)
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


def _bar_path(rect: QRectF, end: str, radius: float = 4) -> QPainterPath:
    """A bar with a rounded data end ("top" or "right") and square corners at the baseline."""
    r = min(radius, rect.width() / 2, rect.height() / 2)
    path = QPainterPath()
    if end == "top":
        path.moveTo(rect.left(), rect.bottom())
        path.lineTo(rect.left(), rect.top() + r)
        path.quadTo(rect.left(), rect.top(), rect.left() + r, rect.top())
        path.lineTo(rect.right() - r, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
        path.lineTo(rect.right(), rect.bottom())
    else:
        path.moveTo(rect.left(), rect.top())
        path.lineTo(rect.right() - r, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
        path.lineTo(rect.right(), rect.bottom() - r)
        path.quadTo(rect.right(), rect.bottom(), rect.right() - r, rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
    path.closeSubpath()
    return path


class MonthlyBars(QWidget):
    """Columns of net unplanned spending per month: red = spent beyond the plan, green = came out ahead."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bars: list[tuple[str, int]] = []  # [(month label, cents)]
        self.setMinimumHeight(200)

    def set_data(self, bars: list[tuple[str, int]]):
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
        top = max(abs(v) for _, v in self.bars) or 1
        slot = r.width() / len(self.bars)
        bw = min(24, slot * 0.5)
        small = QFont(self.font())
        small.setPointSizeF(8.5)
        p.setFont(small)
        for i, (lab, v) in enumerate(self.bars):
            h = max(3.0, abs(v) / top * (r.height() - 16)) if v else 0
            x = r.left() + slot * i + (slot - bw) / 2
            if v:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(col["negative"] if v < 0 else col["positive"]))
                p.drawPath(_bar_path(QRectF(x, r.bottom() - h, bw, h), "top"))
            # signed value in text colour, so the colour isn't the only cue
            p.setPen(QColor(col["text"] if v else col["muted"]))
            p.drawText(QRectF(x - 40, r.bottom() - h - 20, bw + 80, 16), Qt.AlignCenter,
                       ("−" if v < 0 else "+") + money.fmt_short(abs(v)) if v else "—")
            p.setPen(QColor(col["muted"]))
            p.drawText(QRectF(x - 40, r.bottom() + 6, bw + 80, 16), Qt.AlignCenter, lab)
        p.setPen(QPen(QColor(col["border"]), 1))
        p.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.right(), r.bottom()))


class CategoryBars(QWidget):
    """Horizontal bars of monthly bills per category, one colour, values at the bar tips."""

    ROW = 30
    MAX_ROWS = 8  # anything beyond folds into "Other"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[tuple[str, int, float]] = []  # [(category, cents per month, share)]
        self.hover: int | None = None
        self.setMouseTracking(True)

    def set_data(self, rows: list[tuple[str, int, float]]):
        if len(rows) > self.MAX_ROWS:
            rest = rows[self.MAX_ROWS - 1:]
            rows = rows[:self.MAX_ROWS - 1] + [("Other", sum(r[1] for r in rest), sum(r[2] for r in rest))]
        self.rows = rows
        self.hover = None
        self.setFixedHeight(max(1, len(rows)) * self.ROW + 8)
        self.update()

    def _geometry(self):
        fm = self.fontMetrics()
        name_w = min(180, max((fm.horizontalAdvance(r[0]) for r in self.rows), default=60) + 16)
        value_w = fm.horizontalAdvance(f"{money.fmt(max((r[1] for r in self.rows), default=0))}/mo  100%") + 12
        return name_w, max(40.0, self.width() - name_w - value_w), value_w

    def paintEvent(self, _):
        if not self.rows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = theme.colors()
        name_w, track_w, _ = self._geometry()
        top = max(r[1] for r in self.rows) or 1
        bar_h = 14
        for i, (name, cents, share) in enumerate(self.rows):
            y = 4 + i * self.ROW
            mid = y + self.ROW / 2
            if i == self.hover:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(col["surface2"]))
                p.drawRoundedRect(QRectF(0, y, self.width(), self.ROW), 6, 6)
            p.setPen(QColor(col["text"]))
            p.drawText(QRectF(4, y, name_w - 12, self.ROW), Qt.AlignLeft | Qt.AlignVCenter,
                       self.fontMetrics().elidedText(name, Qt.ElideRight, int(name_w - 12)))
            w = max(3.0, cents / top * track_w)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col["accent"]))
            p.drawPath(_bar_path(QRectF(name_w, mid - bar_h / 2, w, bar_h), "right"))
            p.setPen(QColor(col["text"]))
            p.drawText(QRectF(name_w + w + 8, y, self.width(), self.ROW), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{money.fmt(cents)}/mo")
            p.setPen(QColor(col["muted"]))
            p.drawText(QRectF(0, y, self.width() - 4, self.ROW), Qt.AlignRight | Qt.AlignVCenter,
                       f"{round(share * 100)}%")

    def _row_at(self, y: float) -> int | None:
        i = int((y - 4) // self.ROW)
        return i if 0 <= i < len(self.rows) else None

    def mouseMoveEvent(self, e):
        i = self._row_at(e.position().y())
        if i != self.hover:
            self.hover = i
            self.update()
        if i is not None:
            name, cents, share = self.rows[i]
            QToolTip.showText(e.globalPosition().toPoint(),
                              f"{name}: {money.fmt(cents)} a month · {money.fmt(cents * 12)} a year · "
                              f"{share * 100:.1f}% of your bills", self)

    def leaveEvent(self, _):
        self.hover = None
        self.update()
