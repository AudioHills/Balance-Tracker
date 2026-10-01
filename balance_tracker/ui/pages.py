"""The five main pages of the app."""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QColor, QBrush
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLineEdit, QMenu, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import money, storage
from ..forecast import monthly_equivalent, next_occurrence, add_months
from ..models import BILL, FREQUENCIES, INCOME
from . import theme
from .dialogs import date_edit, from_qdate, to_qdate
from .widgets import Banner, BalanceChart, Card, MonthlyBars, MoneySpin, StatCard, hbox, label


def page_shell(title: str, subtitle: str):
    """A scrollable page with a title row. Returns (page, body_layout, header_layout)."""
    page = QScrollArea()
    page.setWidgetResizable(True)
    inner = QWidget()
    inner.setObjectName("Page")
    page.setWidget(inner)
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(32, 28, 32, 28)
    lay.setSpacing(18)
    head = QHBoxLayout()
    titles = QVBoxLayout()
    titles.setSpacing(2)
    titles.addWidget(label(title, "PageTitle"))
    sub = label(subtitle, "PageSubtitle", wrap=True)
    titles.addWidget(sub)
    head.addLayout(titles, 1)
    lay.addLayout(head)
    page.subtitle_label = sub
    return page, lay, head


def table(headers, stretch_col: int = 1) -> QTableWidget:
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


def nice_date(d: date, today: date) -> str:
    if d == today:
        return "Today"
    if d == today + timedelta(days=1):
        return "Tomorrow"
    if d == today - timedelta(days=1):
        return "Yesterday"
    fmt = "%a %b %d" if d.year == today.year else "%a %b %d, %Y"
    return d.strftime(fmt)


def bal_color(bal: int, threshold: int) -> str:
    if bal < 0:
        return "negative"
    if bal < threshold:
        return "warning"
    return "text"


