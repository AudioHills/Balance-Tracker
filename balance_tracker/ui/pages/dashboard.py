"""Dashboard: today's balance, alerts, the forecast chart and what's coming up."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout

from ... import money
from ...forecast import Forecast, add_months, horizon_end
from ...formatting import ago, days_away, long_date, nice_date, relative_day, short_date
from ...insights import PAYDAY_WINDOW_DAYS, monthly_totals, payday_outlook, unpaid_card_charges, unplanned_summary
from ...models import BILL, INCOME
from .. import theme
from ..charts import BalanceChart
from ..widgets import MASK, Banner, Card, EyeButton, Metric, StatCard, chips, chosen, clear_layout, hbox, label
from .common import Page, add_row, bal_color, borderless, cell, table

CARD_TODO_DAYS = 14  # how far back the "Pay your card" list looks


class DashboardPage(Page):
    RANGES = [("1M", 1), ("3M", 3), ("6M", 6), ("1Y", 12)]

    def __init__(self, ctx):
        super().__init__(ctx, "Dashboard")
        phone = QPushButton("📱 Reminders")
        phone.setToolTip("Send payment reminders to your phone or calendar")
        phone.clicked.connect(ctx.reminders)
        afford = QPushButton("Can I afford it?")
        afford.setToolTip("Ctrl+A")
        afford.clicked.connect(ctx.afford)
        check = QPushButton("Check in balance")
        check.setObjectName("Primary")
        check.setToolTip("Ctrl+K")
        check.clicked.connect(ctx.check_in)
        for b in (phone, afford, check):
            self.header.addWidget(b, 0, Qt.AlignTop)

        self.banner = Banner()
        self.body.addWidget(self.banner)
        self._build_card_todo()

        grid = QGridLayout()
        grid.setSpacing(14)
        self.c_today = StatCard("BALANCE TODAY")
        self.eye = EyeButton()
        self.eye.clicked.connect(ctx.toggle_balance)
        self.c_today.title_row.addWidget(self.eye)
        self.c_safe = StatCard("SAFE TO SPEND")
        self.c_low = StatCard("LOWEST POINT AHEAD")
        self.c_unplanned = StatCard("UNPLANNED THIS MONTH")
        for i, w in enumerate((self.c_today, self.c_safe, self.c_low, self.c_unplanned)):
            grid.addWidget(w, 0, i)
        self.body.addLayout(grid)

        self._build_payday()
        self._build_chart()
        self._build_bottom()

    # ---- layout ----------------------------------------------------------
    def _build_card_todo(self):
        """'Pay your card' to-do list for bills charged to a credit card."""
        self.card_box = Card(spacing=6)
        self.card_box.lay.addLayout(hbox(label("💳  Pay your card", "SectionTitle"), None,
                                         label("Bills that landed on a credit card — pay them off and tick them",
                                               "Hint")))
        self.card_rows = QVBoxLayout()
        self.card_rows.setSpacing(4)
        self.card_box.lay.addLayout(self.card_rows)
        self.card_box.hide()
        self.body.addWidget(self.card_box)

    def _build_payday(self):
        self.payday_box = Card(spacing=12)
        self.payday_title = label("", "SectionTitle")
        self.payday_box.lay.addWidget(self.payday_title)
        row = QHBoxLayout()
        row.setSpacing(28)
        self.m_daily = Metric("SPEND UP TO")
        self.m_bills = Metric("GOING OUT BEFORE THEN")
        self.m_low = Metric("LOWEST BEFORE PAYDAY")
        self.m_pay = Metric("PAYCHEQUE")
        for m in (self.m_daily, self.m_bills, self.m_low, self.m_pay):
            row.addWidget(m, 1)
        self.payday_box.lay.addLayout(row)
        self.payday_hint = label("", "Hint", wrap=True)
        self.payday_box.lay.addWidget(self.payday_hint)
        self.body.addWidget(self.payday_box)

    def _build_chart(self):
        chart_card = Card()
        self.range_btns = chips([(t, m) for t, m in self.RANGES], self.refresh, chart_card, checked=1)
        chart_card.lay.addLayout(hbox(label("Balance forecast", "SectionTitle"), None, *self.range_btns, spacing=6))
        chart_card.lay.addWidget(label("Hover to see any day · click to open it in Day by day", "Hint"))
        self.chart = BalanceChart()
        self.chart.dayClicked.connect(self.ctx.show_day)
        chart_card.lay.addWidget(self.chart, 1)
        chart_card.setMinimumHeight(340)
        self.body.addWidget(chart_card, 1)

    def _build_bottom(self):
        bottom = QHBoxLayout()
        bottom.setSpacing(14)
        up_card = Card()
        up_card.lay.addWidget(label("Coming up · next 14 days", "SectionTitle"))
        self.upcoming = borderless(table(["When", "What", "Amount", "Balance after"]))
        self.upcoming.setMinimumHeight(260)
        up_card.lay.addWidget(self.upcoming)
        bottom.addWidget(up_card, 3)

        snap = Card()
        snap.lay.addWidget(label("Monthly snapshot", "SectionTitle"))
        snap.lay.addWidget(label("Average per month, from your recurring entries", "Hint"))
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.s_income, self.s_bills, self.s_net, self.s_unplanned, self.s_debt = (
            label("", "SectionTitle") for _ in range(5))
        form.addRow(label("Income", "Muted"), self.s_income)
        form.addRow(label("Bills", "Muted"), self.s_bills)
        form.addRow(label("Left over", "Muted"), self.s_net)
        form.addRow(label("Avg. unplanned", "Muted"), self.s_unplanned)
        self.s_debt_label = label("Debt-free by", "Muted")
        form.addRow(self.s_debt_label, self.s_debt)
        snap.lay.addLayout(form)
        self.snap_tip = label("", "Hint", wrap=True)
        snap.lay.addWidget(self.snap_tip)
        snap.lay.addStretch(1)
        bottom.addWidget(snap, 2)
        self.body.addLayout(bottom)

    # ---- refresh ---------------------------------------------------------
    def refresh(self):
        ctx, f, today = self.ctx, self.ctx.forecast, self.ctx.today
        s = ctx.data.settings
        hour = datetime.now().hour
        greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
        self.subtitle.setText(f"{greet} — here's {s.account_name} as of {long_date(today)}.")
        if f.empty:
            for c in (self.c_today, self.c_safe, self.c_low, self.c_unplanned):
                c.set("—")
            self.chart.set_data([], today, 0)
            self.payday_box.hide()
            self.card_box.hide()
            self.banner.show_message("Start by entering your current balance — click “Check in balance”.", "warning")
            return
        hidden = s.hide_balance
        horizon = horizon_end(ctx.data, today)
        room, plan_sweeps = self._spending_forecast(today)
        self._refresh_stats(today, hidden, horizon, room, plan_sweeps)
        self._refresh_cards(today)
        self._refresh_banner(today, hidden, horizon)
        self._refresh_payday(today, hidden, room, plan_sweeps)
        self._refresh_chart(today)
        self._refresh_upcoming(today)
        self._refresh_snapshot(today)

    def _spending_forecast(self, today: date) -> tuple[Forecast, bool]:
        """The forecast to measure spending room on, and whether the payoff plan's extra payments
        were left out of it. In "as much as my cushion allows" mode the plan sends every spare
        dollar to debt and shrinks to fit whatever is spent, so (like "Can I afford it?") spending
        room is measured before those extra payments."""
        ctx, s = self.ctx, self.ctx.data.settings
        soon = today + timedelta(days=PAYDAY_WINDOW_DAYS)
        sweeps = ctx.plan is not None and s.debt_in_forecast and any(
            p.extra and today <= p.date <= soon for p in ctx.plan.payments)
        if not sweeps:
            return ctx.forecast, False
        return ctx.build_forecast(debt_extras=False, end=soon + timedelta(days=1)), True

    def _refresh_stats(self, today: date, hidden: bool, horizon: date, room: Forecast, plan_sweeps: bool):
        f, s = self.ctx.forecast, self.ctx.data.settings
        bal = f.balance_on(today)
        last = self.ctx.data.latest_checkpoint
        self.eye.set_state(hidden)
        note = f"Last checked in {ago(last.date, today)}"
        if last.date == today and not last.includes_today and bal is not None and bal != last.balance:
            pending = bal - last.balance
            note += ("\nIncludes items still to go through today" if hidden else
                     f"\nBank showed {money.fmt(last.balance)} at check-in · {money.fmt(pending, signed=True)} "
                     f"still to {'come out' if pending < 0 else 'come in'} today")
        self.c_today.set(MASK if hidden else money.fmt(bal), note,
                         None if hidden or bal is None else bal_color(bal, s.low_balance_threshold))

        safe = room.safe_to_spend(today, 30, s.low_balance_threshold)
        if safe is None:
            self.c_safe.set("—")
        elif safe >= 0:
            self.c_safe.set(money.fmt(safe), f"Keeps your {money.fmt(s.low_balance_threshold)} cushion for 30 days"
                            + (" — what you don't spend goes to your debt plan" if plan_sweeps else ""), "positive")
        else:
            self.c_safe.set(money.fmt(0), f"You're {money.fmt(-safe)} short of your cushion in the next 30 days",
                            "negative")

        low = f.lowest(today, horizon)
        if low:
            self.c_low.set(MASK if hidden else money.fmt(low[1]), f"on {nice_date(low[0], today)}",
                           None if hidden else bal_color(low[1], s.low_balance_threshold))

        this = unplanned_summary(f, today).this_month
        if this < 0:
            self.c_unplanned.set(money.fmt(-this), "spent beyond your plan", "negative")
        elif this > 0:
            self.c_unplanned.set(money.fmt(this, signed=True), "more than planned", "positive")
        else:
            self.c_unplanned.set(money.fmt(0), "Nothing unplanned so far", "positive")

    def _refresh_cards(self, today: date):
        due = unpaid_card_charges(self.ctx.data, today, CARD_TODO_DAYS)
        clear_layout(self.card_rows)
        self.card_box.setVisible(bool(due))
        col = theme.colors()
        for c in due:
            late = c.occurrence.date < today
            txt = label(f"<b>{money.fmt(c.amount)}</b> to {c.card.name} — {c.occurrence.item.name} "
                        f"<span style='color:{col['negative' if late else 'muted']}'>"
                        f"({nice_date(c.occurrence.date, today)})</span>")
            btn = QPushButton("✓ Paid")
            btn.setObjectName("Chip")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=c.key: self.ctx.mark_card_paid(k))
            self.card_rows.addLayout(hbox(txt, None, btn))

    def _refresh_banner(self, today: date, hidden: bool, horizon: date):
        f, s = self.ctx.forecast, self.ctx.data.settings
        neg = f.first_below(0, today, horizon)
        below = f.first_below(s.low_balance_threshold, today, horizon)
        days_since = (today - self.ctx.data.latest_checkpoint.date).days
        if neg:
            self.banner.show_message(
                f"⚠  Heads up: you're projected to be in overdraft{'' if hidden else f' ({money.fmt(neg[1])})'} "
                f"{relative_day(neg[0], today)}. Consider moving a bill or trimming spending.", "negative")
        elif below and s.low_balance_threshold > 0:
            self.banner.show_message(
                f"Your balance dips below your {money.fmt(s.low_balance_threshold)} cushion "
                f"{relative_day(below[0], today)}{'' if hidden else f' ({money.fmt(below[1])})'}.", "warning")
        elif days_since >= 7:
            self.banner.show_message(
                f"It's been {days_since} days since your last check-in — a quick update keeps the forecast honest.",
                "warning")
        else:
            self.banner.hide()

    def _refresh_payday(self, today: date, hidden: bool, room: Forecast, plan_sweeps: bool):
        """Until-payday card: bills and balances from the forecast as shown, the daily allowance
        from the spending-room forecast (see _spending_forecast)."""
        cushion = self.ctx.data.settings.low_balance_threshold
        o = payday_outlook(self.ctx.forecast, today, cushion)
        self.payday_box.setVisible(o is not None)
        if o is None:
            return
        daily = payday_outlook(room, today, cushion).daily if plan_sweeps else o.daily
        if o.payday:
            self.payday_title.setText(f"Until payday · {short_date(o.payday)} ({days_away(o.payday, today)})")
            self.m_pay.set(money.fmt(o.pay, signed=True), "lands that day", "positive")
        else:
            self.payday_title.setText("Next 30 days · no paycheque scheduled")
            self.m_pay.set("—", "Add your income under Income & Bills")
        self.m_daily.set(f"{money.fmt(daily)} / day", f"for {o.days} day{'s' if o.days != 1 else ''}",
                         "positive" if daily else "negative")
        self.m_bills.set(money.fmt(o.bills), f"{o.bill_count} bill{'s' if o.bill_count != 1 else ''}"
                         if o.bill_count else "Nothing scheduled")
        if o.lowest:
            when = nice_date(o.lowest[0], today)
            self.m_low.set(MASK if hidden else money.fmt(o.lowest[1]), f"on {when}",
                           None if hidden else bal_color(o.lowest[1], cushion))
        if daily:
            self.payday_hint.setText(
                f"Spend up to {money.fmt(daily)} a day and your balance stays above your {money.fmt(cushion)} "
                "cushion for the next 30 days — bills after payday included."
                + (" Your payoff plan's extra payments shrink to match what you spend." if plan_sweeps else ""))
        else:
            self.payday_hint.setText("There's no room for extra spending right now without dipping below your "
                                     f"{money.fmt(cushion)} cushion in the next 30 days.")

    def _refresh_chart(self, today: date):
        f = self.ctx.forecast
        months = chosen(self.range_btns)
        end = min(add_months(today, months), f.end)
        begin = max(f.start, today - timedelta(days=max(14, months * 7)))
        pts = [(d, v) for d, v in f.daily.items() if begin <= d <= end]
        self.chart.set_data(pts, today, self.ctx.data.settings.low_balance_threshold)

    def _refresh_upcoming(self, today: date):
        f, thr = self.ctx.forecast, self.ctx.data.settings.low_balance_threshold
        rows = [e for e in f.entries_between(today, today + timedelta(days=14)) if e.kind in (INCOME, BILL)]
        t = self.upcoming
        t.setRowCount(0)
        for e in rows:
            add_row(t, cell(nice_date(e.date, today), color="muted"), cell(e.description, bold=True),
                    cell(money.fmt(e.amount, True), Qt.AlignRight, "positive" if e.amount > 0 else "text"),
                    cell(money.fmt(e.balance), Qt.AlignRight, bal_color(e.balance, thr)))
        if not rows:
            add_row(t, None, cell("Nothing scheduled in the next two weeks", color="muted"))

    def _refresh_snapshot(self, today: date):
        ctx, col = self.ctx, theme.colors()
        totals = monthly_totals(ctx.data.items, today)
        self.s_income.setText(money.fmt(totals.income))
        self.s_income.setStyleSheet(f"color: {col['positive']};")
        self.s_bills.setText(money.fmt(totals.bills))
        self.s_net.setText(money.fmt(totals.net))
        self.s_net.setStyleSheet(f"color: {col['positive' if totals.net >= 0 else 'negative']};")
        has_debt = bool(ctx.plan and ctx.data.debts)
        self.s_debt.setVisible(has_debt)
        self.s_debt_label.setVisible(has_debt)
        if has_debt:
            free = ctx.plan.debt_free
            self.s_debt.setText(f"{free:%B %Y}" if free else "10+ years")
            self.s_debt.setStyleSheet(f"color: {col['positive' if free else 'negative']};")
        avg = unplanned_summary(ctx.forecast, today).average
        spent = -avg if avg is not None and avg < 0 else 0
        self.s_unplanned.setText("—" if avg is None else money.fmt(spent))
        if spent and totals.net > 0:
            self.snap_tip.setText(f"Unplanned spending is using about {round(spent / totals.net * 100)}% "
                                  "of what's left over each month.")
        elif totals.net < 0:
            self.snap_tip.setText("Your bills are higher than your income on average — the forecast will trend down.")
        else:
            self.snap_tip.setText("")
