"""Summaries computed from the data and the forecast, shown on the dashboard and in reminders.

Nothing here touches the UI, so every number the app shows can be unit-tested, and the
iPhone app's port (web/engine.js) is cross-checked against it.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from .forecast import Forecast, Occurrence, add_months, monthly_equivalent, occurrences
from .models import BILL, INCOME, AppData, Debt, RecurringItem, card_paid_key

UNCATEGORIZED = "Uncategorized"
PAYDAY_WINDOW_DAYS = 30  # same window as "Safe to spend"


# --------------------------------------------------------------------------
# Monthly averages from the recurring entries
# --------------------------------------------------------------------------
def counts_toward_monthly(item: RecurringItem, today: date) -> bool:
    """Active, repeating, and not already finished."""
    return item.active and item.frequency != "once" and (item.end_date is None or item.end_date >= today)


@dataclass(frozen=True)
class MonthlyTotals:
    income: int  # cents per month
    bills: int  # cents per month, positive

    @property
    def net(self) -> int:
        return self.income - self.bills


def monthly_totals(items: list[RecurringItem], today: date) -> MonthlyTotals:
    """Average income and bills per month from the entries that are still running."""
    live = [i for i in items if counts_toward_monthly(i, today)]
    return MonthlyTotals(
        income=sum(monthly_equivalent(i) for i in live if i.kind == INCOME),
        bills=-sum(monthly_equivalent(i) for i in live if i.kind == BILL),
    )


@dataclass(frozen=True)
class CategoryShare:
    category: str
    monthly: int  # cents per month, positive
    share: float  # fraction of all monthly bills


def bills_by_category(items: list[RecurringItem], today: date) -> list[CategoryShare]:
    """Where the monthly bills go, biggest first. Categories match regardless of letter case."""
    totals: dict[str, int] = defaultdict(int)
    names: dict[str, str] = {}
    for i in items:
        if i.kind != BILL or not counts_toward_monthly(i, today):
            continue
        name = i.category.strip() or UNCATEGORIZED
        key = name.lower()
        names.setdefault(key, name)
        totals[key] -= monthly_equivalent(i)
    grand = sum(v for v in totals.values() if v > 0)
    rows = sorted(((names[k], v) for k, v in totals.items() if v > 0), key=lambda r: (-r[1], r[0].lower()))
    return [CategoryShare(name, v, v / grand) for name, v in rows]


# --------------------------------------------------------------------------
# Credit-card charges waiting to be paid off
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class CardCharge:
    occurrence: Occurrence
    card: Debt

    @property
    def key(self) -> str:
        return card_paid_key(self.occurrence.item.id, self.occurrence.date)

    @property
    def amount(self) -> int:
        return abs(self.occurrence.amount)


def unpaid_card_charges(data: AppData, today: date, days: int) -> list[CardCharge]:
    """Bills charged to a card in the last `days` days (and today) not yet marked as paid."""
    paid = set(data.card_paid)
    out = []
    for item in data.items:
        card = data.card_for(item)
        if card is None:
            continue
        for o in occurrences(item, today - timedelta(days=days), today):
            charge = CardCharge(o, card)
            if charge.key not in paid:
                out.append(charge)
    out.sort(key=lambda c: c.occurrence.date)
    return out


# --------------------------------------------------------------------------
# Unplanned spending (from check-ins)
# --------------------------------------------------------------------------
def previous_months(today: date, n: int) -> list[tuple[int, int]]:
    """The n full months before this one as (year, month), most recent first."""
    first = today.replace(day=1)
    return [(m.year, m.month) for m in (add_months(first, -k, 1) for k in range(1, n + 1))]


@dataclass(frozen=True)
class UnplannedSummary:
    this_month: int  # net unplanned so far this month (negative = spent beyond the plan)
    average: int | None  # per month, over recent full months that had check-ins
    months_tracked: int
    total: int  # since the starting balance
    checkins: int


def unplanned_summary(forecast: Forecast, today: date, months: int = 6) -> UnplannedSummary:
    by_month = forecast.unplanned_by_month()
    tracked = [by_month[k] for k in previous_months(today, months) if k in by_month]
    return UnplannedSummary(
        this_month=by_month.get((today.year, today.month), 0),
        average=round(sum(tracked) / len(tracked)) if tracked else None,
        months_tracked=len(tracked),
        total=sum(by_month.values()),
        checkins=len(forecast.checkins()),
    )


# --------------------------------------------------------------------------
# Until the next payday
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class PaydayOutlook:
    payday: date | None  # next income after today, if within the window
    pay: int  # total income landing that day
    days: int  # spending days counted: today until the day before payday (or the whole window)
    bills: int  # money going out (positive cents) from today until payday
    bill_count: int
    lowest: tuple[date, int] | None  # lowest end-of-day balance before payday
    daily: int  # the most you can spend every day until payday and stay above your cushion


def payday_outlook(forecast: Forecast, today: date, cushion: int,
                   window_days: int = PAYDAY_WINDOW_DAYS) -> PaydayOutlook | None:
    """How things look until the next paycheque, with an even daily spending allowance.

    Spending X a day for the `days` days before payday lowers day k (0 = today) of the forecast by
    X * min(k + 1, days). The allowance is the largest whole-dollar X that keeps every day of the
    window at or above the cushion — including days after payday, so a big bill right after
    the paycheque is still protected.
    """
    if forecast.balance_on(today) is None:
        return None
    window_end = today + timedelta(days=window_days)
    nxt = forecast.next_income(today)
    payday = nxt.date if nxt is not None and nxt.date <= window_end else None
    last_spend_day = payday - timedelta(days=1) if payday else window_end
    days = (last_spend_day - today).days + 1

    worst = None
    for k in range(window_days + 1):
        bal = forecast.balance_on(today + timedelta(days=k))
        if bal is None:
            continue
        per_day = (bal - cushion) // min(k + 1, days)
        worst = per_day if worst is None else min(worst, per_day)
    daily = max(0, worst or 0)

    going_out = [e for e in forecast.entries_between(today, last_spend_day) if e.kind == BILL]
    pay = sum(e.amount for e in forecast.entries if e.kind == INCOME and e.date == payday) if payday else 0
    return PaydayOutlook(
        payday=payday,
        pay=pay,
        days=days,
        bills=-sum(e.amount for e in going_out),
        bill_count=len(going_out),
        lowest=forecast.lowest(today, last_spend_day),
        daily=daily - daily % 100,
    )
