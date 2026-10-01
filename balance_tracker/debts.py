"""Debt payoff planning.

The planner simulates each debt month by month (interest, then the minimum
payment on its due day) and puts any extra money toward one debt at a time:

* avalanche - highest interest rate first (saves the most interest)
* snowball  - smallest balance first (quickest wins)

In "auto" mode the extra amount for each month is the most that can be paid
while the projected chequing balance never drops below the user's cushion on
any later day. It is found greedily: month by month, given everything already
planned, extra = (lowest future chequing balance) - cushion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .forecast import Forecast, Occurrence, add_months, clamp_day
from .models import AppData, BILL, Debt, RecurringItem

YEARS = 10
MONTHS = YEARS * 12


@dataclass
class Payment:
    date: date
    debt_id: str
    amount: int  # cents
    extra: bool = False


@dataclass
class Plan:
    strategy: str
    payments: list = field(default_factory=list)
    payoff: dict = field(default_factory=dict)  # debt_id -> date (missing = not within horizon)
    interest: dict = field(default_factory=dict)  # debt_id -> cents
    totals: list = field(default_factory=list)  # [(date, total owed)] after each month
    extra_dates: dict = field(default_factory=dict)  # month index -> date extra would be paid
    remaining_after_min: dict = field(default_factory=dict)  # month index -> cents still owed
    extras: dict = field(default_factory=dict)  # month index -> planned extra (cents)
    order: list = field(default_factory=list)  # debt ids in the order they get extra money

    @property
    def total_interest(self) -> int:
        return sum(self.interest.values())

    @property
    def debt_free(self) -> Optional[date]:
        if not self.payoff or len(self.payoff) < len(self.interest):
            return None
        return max(self.payoff.values())

    def next_extra(self, today: date) -> Optional[Payment]:
        return next((p for p in self.payments if p.extra and p.date >= today), None)

    def occurrences(self, debts: list, include_extra: bool = True) -> list:
        """Planned payments as forecast occurrences."""
        names = {d.id: d.name for d in debts}
        out = []
        for p in self.payments:
            if p.extra and not include_extra:
                continue
            label = f"{names.get(p.debt_id, 'Debt')} — {'extra payment (plan)' if p.extra else 'minimum payment'}"
            item = RecurringItem(name=label, amount=p.amount, kind=BILL, frequency="once",
                                 start_date=p.date, category="Debt", id="")
            out.append(Occurrence(p.date, p.date, -p.amount, item))
        return out

    def month_rows(self, today: date, months: int = 12) -> list:
        """[(month_start, {debt_id: cents}, extra_cents)] for the schedule table."""
        start = today.replace(day=1)
        last = max((p.date for p in self.payments), default=None)
        rows = []
        for m in range(months):
            first = add_months(start, m, 1)
            nxt = add_months(start, m + 1, 1)
            per = {}
            extra = 0
            for p in self.payments:
                if first <= p.date < nxt:
                    per[p.debt_id] = per.get(p.debt_id, 0) + p.amount
                    if p.extra:
                        extra += p.amount
            if last is None or first > last:
                break  # everything is paid off
            rows.append((first, per, extra))  # a month can be empty, e.g. this month's due date already passed
        return rows


def minimum_payment(debt: Debt, balance: float, interest: float) -> float:
    pct = balance * debt.min_percent / 100
    if debt.min_plus_interest:
        pct += interest
    return min(balance, max(debt.min_amount, pct))


def _order(debts, bals, strategy):
    live = [d for d in debts if bals[d.id] > 0.5]
    if strategy == "snowball":
        return sorted(live, key=lambda d: (bals[d.id], -d.apr, d.name.lower()))
    return sorted(live, key=lambda d: (-d.apr, bals[d.id], d.name.lower()))


def simulate(debts: list, today: date, strategy: str, extras: dict, months: int = MONTHS,
             rollover: bool = False) -> Plan:
    """Run the month-by-month payoff. `extras`: month index -> extra cents.
    With `rollover`, minimums freed up by paid-off debts are added to the extra."""
    plan = Plan(strategy=strategy, extras=dict(extras))
    bals = {d.id: float(d.balance) for d in debts}
    plan.interest = {d.id: 0 for d in debts}
    freed = 0.0
    month0 = today.replace(day=1)
    plan.order = [d.id for d in _order(debts, bals, strategy)]
    for d in debts:
        if bals[d.id] <= 0.5:
            plan.payoff[d.id] = today
    for m in range(months):
        if all(b <= 0.5 for b in bals.values()):
            break
        first = add_months(month0, m, 1)
        due = {d.id: clamp_day(first.year, first.month, d.due_day) for d in debts}
        last_min = {}
        for d in sorted(debts, key=lambda d: due[d.id]):
            bal = bals[d.id]
            if bal <= 0.5 or due[d.id] < today:
                continue
            interest = bal * d.apr / 1200
            bal += interest
            plan.interest[d.id] += round(interest)
            pay = round(minimum_payment(d, bal, interest))
            pay = min(pay, round(bal))
            if pay > 0:
                plan.payments.append(Payment(due[d.id], d.id, pay))
            bal -= pay
            last_min[d.id] = pay
            if bal <= 0.5:
                bal = 0.0
                plan.payoff[d.id] = due[d.id]
                freed += pay
            bals[d.id] = bal

        order = _order(debts, bals, strategy)
        if order:
            when = max(today, due[order[0].id])
            plan.extra_dates[m] = when
            plan.remaining_after_min[m] = round(sum(bals.values()))
            extra = extras.get(m, 0) + (round(freed) if rollover else 0)
            for d in order:
                if extra <= 0:
                    break
                pay = min(extra, round(bals[d.id]))
                if pay <= 0:
                    continue
                plan.payments.append(Payment(when, d.id, pay, extra=True))
                bals[d.id] -= pay
                extra -= pay
                if bals[d.id] <= 0.5:
                    bals[d.id] = 0.0
                    plan.payoff[d.id] = when
                    if rollover:
                        freed += last_min.get(d.id, 0)
        plan.totals.append((add_months(month0, m + 1, 1) - timedelta(days=1), round(sum(bals.values()))))
    plan.payments.sort(key=lambda p: (p.date, p.extra))
    return plan


def _round_down(cents: int) -> int:
    """Friendlier amounts: whole $10s above $100, whole dollars below."""
    if cents >= 10000:
        return cents // 1000 * 1000
    return cents // 100 * 100


def plan_start(data: AppData, today: date) -> date:
    """First day the plan can schedule a payment. If the balance was already checked in
    today (including today's items), anything new has to happen tomorrow."""
    lc = data.latest_checkpoint
    if lc and lc.date >= today and lc.includes_today:
        return lc.date + timedelta(days=1)
    return today


def base_forecast(data: AppData, today: date, years: int = YEARS) -> Forecast:
    """Chequing forecast without any debt payments (linked bills are replaced by the plan)."""
    start = plan_start(data, today)
    suppress = {d.linked_bill_id: start for d in data.debts if d.linked_bill_id}
    return Forecast(data, add_months(today, years * 12), today, suppress=suppress)


def make_plan(data: AppData, today: date, strategy: Optional[str] = None, mode: Optional[str] = None,
              base: Optional[Forecast] = None) -> Plan:
    s = data.settings
    base_today = today
    today = plan_start(data, today)
    strategy = strategy or s.debt_strategy
    mode = mode or s.debt_mode
    debts = [d for d in data.debts if d.balance > 0]
    if not debts:
        return Plan(strategy=strategy)
    if mode == "minimum":
        return simulate(debts, today, strategy, {})
    if mode == "fixed":
        extras = {m: s.debt_fixed_extra for m in range(MONTHS)} if s.debt_fixed_extra > 0 else {}
        return simulate(debts, today, strategy, extras, rollover=True)

    # auto: as much as the cushion allows
    base = base or base_forecast(data, base_today)
    days = []
    d = today
    while d <= base.end:
        v = base.daily.get(d)
        if v is not None:
            days.append((d, v))
        d += timedelta(days=1)
    if not days:
        return simulate(debts, today, strategy, {})
    index = {d: i for i, (d, _) in enumerate(days)}
    n = len(days)
    cushion = s.low_balance_threshold

    extras: dict = {}
    plan = simulate(debts, today, strategy, extras)
    for m in range(MONTHS):
        when = plan.extra_dates.get(m)
        if when is None or when > days[-1][0]:
            break
        # cumulative planned payments by day
        spent = [0] * n
        for p in plan.payments:
            i = index.get(p.date)
            if i is not None:
                spent[i] += p.amount
        run = 0
        low = None
        start_i = index[when]
        for i in range(n):
            run += spent[i]
            if i >= start_i:
                v = days[i][1] - run
                if low is None or v < low:
                    low = v
        avail = low - cushion
        owed = plan.remaining_after_min.get(m, 0)
        room = owed if avail >= owed else _round_down(avail)
        if room > 0:
            extras[m] = room
            plan = simulate(debts, today, strategy, extras)
    return plan
