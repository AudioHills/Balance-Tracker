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
from ..forecast import monthly_equivalent, next_occurrence, add_months, horizon_end
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
        phone = QPushButton("📱 Reminders")
        phone.setToolTip("Send payment reminders to your phone's calendar")
        phone.clicked.connect(ctx.reminders)
        head.addWidget(phone, 0, Qt.AlignTop)
        afford = QPushButton("Can I afford it?")
        afford.setToolTip("Ctrl+A")
        afford.clicked.connect(ctx.afford)
        head.addWidget(afford, 0, Qt.AlignTop)
        btn = QPushButton("Check in balance")
        btn.setObjectName("Primary")
        btn.clicked.connect(ctx.check_in)
        head.addWidget(btn, 0, Qt.AlignTop)

        self.banner = Banner()
        lay.addWidget(self.banner)

        # "Pay your card" to-do list for bills charged to a credit card
        self.card_box = Card(spacing=6)
        self.card_box.lay.addLayout(hbox(label("💳  Pay your card", "SectionTitle"), None,
                                         label("Bills that landed on a credit card — pay them off and tick them",
                                               "Hint")))
        self.card_rows = QVBoxLayout()
        self.card_rows.setSpacing(4)
        self.card_box.lay.addLayout(self.card_rows)
        self.card_box.hide()
        lay.addWidget(self.card_box)

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
        self.s_debt = label("", "SectionTitle")
        self.snap_form.addRow(label("Income", "Muted"), self.s_income)
        self.snap_form.addRow(label("Bills", "Muted"), self.s_bills)
        self.snap_form.addRow(label("Left over", "Muted"), self.s_net)
        self.snap_form.addRow(label("Avg. unplanned", "Muted"), self.s_unplanned)
        self.s_debt_label = label("Debt-free by", "Muted")
        self.snap_form.addRow(self.s_debt_label, self.s_debt)
        snap.lay.addLayout(self.snap_form)
        self.snap_tip = label("", "Hint", wrap=True)
        snap.lay.addWidget(self.snap_tip)
        snap.lay.addStretch(1)
        bottom.addWidget(snap, 2)
        lay.addLayout(bottom)

    def _refresh_cards(self, today: date):
        from ..forecast import occurrences
        data = self.ctx.data
        due = []
        for item in data.items:
            card = data.debt(item.paid_with) if item.paid_with else None
            if card is None:
                continue
            for o in occurrences(item, today - timedelta(days=14), today):
                key = f"{item.id}|{o.date.isoformat()}"
                if key not in data.card_paid:
                    due.append((o, card, key))
        due.sort(key=lambda t: t[0].date)
        _clear_layout(self.card_rows)
        self.card_box.setVisible(bool(due))
        col = theme.colors()
        for o, card, key in due:
            when = nice_date(o.date, today)
            late = o.date < today
            txt = label(f"<b>{money.fmt(abs(o.amount))}</b> to {card.name} — {o.item.name} "
                        f"<span style='color:{col['negative' if late else 'muted']}'>({when})</span>")
            btn = QPushButton("✓ Paid")
            btn.setObjectName("Chip")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.ctx.mark_card_paid(k))
            self.card_rows.addLayout(hbox(txt, None, btn))

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

        horizon = horizon_end(ctx.data, today)
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

        self._refresh_cards(today)

        # alerts
        neg = f.first_below(0, today, horizon)
        below = f.first_below(s.low_balance_threshold, today, horizon)
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
        plan = ctx.plan
        has_debt = bool(plan and ctx.data.debts)
        self.s_debt.setVisible(has_debt)
        self.s_debt_label.setVisible(has_debt)
        if has_debt:
            free = plan.debt_free
            self.s_debt.setText(free.strftime("%B %Y") if free else "10+ years")
            self.s_debt.setStyleSheet(f"color: {col['positive' if free else 'negative']};")
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


