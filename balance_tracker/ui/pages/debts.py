"""Debts: balances, the payoff plan, and its payment schedule."""
from __future__ import annotations

from datetime import timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHeaderView, QMenu, QPushButton

from ... import money
from ...debts import Plan, make_plan, minimum_payment
from ...forecast import add_months
from ...formatting import months_away, relative_day, short_date
from ...models import DEBT_KINDS, DEBT_STRATEGIES, INCOME
from ..charts import BalanceChart
from ..widgets import Banner, Card, MoneySpin, StatCard, chips, chosen, hbox, label, select_chip
from .common import Page, add_row, borderless, cell, row_data, table

STALE_DAYS = 35  # nag to update a balance from the latest statement after this long


class DebtsPage(Page):
    def __init__(self, ctx):
        super().__init__(ctx, "Debts", "Credit cards, lines of credit and loans — with a payoff plan that only uses "
                                       "money your forecast says you can spare.")
        add = QPushButton("+  Add debt")
        add.setObjectName("Primary")
        add.setToolTip("Ctrl+D")
        add.clicked.connect(ctx.add_debt)
        self.header.addWidget(add, 0, Qt.AlignTop)
        self._loading = False

        self.banner = Banner()
        self.body.addWidget(self.banner)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.c_total = StatCard("TOTAL OWED")
        self.c_interest = StatCard("INTEREST THIS MONTH")
        self.c_free = StatCard("DEBT-FREE BY")
        self.c_saved = StatCard("INTEREST SAVED")
        for i, w in enumerate((self.c_total, self.c_interest, self.c_free, self.c_saved)):
            grid.addWidget(w, 0, i)
        self.body.addLayout(grid)

        # --- plan controls
        plan = Card()
        plan.lay.addWidget(label("Your payoff plan", "SectionTitle"))
        self.strat_btns = chips([(text, key) for key, text in DEBT_STRATEGIES.items()], self.save_plan, plan)
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
        self.compare = borderless(table(["Approach", "Debt-free by", "Total interest", "Interest saved"], 0))
        self.compare.setFixedHeight(3 * 38 + 44)
        plan.lay.addWidget(self.compare)
        self.body.addWidget(plan)
        self.mode.currentIndexChanged.connect(self.save_plan)
        self.fixed.editingFinished.connect(self.save_plan)
        self.in_forecast.toggled.connect(self.save_plan)

        # --- debts table
        self.table = table(["#", "Debt", "Type", "Balance", "Rate", "Limit used", "Min. now", "Paid off by",
                            "Interest left"], 1)
        self.table.setMinimumHeight(200)
        self.table.cellDoubleClicked.connect(self._edit_row)
        self.table.customContextMenuRequested.connect(self.menu)
        self.body.addWidget(self.table)
        self.body.addWidget(label("# is the order extra money goes · double-click to update a balance · "
                                  "right-click for more", "Hint"))

        # --- chart + schedule
        chart = Card()
        chart.lay.addWidget(label("Total debt over time", "SectionTitle"))
        self.chart = BalanceChart()
        self.chart.setMinimumHeight(240)
        chart.lay.addWidget(self.chart)
        self.body.addWidget(chart)

        sched = Card()
        sched.lay.addWidget(label("Payment schedule · next 12 months", "SectionTitle"))
        sched.lay.addWidget(label("Minimums plus the planned extra, by month · hover an amount for exact dates.",
                                  "Hint"))
        self.schedule = borderless(table(["Month"], 0))
        self.schedule.setMinimumHeight(2 * 38 + 44)
        sched.lay.addWidget(self.schedule)
        self.body.addWidget(sched)

    # ------------------------------------------------------------------
    def _edit_row(self, r, _c=None):
        debt_id = row_data(self.table, r, 1)
        if debt_id:
            self.ctx.edit_debt(debt_id)

    def menu(self, pos):
        debt_id = row_data(self.table, self.table.rowAt(pos.y()), 1)
        if not debt_id:
            return
        m = QMenu(self.table)
        m.addAction("Update balance / edit…", lambda: self.ctx.edit_debt(debt_id))
        m.addSeparator()
        m.addAction("Delete", lambda: self.ctx.delete_debt(debt_id))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def save_plan(self):
        if self._loading:
            return
        s = self.ctx.data.settings
        s.debt_strategy = chosen(self.strat_btns)
        s.debt_mode = self.mode.currentData()
        s.debt_fixed_extra = self.fixed.cents()
        s.debt_in_forecast = self.in_forecast.isChecked()
        self.ctx.commit()

    def refresh(self):
        ctx, today = self.ctx, self.ctx.today
        data, s = ctx.data, ctx.data.settings
        self._loading = True
        select_chip(self.strat_btns, s.debt_strategy)
        self.mode.setCurrentIndex(0 if s.debt_mode == "auto" else 1)
        self.fixed.setPrefix(money.symbol())
        self.fixed.set_cents(s.debt_fixed_extra)
        self.fixed.setVisible(s.debt_mode == "fixed")
        self.in_forecast.setChecked(s.debt_in_forecast)
        self._loading = False

        debts = data.debts
        total = sum(d.balance for d in debts)
        limits = sum(d.credit_limit for d in debts if d.credit_limit)
        used = sum(d.balance for d in debts if d.credit_limit)
        self.c_total.set(money.fmt(total), f"{len(debts)} debts" + (
            f" · {round(used / limits * 100)}% of credit limits used" if limits else ""),
            "negative" if total else "positive")
        interest = sum(round(d.balance * d.apr / 1200) for d in debts)
        self.c_interest.set(money.fmt(interest), f"≈ {money.fmt(interest * 12)} a year at today's balances",
                            "warning" if interest else None)

        plan = ctx.plan
        if not debts or plan is None:
            self.c_free.set("—", "Add a debt to build a plan" if not debts else "Enter a starting balance first")
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
        self.c_free.set(f"{free:%b %Y}" if free else "Not on track",
                        months_away(free, today) if free
                        else "Minimums don't cover the interest, or it takes over 10 years",
                        "positive" if free else "negative")
        self.c_saved.set(money.fmt(max(0, mins.total_interest - plan.total_interest)), "vs. paying only the minimums",
                         "positive")
        self._refresh_banner(mins, free)
        self._refresh_next_action(plan)
        self._refresh_compare(plan, mins)
        self._refresh_table(plan)
        self._refresh_chart(plan, total)
        self._refresh_schedule(plan)

    def _refresh_banner(self, mins: Plan, free):
        today, debts = self.ctx.today, self.ctx.data.debts
        stale = [d for d in debts if (today - d.updated_on).days > STALE_DAYS]
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

    def _refresh_next_action(self, plan: Plan):
        ctx, today, s = self.ctx, self.ctx.today, self.ctx.data.settings
        nxt = plan.next_extra(today)
        if nxt:
            payday = any(e.kind == INCOME and e.date == nxt.date for e in ctx.forecast.entries)
            name = ctx.data.debt(nxt.debt_id).name
            self.next_action.setText(f"👉  Next: pay {money.fmt(nxt.amount)} extra to {name} "
                                     f"{relative_day(nxt.date, today)}{' — the day your pay lands' if payday else ''} "
                                     "(on top of the minimum).")
        elif s.debt_mode == "auto":
            self.next_action.setText("No extra money to spare right now — keep paying the minimums. "
                                     "The plan adds extra as soon as your forecast has room above your cushion.")
        else:
            self.next_action.setText("Set a fixed extra amount above to speed things up.")
        if s.debt_mode == "auto":
            why = "saves the most interest." if s.debt_strategy == "avalanche" else "quick wins to keep you motivated."
            self.plan_hint.setText(
                "Extra payments go out as soon as it's safe — usually the day your pay lands — and each is "
                "sized by checking every future day, so your balance never drops below your "
                f"{money.fmt(s.low_balance_threshold)} cushion (change it in Settings). "
                f"{DEBT_STRATEGIES[s.debt_strategy]} — {why}")
        else:
            self.plan_hint.setText("When a debt is paid off, its minimum payment rolls into the next one.")

    def _refresh_compare(self, plan: Plan, mins: Plan):
        data, today, s = self.ctx.data, self.ctx.today, self.ctx.data.settings
        rows = [("Minimum payments only", mins)]
        for key, text in DEBT_STRATEGIES.items():
            rows.append((text, plan if key == s.debt_strategy else make_plan(data, today, strategy=key)))
        t = self.compare
        t.setRowCount(0)
        for name, p in rows:
            chosen_plan = p is plan
            saved = mins.total_interest - p.total_interest
            add_row(t, cell(name + ("  ← your plan" if chosen_plan else ""), bold=chosen_plan,
                            color="accent" if chosen_plan else None),
                    cell(f"{p.debt_free:%b %Y}" if p.debt_free else "10+ years",
                         color=None if p.debt_free else "negative"),
                    cell(money.fmt(p.total_interest), Qt.AlignRight),
                    cell(money.fmt(saved) if p is not mins else "—", Qt.AlignRight,
                         "positive" if saved > 0 else "muted"))

    def _refresh_table(self, plan: Plan):
        order = {d_id: i + 1 for i, d_id in enumerate(plan.order)}
        t = self.table
        t.setRowCount(0)
        for d in sorted(self.ctx.data.debts, key=lambda d: order.get(d.id, 99)):
            interest_m = d.balance * d.apr / 1200
            min_now = round(minimum_payment(d, d.balance + interest_m, interest_m))
            kind = DEBT_KINDS[d.kind]
            name = cell(d.name, bold=True, data=d.id)
            name.setToolTip(kind + (f" — {d.notes}" if d.notes else ""))
            if d.credit_limit:
                pct = round(d.balance / d.credit_limit * 100)
                used = cell(f"{pct}%", Qt.AlignRight, "negative" if pct > 70 else "warning" if pct > 30 else "positive")
            else:
                used = cell("—", Qt.AlignRight, "muted")
            paid_off = plan.payoff.get(d.id)
            add_row(t, cell(str(order.get(d.id, "✓")), color="accent", bold=True), name, cell(kind, color="muted"),
                    cell(money.fmt(d.balance), Qt.AlignRight, bold=True),
                    cell(f"{d.apr:.2f}%", Qt.AlignRight, "negative" if d.apr >= 15 else None), used,
                    cell(money.fmt(min_now), Qt.AlignRight),
                    cell(f"{paid_off:%b %Y}" if paid_off else "10+ years", Qt.AlignRight,
                         None if paid_off else "negative"),
                    cell(money.fmt(plan.interest.get(d.id, 0)), Qt.AlignRight, "muted"))

    def _refresh_chart(self, plan: Plan, total: int):
        """Daily steps from the plan's month-end totals."""
        today = self.ctx.today
        pts = []
        cur = total
        it = iter(plan.totals)
        nxt = next(it, None)
        end = plan.totals[-1][0] if plan.totals else today
        day = today
        while day <= end:
            while nxt and nxt[0] < day:
                cur = nxt[1]
                nxt = next(it, None)
            pts.append((day, cur))
            day += timedelta(days=1)
        self.chart.set_data(pts, None, 0)

    def _refresh_schedule(self, plan: Plan):
        rows = plan.month_rows(self.ctx.today, 12)
        live = [d for d in self.ctx.data.debts if any(d.id in per for _, per, _ in rows)]
        t = self.schedule
        t.clear()
        t.setColumnCount(len(live) + 3)
        t.setHorizontalHeaderLabels(["Month"] + [d.name for d in live] + ["of which extra", "Total"])
        for i in range(t.columnCount()):
            t.horizontalHeader().setSectionResizeMode(i, QHeaderView.Stretch)
        t.setRowCount(0)
        for first, per, extra in rows:
            next_month = add_months(first, 1, 1)
            cells = [cell(f"{first:%B %Y}", bold=True)]
            for d in live:
                v = per.get(d.id)
                c = cell(money.fmt(v) if v else "—", Qt.AlignRight, None if v else "muted")
                tips = [f"{short_date(p.date)}: {'extra' if p.extra else 'minimum'} {money.fmt(p.amount)}"
                        for p in plan.payments if p.debt_id == d.id and first <= p.date < next_month]
                if tips:
                    c.setToolTip("\n".join(tips))
                cells.append(c)
            cells.append(cell(money.fmt(extra) if extra else "—", Qt.AlignRight, "positive" if extra else "muted"))
            cells.append(cell(money.fmt(sum(per.values())) if per else "—", Qt.AlignRight, None if per else "muted",
                              bold=bool(per)))
            r = add_row(t, *cells)
            if not per and r == 0:
                t.item(r, 0).setToolTip("Nothing left to pay this month — due dates have already passed.")
        if not rows:
            add_row(t, cell("No payments scheduled — add a debt with a balance above $0.", color="muted"))
        t.setFixedHeight(max(1, t.rowCount()) * 38 + 44)