# ==========================================================================
class DashboardPage:
    RANGES = [("1M", 1), ("3M", 3), ("6M", 6), ("1Y", 12)]

    def __init__(self, ctx):
        self.ctx = ctx
        self.widget, lay, head = page_shell("Dashboard", "")
        btn = QPushButton("Check in balance")
        btn.setObjectName("Primary")
        btn.clicked.connect(ctx.check_in)
        head.addWidget(btn, 0, Qt.AlignTop)

        self.banner = Banner()
        lay.addWidget(self.banner)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.c_today = StatCard("BALANCE TODAY")
        self.c_safe = StatCard("SAFE TO SPEND")
        self.c_low = StatCard("LOWEST POINT AHEAD")
        self.c_unplanned = StatCard("UNPLANNED THIS MONTH")
        for i, w in enumerate((self.c_today, self.c_safe, self.c_low, self.c_unplanned)):
            grid.addWidget(w, 0, i)
        lay.addLayout(grid)

        chart_card = Card()
        self.range_btns = []
        group = QButtonGroup(chart_card)
        chips = []
        for text, months in self.RANGES:
            b = QPushButton(text)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setProperty("months", months)
            b.clicked.connect(self.refresh)
            group.addButton(b)
            self.range_btns.append(b)
            chips.append(b)
        self.range_btns[1].setChecked(True)
        chart_card.lay.addLayout(hbox(label("Balance forecast", "SectionTitle"), None, *chips, spacing=6))
        chart_card.lay.addWidget(label("Hover to see any day · click to open it in Day by day", "Hint"))
        self.chart = BalanceChart()
        self.chart.dayClicked.connect(ctx.show_day)
        chart_card.lay.addWidget(self.chart, 1)
        chart_card.setMinimumHeight(340)
        lay.addWidget(chart_card, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        up_card = Card()
        up_card.lay.addLayout(hbox(label("Coming up · next 14 days", "SectionTitle"), None))
        self.upcoming = table(["When", "What", "Amount", "Balance after"])
        self.upcoming.setMinimumHeight(260)
        self.upcoming.setAlternatingRowColors(False)
        self.upcoming.setStyleSheet("QTableView { border: none; }")
        up_card.lay.addWidget(self.upcoming)
        bottom.addWidget(up_card, 3)

        snap = Card()
        snap.lay.addWidget(label("Monthly snapshot", "SectionTitle"))
        snap.lay.addWidget(label("Average per month, from your recurring entries", "Hint"))
        self.snap_form = QFormLayout()
        self.snap_form.setVerticalSpacing(10)
        self.s_income = label("", "SectionTitle")
        self.s_bills = label("", "SectionTitle")
        self.s_net = label("", "SectionTitle")
        self.s_unplanned = label("", "SectionTitle")
        self.snap_form.addRow(label("Income", "Muted"), self.s_income)
        self.snap_form.addRow(label("Bills", "Muted"), self.s_bills)
        self.snap_form.addRow(label("Left over", "Muted"), self.s_net)
        self.snap_form.addRow(label("Avg. unplanned", "Muted"), self.s_unplanned)
        snap.lay.addLayout(self.snap_form)
        self.snap_tip = label("", "Hint", wrap=True)
        snap.lay.addWidget(self.snap_tip)
        snap.lay.addStretch(1)
        bottom.addWidget(snap, 2)
        lay.addLayout(bottom)

    def refresh(self):
        ctx, f, today = self.ctx, self.ctx.forecast, self.ctx.today
        s = ctx.data.settings
        hour = datetime.now().hour
        greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
        self.widget.subtitle_label.setText(f"{greet} — here's {s.account_name} as of {today.strftime('%A, %B %d')}.")
        col = theme.colors()
        if f.empty:
            for cdx in (self.c_today, self.c_safe, self.c_low, self.c_unplanned):
                cdx.set("—")
            self.chart.set_data([], today, 0)
            self.banner.show_message("Start by entering your current balance — click “Check in balance”.", "warning")
            return

        bal = f.balance_on(today)
        last = ctx.data.latest_checkpoint
        days_ago = (today - last.date).days
        ago = "today" if days_ago == 0 else "yesterday" if days_ago == 1 else f"{days_ago} days ago"
        self.c_today.set(money.fmt(bal), f"Last checked in {ago}",
                         bal_color(bal, s.low_balance_threshold) if bal is not None else None)

        safe = f.safe_to_spend(today, 30, s.low_balance_threshold)
        if safe is None:
            self.c_safe.set("—")
        elif safe >= 0:
            self.c_safe.set(money.fmt(safe), f"Keeps {money.fmt(s.low_balance_threshold)} cushion for 30 days",
                            "positive")
        else:
            self.c_safe.set(money.fmt(0), f"You're {money.fmt(-safe)} short of your cushion in the next 30 days",
                            "negative")

        horizon = f.end
        low = f.lowest(today, horizon)
        if low:
            self.c_low.set(money.fmt(low[1]), f"on {nice_date(low[0], today)}",
                           bal_color(low[1], s.low_balance_threshold))

        by_month = f.unplanned_by_month()
        this = by_month.get((today.year, today.month), 0)
        self.c_unplanned.set(money.fmt(-this) if this < 0 else money.fmt(0) if this == 0 else money.fmt(this, True),
                             "spent beyond your plan" if this < 0 else
                             "more than planned" if this > 0 else "Nothing unplanned so far",
                             "negative" if this < 0 else "positive")

        # alerts
        neg = f.first_below(0, today)
        below = f.first_below(s.low_balance_threshold, today)
        if neg:
            self.banner.show_message(
                f"⚠  Heads up: you're projected to be in overdraft ({money.fmt(neg[1])}) "
                f"{_when(neg[0], today)}. Consider moving a bill or trimming spending.", "negative")
        elif below and s.low_balance_threshold > 0:
            self.banner.show_message(
                f"Your balance dips below your {money.fmt(s.low_balance_threshold)} cushion "
                f"{_when(below[0], today)} ({money.fmt(below[1])}).", "warning")
        elif days_ago >= 7:
            self.banner.show_message(
                f"It's been {days_ago} days since your last check-in — a quick update keeps the forecast honest.",
                "warning")
        else:
            self.banner.hide()

        # chart
        months = next(b.property("months") for b in self.range_btns if b.isChecked())
        end = min(add_months(today, months), f.end)
        begin = max(f.start, today - timedelta(days=max(14, months * 7)))
        pts = [(d, v) for d, v in f.daily.items() if begin <= d <= end]
        self.chart.set_data(pts, today, s.low_balance_threshold)

        # upcoming
        rows = [e for e in f.entries_between(today, today + timedelta(days=14)) if e.kind in (INCOME, BILL)]
        t = self.upcoming
        t.setRowCount(0)
        for e in rows:
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, cell(nice_date(e.date, today), color="muted"))
            t.setItem(r, 1, cell(e.description, bold=True))
            t.setItem(r, 2, cell(money.fmt(e.amount, True), Qt.AlignRight,
                                 "positive" if e.amount > 0 else "text"))
            t.setItem(r, 3, cell(money.fmt(e.balance), Qt.AlignRight,
                                 bal_color(e.balance, s.low_balance_threshold)))
        if not rows:
            t.insertRow(0)
            t.setItem(0, 1, cell("Nothing scheduled in the next two weeks", color="muted"))

        inc = sum(monthly_equivalent(i) for i in ctx.data.items if i.active and i.kind == INCOME)
        bills = -sum(monthly_equivalent(i) for i in ctx.data.items if i.active and i.kind == BILL)
        net = inc - bills
        self.s_income.setText(money.fmt(inc))
        self.s_income.setStyleSheet(f"color: {col['positive']};")
        self.s_bills.setText(money.fmt(bills))
        self.s_net.setText(money.fmt(net))
        self.s_net.setStyleSheet(f"color: {col['positive' if net >= 0 else 'negative']};")
        recent = [by_month.get(k, 0) for k in _last_full_months(today, 3)]
        avg = -sum(recent) // 3 if any(recent) else 0
        self.s_unplanned.setText(money.fmt(max(0, avg)) if any(recent) else "—")
        if any(recent) and avg > 0 and net > 0:
            pct = round(avg / net * 100) if net else 0
            self.snap_tip.setText(f"Unplanned spending is using about {pct}% of what's left over each month.")
        elif net < 0:
            self.snap_tip.setText("Your bills are higher than your income on average — the forecast will trend down.")
        else:
            self.snap_tip.setText("")


