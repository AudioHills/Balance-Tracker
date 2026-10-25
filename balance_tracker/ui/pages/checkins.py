"""Check-ins: every real balance entered, and the unplanned spending it revealed."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QMenu, QPushButton

from ... import money
from ...formatting import full_date
from ...insights import previous_months, unplanned_summary
from ..charts import MonthlyBars
from ..widgets import Card, StatCard, label
from .common import Page, add_row, cell, row_data, signed_tone, table


def _unplanned_text(cents: int) -> str:
    """Overspending reads as a plain amount; coming out ahead gets a + sign."""
    return money.fmt(-cents) if cents < 0 else money.fmt(cents, signed=True)


class CheckinsPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Check-ins",
                         "Each time you enter your real balance, the difference from the plan is recorded here — "
                         "so you can see how much is going to everyday spending.")
        btn = QPushButton("Check in now")
        btn.setObjectName("Primary")
        btn.setToolTip("Ctrl+K")
        btn.clicked.connect(ctx.check_in)
        self.header.addWidget(btn, 0, Qt.AlignTop)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.c_month = StatCard("UNPLANNED THIS MONTH")
        self.c_avg = StatCard("MONTHLY AVERAGE")
        self.c_total = StatCard("SINCE YOU STARTED")
        for i, w in enumerate((self.c_month, self.c_avg, self.c_total)):
            grid.addWidget(w, 0, i)
        self.body.addLayout(grid)

        chart = Card()
        chart.lay.addWidget(label("Unplanned spending by month", "SectionTitle"))
        chart.lay.addWidget(label("Red (−) = spent more than planned · green (+) = came out ahead", "Hint"))
        self.bars = MonthlyBars()
        chart.lay.addWidget(self.bars)
        self.body.addWidget(chart)

        self.table = table(["Date", "Plan expected", "Actual balance", "Difference", "Note"], 4)
        self.table.setMinimumHeight(280)
        self.table.customContextMenuRequested.connect(self.menu)
        self.body.addWidget(self.table, 1)
        self.body.addWidget(label("Right-click a check-in to delete it", "Hint"))

    def refresh(self):
        f, today, data = self.ctx.forecast, self.ctx.today, self.ctx.data
        u = unplanned_summary(f, today)
        if u.this_month < 0:
            self.c_month.set(_unplanned_text(u.this_month), "spent beyond your plan", "negative")
        elif u.this_month > 0:
            self.c_month.set(_unplanned_text(u.this_month), "came out ahead of the plan", "positive")
        else:
            self.c_month.set(money.fmt(0), "Nothing unplanned so far", "positive")
        if u.average is None:
            self.c_avg.set("—", "Needs a full month of check-ins")
        else:
            self.c_avg.set(_unplanned_text(u.average), f"over the last {u.months_tracked} month(s) with check-ins",
                           signed_tone(u.average))
        self.c_total.set(_unplanned_text(u.total), f"across {u.checkins} check-ins", signed_tone(u.total))

        by_month = f.unplanned_by_month()
        series = list(reversed(previous_months(today, 5))) + [(today.year, today.month)]
        self.bars.set_data([(f"{date(y, m, 1):%b}", by_month.get((y, m), 0)) for y, m in series]
                           if by_month else [])

        t = self.table
        t.setRowCount(0)
        for e in reversed(f.checkins()):
            cp = data.checkpoint(e.checkpoint_id)
            add_row(t, cell(full_date(e.date), bold=True, data=e.checkpoint_id),
                    cell(money.fmt(e.projected), Qt.AlignRight, "muted"),
                    cell(money.fmt(e.balance), Qt.AlignRight),
                    cell(money.fmt(e.amount, True), Qt.AlignRight, signed_tone(e.amount), bold=True),
                    cell(cp.note if cp else "", color="muted"))
        start = data.start
        if start:
            add_row(t, cell(full_date(start.date), bold=True), cell("—", Qt.AlignRight, "muted"),
                    cell(money.fmt(start.balance), Qt.AlignRight), cell("", Qt.AlignRight),
                    cell("Starting balance (edit in Settings)", color="muted", italic=True))

    def menu(self, pos):
        cp_id = row_data(self.table, self.table.rowAt(pos.y()))
        if not cp_id:
            return
        m = QMenu(self.table)
        m.addAction("Delete this check-in", lambda: self.ctx.delete_checkpoint(cp_id))
        m.exec(self.table.viewport().mapToGlobal(pos))
