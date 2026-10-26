"""Day by day: every scheduled income and bill with the running balance."""
from __future__ import annotations

import os
from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
)

from ... import money, storage
from ...forecast import CHECKIN, START, Entry, add_months
from ...formatting import full_date
from ...models import BILL, INCOME
from .. import theme
from ..widgets import date_edit, hbox, label
from .common import Page, add_row, bal_color, cell, table

DAY_ROLE = Qt.UserRole + 1  # ISO date of the row, for jumping to a day


class LedgerPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Day by day",
                         "Every scheduled income and bill with the running balance. Right-click a line to skip it, "
                         "change the amount just this once, or change it from that date on.")
        today = ctx.today
        self.from_date = date_edit(today - timedelta(days=7))
        self.to_date = date_edit(add_months(today, 2))
        self.every_day = QCheckBox("Show every day")
        self.every_day.setChecked(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter…  (Ctrl+F)")
        self.search.setToolTip("Show only lines whose name or category contains this")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(220)
        today_btn = QPushButton("Jump to today")
        today_btn.clicked.connect(lambda: self.show_day(self.ctx.today))
        export_btn = QPushButton("Export CSV…")
        export_btn.clicked.connect(self.export_csv)
        self.body.addLayout(hbox(label("From", "Muted"), self.from_date, label("to", "Muted"), self.to_date,
                                 12, self.every_day, None, self.search, today_btn, export_btn))
        self.table = table(["Date", "Description", "Category", "Change", "Balance"])
        self.table.setMinimumHeight(520)
        self.table.customContextMenuRequested.connect(self.menu)
        self.table.cellDoubleClicked.connect(self.double_click)
        self.body.addWidget(self.table, 1)
        self.summary = label("", "Hint")
        self.body.addWidget(self.summary)
        for sig in (self.from_date.dateChanged, self.to_date.dateChanged):
            sig.connect(self.refresh)
        self.every_day.toggled.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)

    def focus_search(self) -> bool:
        self.search.setFocus()
        self.search.selectAll()
        return True

    def show_day(self, d: date):
        a, b = self.from_date.value(), self.to_date.value()
        if not (a <= d <= b) or self.search.text():
            for w in (self.from_date, self.to_date, self.search):
                w.blockSignals(True)
            self.from_date.setDate(d - timedelta(days=7))
            self.to_date.setDate(max(b, d + timedelta(days=30)))
            self.search.clear()
            for w in (self.from_date, self.to_date, self.search):
                w.blockSignals(False)
            self.refresh()
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.data(DAY_ROLE) == d.isoformat():
                self.table.scrollToItem(it, QAbstractItemView.PositionAtTop)
                self.table.selectRow(r)
                break

    def _rows(self, f, a: date, b: date, query: str) -> list[Entry | date]:
        """Entries to show; a bare date stands for a day with nothing scheduled."""
        by_day: dict[date, list[Entry]] = {}
        for e in f.entries_between(a, b):
            if not query or query in e.description.lower() or query in e.category.lower():
                by_day.setdefault(e.date, []).append(e)
        if query or not self.every_day.isChecked():
            return [e for d in sorted(by_day) for e in by_day[d]]
        rows: list[Entry | date] = []
        d = a
        while d <= b:
            if d in by_day:
                rows.extend(by_day[d])
            elif d in f.daily:
                rows.append(d)
            d += timedelta(days=1)
        return rows

    def refresh(self):
        ctx, today = self.ctx, self.ctx.today
        thr = ctx.data.settings.low_balance_threshold
        a, b = self.from_date.value(), self.to_date.value()
        if b > ctx.forecast.end and not ctx.forecast.empty:
            ctx.extend_forecast(b)
        f = ctx.forecast
        query = self.search.text().strip().lower()
        t = self.table
        t.setUpdatesEnabled(False)
        t.setRowCount(0)
        today_bg = QBrush(QColor(theme.colors()["today"]))
        last_date = None
        totals = {INCOME: 0, BILL: 0, CHECKIN: 0}
        for e in self._rows(f, a, b, query):
            if isinstance(e, date):  # a day with nothing scheduled
                d, payload = e, None
                bal = f.daily[d]
                items = [cell(full_date(d), color="muted"), cell(""), cell(""), cell(""),
                         cell(money.fmt(bal), Qt.AlignRight, bal_color(bal, thr))]
            else:
                d, payload = e.date, e
                first = d != last_date
                special = e.kind in (CHECKIN, START)
                change_color = "positive" if e.kind == INCOME else (
                    "negative" if e.kind == CHECKIN and e.amount < 0 else "accent" if e.kind == CHECKIN else None)
                items = [cell(full_date(d) if first else "", color=None if first else "muted", bold=first),
                         cell(e.description + ("  (changed)" if e.overridden else ""), bold=e.kind != START,
                              italic=special, color="accent" if special else None),
                         cell(e.category, color="muted"),
                         cell("" if e.kind == START else money.fmt(e.amount, True), Qt.AlignRight, change_color),
                         cell(money.fmt(e.balance), Qt.AlignRight, bal_color(e.balance, thr), bold=True)]
                if e.kind in totals:
                    totals[e.kind] += e.amount
            items[0].setData(DAY_ROLE, d.isoformat())
            items[0].setData(Qt.UserRole, payload)
            if d == today:
                for it in items:
                    it.setBackground(today_bg)
            add_row(t, *items)
            last_date = d
        t.setUpdatesEnabled(True)
        net = sum(totals.values())
        prefix = f"Matching “{self.search.text().strip()}”" if query else "In this range"
        self.summary.setText(
            f"{prefix}: income {money.fmt(totals[INCOME])} · bills {money.fmt(-totals[BILL])} · "
            f"unplanned {money.fmt(totals[CHECKIN], True)} · net {money.fmt(net, True)}")

    def _entry_at(self, row: int) -> Entry | None:
        it = self.table.item(row, 0)
        return it.data(Qt.UserRole) if it else None

    def double_click(self, row, _col):
        e = self._entry_at(row)
        if e is not None and e.item_id:
            self.ctx.edit_item(e.item_id)

    def menu(self, pos):
        e = self._entry_at(self.table.rowAt(pos.y()))
        if e is None:
            return
        m = QMenu(self.table)
        if e.item_id:
            item = self.ctx.data.item(e.item_id)
            key = e.scheduled.isoformat()
            m.addAction("Change amount this time…", lambda: self.change_once(item, key, e))
            m.addAction("Skip this time", lambda: self.ctx.set_override(item, key, None))
            if key in item.overrides:
                m.addAction("Restore normal amount", lambda: self.ctx.clear_override(item, key))
            m.addSeparator()
            m.addAction("Change amount from this date on…", lambda: self.ctx.change_amount_from(item.id, e.scheduled))
            m.addAction(f"Edit “{item.name}”…", lambda: self.ctx.edit_item(item.id))
        elif e.kind == CHECKIN:
            m.addAction("Delete this check-in", lambda: self.ctx.delete_checkpoint(e.checkpoint_id))
        else:
            return
        m.exec(self.table.viewport().mapToGlobal(pos))

    def change_once(self, item, key: str, e: Entry):
        dlg = QInputDialog(self.widget)
        dlg.setWindowTitle("Change amount")
        dlg.setInputMode(QInputDialog.DoubleInput)
        dlg.setDoubleRange(0, 99_999_999)
        dlg.setDoubleDecimals(2)
        dlg.setDoubleValue(abs(e.amount) / 100)
        dlg.setLabelText(f"{item.name} on {full_date(e.date)}:")
        for lb in dlg.findChildren(QLabel):  # the name is data: never render it as markup
            lb.setTextFormat(Qt.PlainText)
        if dlg.exec():
            self.ctx.set_override(item, key, money.to_cents(dlg.doubleValue()))

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self.widget, "Export day-by-day ledger",
                                              f"balance-forecast-{self.ctx.today.isoformat()}.csv",
                                              "CSV files (*.csv)")
        if path:
            query = self.search.text().strip().lower()
            rows = self._rows(self.ctx.forecast, self.from_date.value(), self.to_date.value(), query)
            storage.export_ledger_csv([e for e in rows if isinstance(e, Entry)], path)
            self.ctx.toast(f"Exported to {os.path.basename(path)}")