def _when(d: date, today: date) -> str:
    if d == today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    return "on " + d.strftime("%A, %B %d")


def _last_full_months(today: date, n: int):
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append((y, m))
    return out


# ==========================================================================
class LedgerPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.widget, lay, head = page_shell(
            "Day by day", "Every scheduled income and bill with the running balance. "
                          "Right-click a line to skip it or change the amount just this once.")
        today = ctx.today
        self.from_date = date_edit(today - timedelta(days=7))
        self.to_date = date_edit(add_months(today, 2))
        self.every_day = QCheckBox("Show every day")
        self.every_day.setChecked(True)
        today_btn = QPushButton("Jump to today")
        today_btn.clicked.connect(lambda: self.show_day(self.ctx.today))
        export_btn = QPushButton("Export CSV…")
        export_btn.clicked.connect(self.export_csv)
        lay.addLayout(hbox(label("From", "Muted"), self.from_date, label("to", "Muted"), self.to_date,
                           12, self.every_day, None, today_btn, export_btn))
        self.table = table(["Date", "Description", "Category", "Change", "Balance"])
        self.table.setMinimumHeight(520)
        self.table.customContextMenuRequested.connect(self.menu)
        self.table.cellDoubleClicked.connect(self.double_click)
        lay.addWidget(self.table, 1)
        self.summary = label("", "Hint")
        lay.addWidget(self.summary)
        for sig in (self.from_date.dateChanged, self.to_date.dateChanged):
            sig.connect(self.refresh)
        self.every_day.toggled.connect(self.refresh)

    def show_day(self, d: date):
        a, b = from_qdate(self.from_date.date()), from_qdate(self.to_date.date())
        if not (a <= d <= b):
            self.from_date.blockSignals(True)
            self.to_date.blockSignals(True)
            self.from_date.setDate(to_qdate(d - timedelta(days=7)))
            self.to_date.setDate(to_qdate(max(b, d + timedelta(days=30))))
            self.from_date.blockSignals(False)
            self.to_date.blockSignals(False)
            self.refresh()
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it and it.data(Qt.UserRole + 1) == d.isoformat():
                self.table.scrollToItem(it, QAbstractItemView.PositionAtTop)
                self.table.selectRow(r)
                break

    def refresh(self):
        ctx, f, today = self.ctx, self.ctx.forecast, self.ctx.today
        thr = ctx.data.settings.low_balance_threshold
        a, b = from_qdate(self.from_date.date()), from_qdate(self.to_date.date())
        if b > f.end and not f.empty:
            ctx.extend_forecast(b)
            f = ctx.forecast
        t = self.table
        t.setUpdatesEnabled(False)
        t.setRowCount(0)
        rows = []
        by_day = {}
        for e in f.entries_between(a, b):
            by_day.setdefault(e.date, []).append(e)
        if self.every_day.isChecked():
            d = a
            while d <= b:
                if d in by_day:
                    rows.extend(by_day[d])
                elif d in f.daily:
                    rows.append(("quiet", d))
                d += timedelta(days=1)
        else:
            rows = [e for d in sorted(by_day) for e in by_day[d]]
        today_bg = QBrush(QColor(theme.colors()["today"]))
        last_date = None
        income = bills = unplanned = 0
        for e in rows:
            r = t.rowCount()
            t.insertRow(r)
            if isinstance(e, tuple):  # a day with nothing scheduled
                d = e[1]
                bal = f.daily[d]
                items = [cell(d.strftime("%a %b %d, %Y"), color="muted"),
                         cell("", color="muted"), cell(""), cell(""),
                         cell(money.fmt(bal), Qt.AlignRight, bal_color(bal, thr))]
                e_date, payload = d, None
            else:
                d = e.date
                first = d != last_date
                kind_color = {"income": "positive", "checkin": "accent"}.get(e.kind)
                desc = e.description + ("  (changed)" if e.overridden else "")
                items = [cell(d.strftime("%a %b %d, %Y") if first else "", color=None if first else "muted",
                              bold=first),
                         cell(desc, bold=e.kind != "start", italic=e.kind in ("checkin", "start"),
                              color="accent" if e.kind in ("checkin", "start") else None),
                         cell(e.category, color="muted"),
                         cell("" if e.kind == "start" else money.fmt(e.amount, True), Qt.AlignRight,
                              "negative" if e.kind == "checkin" and e.amount < 0 else kind_color),
                         cell(money.fmt(e.balance), Qt.AlignRight, bal_color(e.balance, thr), bold=True)]
                e_date, payload = d, e
                if e.kind == "income":
                    income += e.amount
                elif e.kind == "bill":
                    bills += e.amount
                elif e.kind == "checkin":
                    unplanned += e.amount
            items[0].setData(Qt.UserRole + 1, e_date.isoformat())
            items[0].setData(Qt.UserRole, payload)
            for c_, it in enumerate(items):
                if e_date == today:
                    it.setBackground(today_bg)
                t.setItem(r, c_, it)
            last_date = e_date
        t.setUpdatesEnabled(True)
        self.summary.setText(
            f"In this range: income {money.fmt(income)} · bills {money.fmt(-bills)} · "
            f"unplanned {money.fmt(unplanned, True)} · net {money.fmt(income + bills + unplanned, True)}")

    def _entry_at(self, row):
        it = self.table.item(row, 0)
        return it.data(Qt.UserRole) if it else None

    def double_click(self, row, _col):
        e = self._entry_at(row)
        if e is not None and e.item_id:
            self.ctx.edit_item(e.item_id)

    def menu(self, pos):
        row = self.table.rowAt(pos.y())
        e = self._entry_at(row)
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
            m.addAction(f"Edit “{item.name}”…", lambda: self.ctx.edit_item(item.id))
        elif e.kind == "checkin":
            m.addAction("Delete this check-in", lambda: self.ctx.delete_checkpoint(e.checkpoint_id))
        else:
            return
        m.exec(self.table.viewport().mapToGlobal(pos))

    def change_once(self, item, key, e):
        val, ok = QInputDialog.getDouble(
            self.widget, "Change amount", f"{item.name} on {e.date.strftime('%b %d, %Y')}:",
            abs(e.amount) / 100, 0, 99_999_999, 2)
        if ok:
            self.ctx.set_override(item, key, money.to_cents(val))

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self.widget, "Export day-by-day ledger",
                                              f"balance-forecast-{self.ctx.today.isoformat()}.csv",
                                              "CSV files (*.csv)")
        if path:
            a, b = from_qdate(self.from_date.date()), from_qdate(self.to_date.date())
            storage.export_ledger_csv(self.ctx.forecast.entries_between(a, b), path)
            self.ctx.toast(f"Exported to {os.path.basename(path)}")