def _clear_layout(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _clear_layout(it.layout())


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
            card = ctx.data.debt(i.paid_with) if i.paid_with else None
            t.setItem(r, 1, cell(" · ".join(x for x in (i.category, f"💳 on {card.name}" if card else "") if x),
                                 color="muted"))
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
        form.addRow("Watch ahead", hbox(self.horizon, label(
            "How far ahead alerts and “lowest point” look.", "Hint"), None))
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
        rem = QPushButton("✉  Email & phone reminders…")
        rem.clicked.connect(ctx.notify_settings)
        cal = QPushButton("📅  Export to calendar…")
        cal.clicked.connect(ctx.calendar_export)
        data.lay.addLayout(hbox(rem, cal, label("Get reminded to pay your card and bills.", "Hint"), None))
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


# ==========================================================================
class DebtsPage:
    def __init__(self, ctx):
        from .widgets import BalanceChart
        self.ctx = ctx
        self.widget, lay, head = page_shell(
            "Debts", "Credit cards, lines of credit and loans — with a payoff plan that only uses money "
                     "your forecast says you can spare.")
        add = QPushButton("+  Add debt")
        add.setObjectName("Primary")
        add.clicked.connect(ctx.add_debt)
        head.addWidget(add, 0, Qt.AlignTop)

        self.banner = Banner()
        lay.addWidget(self.banner)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.c_total = StatCard("TOTAL OWED")
        self.c_interest = StatCard("INTEREST THIS MONTH")
        self.c_free = StatCard("DEBT-FREE BY")
        self.c_saved = StatCard("INTEREST SAVED")
        for i, w in enumerate((self.c_total, self.c_interest, self.c_free, self.c_saved)):
            grid.addWidget(w, 0, i)
        lay.addLayout(grid)

        # --- plan controls
        plan = Card()
        plan.lay.addWidget(label("Your payoff plan", "SectionTitle"))
        self.strat_btns = []
        group = QButtonGroup(plan)
        from ..models import DEBT_STRATEGIES
        for key, text in DEBT_STRATEGIES.items():
            b = QPushButton(text)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setProperty("key", key)
            b.clicked.connect(self.save_plan)
            group.addButton(b)
            self.strat_btns.append(b)
        self.mode = QComboBox()
        self.mode.addItem("As much as my cushion allows", "auto")
        self.mode.addItem("A fixed extra amount each month", "fixed")
        self.fixed = MoneySpin()
        self.fixed.setMaximumWidth(140)
        self.in_forecast = QCheckBox("Show these payments in my day-by-day forecast")
        plan.lay.addLayout(hbox(label("Pay off", "Muted"), *self.strat_btns, 16, label("Extra money:", "Muted"),
                                self.mode, self.fixed, None, spacing=8))
        plan.lay.addWidget(self.in_forecast)
        self.next_action = label("", "SectionTitle", wrap=True)
        plan.lay.addWidget(self.next_action)
        self.plan_hint = label("", "Hint", wrap=True)
        plan.lay.addWidget(self.plan_hint)
        self.compare = table(["Approach", "Debt-free by", "Total interest", "Interest saved"], 0)
        self.compare.setFixedHeight(3 * 38 + 44)
        self.compare.setStyleSheet("QTableView { border: none; }")
        plan.lay.addWidget(self.compare)
        lay.addWidget(plan)
        self.mode.currentIndexChanged.connect(self.save_plan)
        self.fixed.editingFinished.connect(self.save_plan)
        self.in_forecast.toggled.connect(self.save_plan)
        self._loading = False

        # --- debts table
        self.table = table(["#", "Debt", "Type", "Balance", "Rate", "Limit used", "Min. now", "Paid off by",
                            "Interest left"], 1)
        self.table.setMinimumHeight(200)
        self.table.cellDoubleClicked.connect(self._edit_row)
        self.table.customContextMenuRequested.connect(self.menu)
        lay.addWidget(self.table)
        lay.addWidget(label("# is the order extra money goes · double-click to update a balance · "
                            "right-click for more", "Hint"))

        # --- chart + schedule
        chart = Card()
        chart.lay.addWidget(label("Total debt over time", "SectionTitle"))
        self.chart = BalanceChart()
        self.chart.setMinimumHeight(240)
        chart.lay.addWidget(self.chart)
        lay.addWidget(chart)

        sched = Card()
        sched.lay.addWidget(label("Payment schedule · next 12 months", "SectionTitle"))
        sched.lay.addWidget(label("Minimums plus the planned extra, by month · hover an amount for exact dates.",
                                  "Hint"))
        self.schedule = table(["Month"], 0)
        self.schedule.setMinimumHeight(2 * 38 + 44)
        self.schedule.setStyleSheet("QTableView { border: none; }")
        sched.lay.addWidget(self.schedule)
        lay.addWidget(sched)

    # ------------------------------------------------------------------
    def _edit_row(self, r, _c=None):
        it = self.table.item(r, 1)
        if it and it.data(Qt.UserRole):
            self.ctx.edit_debt(it.data(Qt.UserRole))

    def menu(self, pos):
        row = self.table.rowAt(pos.y())
        it = self.table.item(row, 1) if row >= 0 else None
        if not it or not it.data(Qt.UserRole):
            return
        debt_id = it.data(Qt.UserRole)
        m = QMenu(self.table)
        m.addAction("Update balance / edit…", lambda: self.ctx.edit_debt(debt_id))
        m.addSeparator()
        m.addAction("Delete", lambda: self.ctx.delete_debt(debt_id))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def save_plan(self):
        if self._loading:
            return
        s = self.ctx.data.settings
        s.debt_strategy = next(b.property("key") for b in self.strat_btns if b.isChecked())
        s.debt_mode = self.mode.currentData()
        s.debt_fixed_extra = self.fixed.cents()
        s.debt_in_forecast = self.in_forecast.isChecked()
        self.ctx.commit()

    def refresh(self):
        from ..debts import make_plan, minimum_payment
        from ..models import DEBT_KINDS, DEBT_STRATEGIES
        ctx, today = self.ctx, self.ctx.today
        data, s = ctx.data, ctx.data.settings
        self._loading = True
        for b in self.strat_btns:
            b.setChecked(b.property("key") == s.debt_strategy)
        self.mode.setCurrentIndex(0 if s.debt_mode == "auto" else 1)
        self.fixed.setPrefix(money._symbol)
        self.fixed.set_cents(s.debt_fixed_extra)
        self.fixed.setVisible(s.debt_mode == "fixed")
        self.in_forecast.setChecked(s.debt_in_forecast)
        self._loading = False

        debts = data.debts
        plan = ctx.plan
        total = sum(d.balance for d in debts)
        limits = sum(d.credit_limit for d in debts if d.credit_limit)
        used = sum(d.balance for d in debts if d.credit_limit)
        self.c_total.set(money.fmt(total), f"{len(debts)} debts" + (
            f" · {round(used / limits * 100)}% of credit limits used" if limits else ""),
            "negative" if total else "positive")
        interest = sum(round(d.balance * d.apr / 1200) for d in debts)
        self.c_interest.set(money.fmt(interest), f"≈ {money.fmt(interest * 12)} a year at today's balances",
                            "warning" if interest else None)

        if not debts:
            self.c_free.set("—", "Add a debt to build a plan")
            self.c_saved.set("—")
            self.banner.hide()
            self.next_action.setText("Add your credit cards, lines of credit and loans to get a payoff plan.")
            self.plan_hint.setText("")
            for t in (self.compare, self.table, self.schedule):
                t.setRowCount(0)
            self.chart.set_data([], None, 0)
            return

        mins = make_plan(data, today, mode="minimum")
        free = plan.debt_free
        self.c_free.set(free.strftime("%b %Y") if free else "Not on track",
                        _months_away(today, free) if free else "Minimums don't cover the interest, or it "
                                                                "takes over 10 years", "positive" if free else "negative")
        saved = mins.total_interest - plan.total_interest
        self.c_saved.set(money.fmt(max(0, saved)), "vs. paying only the minimums", "positive")

        # banner: stale balances / interest-only warnings
        stale = [d for d in debts if (today - d.updated_on).days > 35]
        never = [d for d in debts if d.id not in mins.payoff and d.balance > 0]
        if stale:
            self.banner.show_message(
                f"Update your balance for {', '.join(d.name for d in stale)} — it's been over a month. "
                "Double-click a debt to update it from your latest statement.", "warning")
        elif never and not free:
            self.banner.show_message(
                f"{', '.join(d.name for d in never)}: the minimum payment only covers interest. "
                "Extra payments are the only way to bring this down.", "warning")
        else:
            self.banner.hide()

        # next action
        nxt = plan.next_extra(today)
        if nxt:
            dname = data.debt(nxt.debt_id).name
            self.next_action.setText(f"👉  Next: pay {money.fmt(nxt.amount)} extra to {dname} on "
                                     f"{nxt.date.strftime('%A, %B %d')} (on top of the minimum).")
        elif s.debt_mode == "auto":
            self.next_action.setText("No extra money to spare right now — keep paying the minimums. "
                                     "The plan adds extra as soon as your forecast has room above your cushion.")
        else:
            self.next_action.setText("Set a fixed extra amount above to speed things up.")
        if s.debt_mode == "auto":
            self.plan_hint.setText(
                f"Extra payments are sized so your chequing balance never drops below your "
                f"{money.fmt(s.low_balance_threshold)} cushion (change it in Settings). "
                f"{DEBT_STRATEGIES[s.debt_strategy]} — " +
                ("saves the most interest." if s.debt_strategy == "avalanche" else "quick wins to keep you motivated."))
        else:
            self.plan_hint.setText("When a debt is paid off, its minimum payment rolls into the next one.")

        # comparison
        rows = [("Minimum payments only", mins)]
        for key, text in DEBT_STRATEGIES.items():
            rows.append((text, plan if key == s.debt_strategy else make_plan(data, today, strategy=key)))
        t = self.compare
        t.setRowCount(0)
        for name, p in rows:
            r = t.rowCount()
            t.insertRow(r)
            chosen = p is plan
            t.setItem(r, 0, cell(name + ("  ← your plan" if chosen else ""), bold=chosen,
                                 color="accent" if chosen else None))
            t.setItem(r, 1, cell(p.debt_free.strftime("%b %Y") if p.debt_free else "10+ years",
                                 color=None if p.debt_free else "negative"))
            t.setItem(r, 2, cell(money.fmt(p.total_interest), Qt.AlignRight))
            sv = mins.total_interest - p.total_interest
            t.setItem(r, 3, cell(money.fmt(sv) if p is not mins else "—", Qt.AlignRight,
                                 "positive" if sv > 0 else "muted"))

        # debts table
        order = {d_id: i + 1 for i, d_id in enumerate(plan.order)}
        t = self.table
        t.setRowCount(0)
        for d in sorted(debts, key=lambda d: order.get(d.id, 99)):
            r = t.rowCount()
            t.insertRow(r)
            interest_m = d.balance * d.apr / 1200
            mp = round(minimum_payment(d, d.balance + interest_m, interest_m))
            t.setItem(r, 0, cell(str(order.get(d.id, "✓")), color="accent", bold=True))
            sub = DEBT_KINDS[d.kind]
            name_cell = cell(d.name, bold=True, data=d.id)
            name_cell.setToolTip(f"{sub}" + (f" — {d.notes}" if d.notes else ""))
            t.setItem(r, 1, name_cell)
            t.setItem(r, 2, cell(sub, color="muted"))
            t.setItem(r, 3, cell(money.fmt(d.balance), Qt.AlignRight, bold=True))
            t.setItem(r, 4, cell(f"{d.apr:.2f}%", Qt.AlignRight, "negative" if d.apr >= 15 else None))
            if d.credit_limit:
                pct = round(d.balance / d.credit_limit * 100)
                t.setItem(r, 5, cell(f"{pct}%", Qt.AlignRight,
                                     "negative" if pct > 70 else "warning" if pct > 30 else "positive"))
            else:
                t.setItem(r, 5, cell("—", Qt.AlignRight, "muted"))
            t.setItem(r, 6, cell(money.fmt(mp), Qt.AlignRight))
            po = plan.payoff.get(d.id)
            t.setItem(r, 7, cell(po.strftime("%b %Y") if po else "10+ years", Qt.AlignRight,
                                 None if po else "negative"))
            t.setItem(r, 8, cell(money.fmt(plan.interest.get(d.id, 0)), Qt.AlignRight, "muted"))

        # chart (daily steps from the monthly totals)
        pts = []
        cur = total
        it = iter(plan.totals)
        nxt_pt = next(it, None)
        end = plan.totals[-1][0] if plan.totals else today
        day = today
        while day <= end:
            while nxt_pt and nxt_pt[0] < day:
                cur = nxt_pt[1]
                nxt_pt = next(it, None)
            pts.append((day, cur))
            day += timedelta(days=1)
        self.chart.set_data(pts, None, 0)

        # schedule
        rows = plan.month_rows(today, 12)
        live = [d for d in debts if any(d.id in per for _, per, _ in rows)]
        t = self.schedule
        t.clear()
        t.setColumnCount(len(live) + 3)
        t.setHorizontalHeaderLabels(["Month"] + [d.name for d in live] + ["of which extra", "Total"])
        hh = t.horizontalHeader()
        for i in range(t.columnCount()):
            hh.setSectionResizeMode(i, QHeaderView.Stretch)
        t.setRowCount(0)
        for first, per, extra in rows:
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, cell(first.strftime("%B %Y"), bold=True))
            nxt_month = add_months(first, 1, 1)
            for j, d in enumerate(live):
                v = per.get(d.id)
                c = cell(money.fmt(v) if v else "—", Qt.AlignRight, None if v else "muted")
                tips = [f"{p.date.strftime('%a %b %d')}: {'extra' if p.extra else 'minimum'} {money.fmt(p.amount)}"
                        for p in plan.payments if p.debt_id == d.id and first <= p.date < nxt_month]
                if tips:
                    c.setToolTip("\n".join(tips))
                t.setItem(r, j + 1, c)
            t.setItem(r, len(live) + 1, cell(money.fmt(extra) if extra else "—", Qt.AlignRight,
                                             "positive" if extra else "muted"))
            t.setItem(r, len(live) + 2, cell(money.fmt(sum(per.values())) if per else "—", Qt.AlignRight,
                                             None if per else "muted", bold=bool(per)))
            if not per and r == 0:
                t.item(r, 0).setToolTip("Nothing left to pay this month — due dates have already passed.")
        if not rows:
            t.insertRow(0)
            t.setItem(0, 0, cell("No payments scheduled — add a debt with a balance above $0.", color="muted"))
        t.setFixedHeight(max(1, t.rowCount()) * 38 + 44)


def _months_away(today: date, d: date) -> str:
    m = (d.year - today.year) * 12 + d.month - today.month
    if m <= 0:
        return "this month"
    y, mm = divmod(m, 12)
    parts = ([f"{y} year{'s' if y != 1 else ''}"] if y else []) + ([f"{mm} month{'s' if mm != 1 else ''}"] if mm else [])
    return "in " + " ".join(parts)