# ==========================================================================
class ItemsPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.widget, lay, head = page_shell(
            "Income & Bills", "Everything that regularly moves money in or out of your account.")
        add_inc = QPushButton("+  Add income")
        add_inc.clicked.connect(lambda: ctx.add_item(INCOME))
        add_bill = QPushButton("+  Add bill")
        add_bill.setObjectName("Primary")
        add_bill.clicked.connect(lambda: ctx.add_item(BILL))
        head.addLayout(hbox(add_inc, add_bill))

        grid = QGridLayout()
        grid.setSpacing(14)
        self.c_inc = StatCard("INCOME / MONTH")
        self.c_bill = StatCard("BILLS / MONTH")
        self.c_net = StatCard("LEFT OVER / MONTH")
        for i, w in enumerate((self.c_inc, self.c_bill, self.c_net)):
            grid.addWidget(w, 0, i)
        lay.addLayout(grid)

        self.filter_btns = []
        group = QButtonGroup(self.widget)
        for text, key in (("All", None), ("Income", INCOME), ("Bills", BILL)):
            b = QPushButton(text)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setProperty("kind", key)
            b.clicked.connect(self.refresh)
            group.addButton(b)
            self.filter_btns.append(b)
        self.filter_btns[0].setChecked(True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(self.refresh)
        lay.addLayout(hbox(*self.filter_btns, None, self.search, spacing=6))

        self.table = table(["Name", "Category", "Amount", "How often", "Next", "≈ per month", "Status"], 0)
        self.table.setMinimumHeight(420)
        self.table.cellDoubleClicked.connect(lambda r, _: self._edit_row(r))
        self.table.customContextMenuRequested.connect(self.menu)
        lay.addWidget(self.table, 1)
        lay.addWidget(label("Double-click to edit · right-click for more options", "Hint"))

    def _edit_row(self, r):
        it = self.table.item(r, 0)
        if it and it.data(Qt.UserRole):
            self.ctx.edit_item(it.data(Qt.UserRole))

    def refresh(self):
        ctx, today = self.ctx, self.ctx.today
        col = theme.colors()
        items = ctx.data.items
        inc = sum(monthly_equivalent(i) for i in items if i.active and i.kind == INCOME)
        bills = -sum(monthly_equivalent(i) for i in items if i.active and i.kind == BILL)
        self.c_inc.set(money.fmt(inc), f"{sum(1 for i in items if i.kind == INCOME)} income entries", "positive")
        self.c_bill.set(money.fmt(bills), f"{sum(1 for i in items if i.kind == BILL)} bills")
        self.c_net.set(money.fmt(inc - bills, True), "before unplanned spending",
                       "positive" if inc >= bills else "negative")

        kind = next(b.property("kind") for b in self.filter_btns if b.isChecked())
        q = self.search.text().strip().lower()
        shown = [i for i in items if (kind is None or i.kind == kind)
                 and (not q or q in i.name.lower() or q in i.category.lower())]
        nexts = {i.id: next_occurrence(i, today) for i in shown}
        shown.sort(key=lambda i: (not i.active, i.kind != INCOME,
                                  nexts[i.id].date if nexts[i.id] else date.max, i.name.lower()))
        t = self.table
        t.setRowCount(0)
        for i in shown:
            r = t.rowCount()
            t.insertRow(r)
            nxt = nexts[i.id]
            status = "Paused" if not i.active else ("Finished" if nxt is None else "Active")
            dim = None if i.active and nxt else "muted"
            t.setItem(r, 0, cell(("▲  " if i.kind == INCOME else "▼  ") + i.name, bold=True,
                                 color=dim or ("positive" if i.kind == INCOME else None), data=i.id))
            t.setItem(r, 1, cell(i.category, color="muted"))
            t.setItem(r, 2, cell(money.fmt(i.signed_amount, True), Qt.AlignRight,
                                 dim or ("positive" if i.kind == INCOME else None)))
            freq = FREQUENCIES[i.frequency]
            if i.frequency == "semimonthly":
                d2 = "last day" if i.second_day >= 31 else _ordinal(i.second_day)
                freq += f" ({_ordinal(i.start_date.day)} & {d2})"
            t.setItem(r, 3, cell(freq, color=dim))
            t.setItem(r, 4, cell(nice_date(nxt.date, today) if nxt else "—", color=dim))
            t.setItem(r, 5, cell(money.fmt(monthly_equivalent(i), True) if i.frequency != "once" else "one-time",
                                 Qt.AlignRight, "muted"))
            t.setItem(r, 6, cell(status, color="muted" if status != "Active" else "positive"))
        if not shown:
            t.insertRow(0)
            t.setItem(0, 0, cell("Nothing here yet — add your paycheque and bills above.", color="muted"))

    def menu(self, pos):
        row = self.table.rowAt(pos.y())
        it = self.table.item(row, 0) if row >= 0 else None
        if not it or not it.data(Qt.UserRole):
            return
        item = self.ctx.data.item(it.data(Qt.UserRole))
        m = QMenu(self.table)
        m.addAction("Edit…", lambda: self.ctx.edit_item(item.id))
        m.addAction("Duplicate", lambda: self.ctx.duplicate_item(item.id))
        m.addAction("Resume" if not item.active else "Pause (exclude from forecast)",
                    lambda: self.ctx.toggle_item(item.id))
        m.addSeparator()
        m.addAction("Delete", lambda: self.ctx.delete_item(item.id))
        m.exec(self.table.viewport().mapToGlobal(pos))


def _ordinal(n: int) -> str:
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


# ==========================================================================
class CheckinsPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.widget, lay, head = page_shell(
            "Check-ins", "Each time you enter your real balance, the difference from the plan is "
                         "recorded here — so you can see how much is going to everyday spending.")
        btn = QPushButton("Check in now")
        btn.setObjectName("Primary")
        btn.clicked.connect(ctx.check_in)
        head.addWidget(btn, 0, Qt.AlignTop)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.c_month = StatCard("UNPLANNED THIS MONTH")
        self.c_avg = StatCard("MONTHLY AVERAGE")
        self.c_total = StatCard("SINCE YOU STARTED")
        for i, w in enumerate((self.c_month, self.c_avg, self.c_total)):
            grid.addWidget(w, 0, i)
        lay.addLayout(grid)

        chart = Card()
        chart.lay.addWidget(label("Unplanned spending by month", "SectionTitle"))
        chart.lay.addWidget(label("Red = spent more than planned · green = came out ahead", "Hint"))
        self.bars = MonthlyBars()
        chart.lay.addWidget(self.bars)
        lay.addWidget(chart)

        self.table = table(["Date", "Plan expected", "Actual balance", "Difference", "Note"], 4)
        self.table.setMinimumHeight(280)
        self.table.customContextMenuRequested.connect(self.menu)
        lay.addWidget(self.table, 1)

    def refresh(self):
        f, today = self.ctx.forecast, self.ctx.today
        by_month = f.unplanned_by_month()
        this = by_month.get((today.year, today.month), 0)
        self.c_month.set(money.fmt(-this) if this <= 0 else money.fmt(this, True),
                         "spent beyond your plan" if this < 0 else "Nothing unplanned so far",
                         "negative" if this < 0 else "positive")
        months = _last_full_months(today, 6)
        tracked = [by_month[k] for k in months if k in by_month]
        if tracked:
            avg = sum(tracked) // len(tracked)
            self.c_avg.set(money.fmt(-avg) if avg <= 0 else money.fmt(avg, True),
                           f"over the last {len(tracked)} month(s) with check-ins",
                           "negative" if avg < 0 else "positive")
        else:
            self.c_avg.set("—", "Needs a full month of check-ins")
        total = sum(by_month.values())
        self.c_total.set(money.fmt(-total) if total <= 0 else money.fmt(total, True),
                         f"across {len(f.checkins())} check-ins", "negative" if total < 0 else "positive")

        series = list(reversed(months[:5])) + [(today.year, today.month)]
        self.bars.set_data([(date(y, m, 1).strftime("%b"), by_month.get((y, m), 0)) for y, m in series]
                           if by_month else [])

        t = self.table
        t.setRowCount(0)
        for e in reversed(f.checkins()):
            r = t.rowCount()
            t.insertRow(r)
            cp = next((c for c in self.ctx.data.checkpoints if c.id == e.checkpoint_id), None)
            t.setItem(r, 0, cell(e.date.strftime("%a %b %d, %Y"), bold=True, data=e.checkpoint_id))
            t.setItem(r, 1, cell(money.fmt(e.projected), Qt.AlignRight, "muted"))
            t.setItem(r, 2, cell(money.fmt(e.balance), Qt.AlignRight))
            t.setItem(r, 3, cell(money.fmt(e.amount, True), Qt.AlignRight,
                                 "negative" if e.amount < 0 else "positive", bold=True))
            t.setItem(r, 4, cell(cp.note if cp else "", color="muted"))
        start = self.ctx.data.start
        if start:
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, cell(start.date.strftime("%a %b %d, %Y"), bold=True))
            t.setItem(r, 1, cell("—", Qt.AlignRight, "muted"))
            t.setItem(r, 2, cell(money.fmt(start.balance), Qt.AlignRight))
            t.setItem(r, 3, cell("", Qt.AlignRight))
            t.setItem(r, 4, cell("Starting balance (edit in Settings)", color="muted", italic=True))

    def menu(self, pos):
        row = self.table.rowAt(pos.y())
        it = self.table.item(row, 0) if row >= 0 else None
        if not it or not it.data(Qt.UserRole):
            return
        m = QMenu(self.table)
        m.addAction("Delete this check-in", lambda: self.ctx.delete_checkpoint(it.data(Qt.UserRole)))
        m.exec(self.table.viewport().mapToGlobal(pos))


# ==========================================================================
class SettingsPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.widget, lay, _ = page_shell("Settings", "Preferences, starting balance, and your data.")
        s = ctx.data.settings
        self._loading = True

        # --- preferences
        pref = Card()
        pref.lay.addWidget(label("Preferences", "SectionTitle"))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setVerticalSpacing(10)
        self.account = QLineEdit(s.account_name)
        self.theme = QComboBox()
        for k, v in (("system", "Match Windows"), ("light", "Light"), ("dark", "Dark")):
            self.theme.addItem(v, k)
        self.currency = QLineEdit(s.currency_symbol)
        self.currency.setMaxLength(4)
        self.currency.setMaximumWidth(80)
        self.cushion = MoneySpin()
        self.horizon = QSpinBox()
        self.horizon.setRange(1, 36)
        self.horizon.setSuffix(" months")
        self.prompt = QCheckBox("Ask for my current balance when the app opens")
        form.addRow("Account name", self.account)
        form.addRow("Theme", self.theme)
        form.addRow("Currency symbol", self.currency)
        form.addRow("Low-balance cushion", hbox(self.cushion, label(
            "You'll be warned when the forecast dips below this.", "Hint"), None))
        form.addRow("Forecast ahead", hbox(self.horizon, None))
        form.addRow("", self.prompt)
        pref.lay.addLayout(form)
        lay.addWidget(pref)

        # --- starting balance
        start = Card()
        start.lay.addWidget(label("Starting balance", "SectionTitle"))
        start.lay.addWidget(label("Where the day-by-day history begins. Later check-ins build on this.",
                                  "Hint", wrap=True))
        self.start_bal = MoneySpin(allow_negative=True)
        self.start_date = date_edit(ctx.today)
        save_start = QPushButton("Update starting balance")
        save_start.clicked.connect(self.save_start)
        start.lay.addLayout(hbox(self.start_bal, label("as of", "Muted"), self.start_date, save_start, None))
        lay.addWidget(start)

        # --- data
        data = Card()
        data.lay.addWidget(label("Backup & restore", "SectionTitle"))
        self.data_path = label("", "Hint", wrap=True)
        self.data_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        data.lay.addWidget(self.data_path)
        exp = QPushButton("Export backup…")
        exp.clicked.connect(ctx.export_backup)
        imp = QPushButton("Import backup…")
        imp.clicked.connect(ctx.import_backup)
        opn = QPushButton("Open data folder")
        opn.clicked.connect(self.open_folder)
        data.lay.addLayout(hbox(exp, imp, opn, None))
        data.lay.addWidget(label("Automatic backups are saved every day you make changes (last 30 days kept).",
                                 "Hint", wrap=True))
        self.auto = QComboBox()
        self.auto.setMinimumWidth(280)
        restore = QPushButton("Restore")
        restore.clicked.connect(self.restore_auto)
        data.lay.addLayout(hbox(self.auto, restore, None))
        reset = QPushButton("Erase all data…")
        reset.setObjectName("Danger")
        reset.clicked.connect(ctx.reset_all)
        data.lay.addLayout(hbox(None, reset))
        lay.addWidget(data)

        from .. import __version__
        lay.addWidget(label(f"Balance Tracker {__version__}", "Hint"))
        lay.addStretch(1)

        self.account.editingFinished.connect(self.save)
        self.currency.editingFinished.connect(self.save)
        self.cushion.editingFinished.connect(self.save)
        self.horizon.valueChanged.connect(self.save)
        self.theme.currentIndexChanged.connect(self.save)
        self.prompt.toggled.connect(self.save)
        self._loading = False

    def refresh(self):
        self._loading = True
        s, d = self.ctx.data.settings, self.ctx.data
        self.account.setText(s.account_name)
        self.theme.setCurrentIndex(["system", "light", "dark"].index(s.theme))
        self.currency.setText(s.currency_symbol)
        self.cushion.setPrefix(money._symbol)
        self.cushion.set_cents(s.low_balance_threshold)
        self.horizon.setValue(s.forecast_months)
        self.prompt.setChecked(s.prompt_on_open)
        if d.start:
            self.start_bal.set_cents(d.start.balance)
            self.start_date.setDate(to_qdate(d.start.date))
        self.start_bal.setPrefix(money._symbol)
        self.data_path.setText(f"Your data is stored at: {self.ctx.store.path}")
        self.auto.clear()
        for p in self.ctx.store.auto_backups():
            self.auto.addItem(p.stem.replace("auto-", "Auto backup · ").replace("before-restore-", "Before restore · "),
                              str(p))
        if self.auto.count() == 0:
            self.auto.addItem("No automatic backups yet", None)
        self._loading = False

    def save(self):
        if self._loading:
            return
        s = self.ctx.data.settings
        theme_changed = s.theme != self.theme.currentData()
        s.account_name = self.account.text().strip() or "Chequing"
        s.theme = self.theme.currentData()
        s.currency_symbol = self.currency.text().strip() or "$"
        s.low_balance_threshold = self.cushion.cents()
        s.forecast_months = self.horizon.value()
        s.prompt_on_open = self.prompt.isChecked()
        self.ctx.commit(theme_changed=theme_changed)

    def save_start(self):
        d = from_qdate(self.start_date.date())
        later = [c for c in self.ctx.data.checkpoints if c.date <= d and c is not self.ctx.data.start]
        if later:
            QMessageBox.warning(self.widget, "Check-ins in the way",
                                "There are check-ins on or before that date. Delete them first, or pick an "
                                "earlier date.")
            return
        self.ctx.set_start(d, self.start_bal.cents())

    def open_folder(self):
        folder = str(self.ctx.store.folder)
        self.ctx.store.folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def restore_auto(self):
        path = self.auto.currentData()
        if path:
            self.ctx.restore_from(path)
