"""Scheduling and day-by-day balance projection."""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterator, Optional

from .models import AppData, Checkpoint, RecurringItem, INCOME, LAST_DAY

STEP_DAYS = {"weekly": 7, "biweekly": 14, "fourweekly": 28}
STEP_MONTHS = {"monthly": 1, "bimonthly": 2, "quarterly": 3, "semiannual": 6, "yearly": 12}

# How many times per year each frequency happens (used for monthly averages)
PER_YEAR = {
    "once": 0, "weekly": 52, "biweekly": 26, "fourweekly": 13, "semimonthly": 24,
    "monthly": 12, "bimonthly": 6, "quarterly": 4, "semiannual": 2, "yearly": 1,
}


# --------------------------------------------------------------------------
# Date helpers
# --------------------------------------------------------------------------
def clamp_day(year: int, month: int, day: int) -> date:
    """Date in the given month, using the last day if `day` is too large."""
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def add_months(d: date, months: int, day: Optional[int] = None) -> date:
    m = d.month - 1 + months
    return clamp_day(d.year + m // 12, m % 12 + 1, day or d.day)


def shift_weekend(d: date, rule: str) -> date:
    wd = d.weekday()  # Mon=0 .. Sun=6
    if wd < 5 or rule == "none":
        return d
    if rule == "before":
        return d - timedelta(days=wd - 4)
    return d + timedelta(days=7 - wd)


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def scheduled_dates(item: RecurringItem, until: date, since: Optional[date] = None) -> Iterator[date]:
    """Yield the scheduled (pre-weekend-shift) dates of `item` up to `until`."""
    start = item.start_date
    end = min(until, item.end_date) if item.end_date else until
    since = since or start
    if end < start:
        return
    f = item.frequency
    if f == "once":
        yield start
    elif f in STEP_DAYS:
        step = STEP_DAYS[f]
        k = max(0, (since - start).days // step - 1)
        d = start + timedelta(days=step * k)
        while d <= end:
            yield d
            d += timedelta(days=step)
    elif f in STEP_MONTHS:
        step = STEP_MONTHS[f]
        k = max(0, _months_between(start, since) // step - 1)
        while True:
            d = add_months(start, step * k, start.day)
            if d > end:
                break
            yield d
            k += 1
    elif f == "semimonthly":
        days = sorted({start.day, item.second_day if item.second_day else LAST_DAY})
        k = max(0, _months_between(start, since) - 1)
        while True:
            first = add_months(start.replace(day=1), k, 1)
            if first > end:
                break
            for dd in days:
                d = clamp_day(first.year, first.month, dd)
                if start <= d <= end:
                    yield d
            k += 1


@dataclass
class Occurrence:
    date: date  # date it actually hits the account
    scheduled: date  # date before any weekend shift (key for overrides)
    amount: int  # signed cents
    item: RecurringItem
    overridden: bool = False


def occurrences(item: RecurringItem, start: date, end: date) -> list:
    """All occurrences of `item` that post between start and end (inclusive)."""
    out = []
    if not item.active:
        return out
    for sd in scheduled_dates(item, end + timedelta(days=3), since=start - timedelta(days=3)):
        post = shift_weekend(sd, item.weekend_rule)
        if post < start or post > end:
            continue
        key = sd.isoformat()
        if key in item.overrides:
            ov = item.overrides[key]
            if ov is None:
                continue  # skipped
            amt = abs(ov) if item.kind == INCOME else -abs(ov)
            out.append(Occurrence(post, sd, amt, item, overridden=True))
        else:
            out.append(Occurrence(post, sd, item.signed_amount, item))
    return out


def next_occurrence(item: RecurringItem, today: date) -> Optional[Occurrence]:
    for horizon in (400, 4000):
        occ = occurrences(item, today, today + timedelta(days=horizon))
        if occ:
            return min(occ, key=lambda o: o.date)
    return None


def monthly_equivalent(item: RecurringItem) -> int:
    """Signed average amount per month (cents)."""
    return round(item.signed_amount * PER_YEAR[item.frequency] / 12)


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------
@dataclass
class Entry:
    date: date
    kind: str  # start | income | bill | checkin
    description: str
    amount: int
    balance: int
    category: str = ""
    item_id: Optional[str] = None
    scheduled: Optional[date] = None
    checkpoint_id: Optional[str] = None
    overridden: bool = False
    projected: Optional[int] = None  # for check-ins: balance the plan expected


class Forecast:
    """Day-by-day projected balance from the starting balance to `end`."""

    def __init__(self, data: AppData, end: date, today: Optional[date] = None,
                 extra: Optional[list] = None, suppress: Optional[dict] = None):
        """`extra`: additional Occurrences (e.g. planned debt payments).
        `suppress`: item_id -> date; that item's occurrences on/after the date are left out."""
        self.data = data
        self.today = today or date.today()
        self.extra = extra or []
        self.suppress = suppress or {}
        self.entries: list = []
        self.daily: dict = {}  # date -> end-of-day balance
        self.start: Optional[date] = None
        self.end = end
        self._build()

    def _build(self) -> None:
        cps = self.data.sorted_checkpoints()
        if not cps:
            return
        first = cps[0]
        self.start = first.date
        if self.end < first.date:
            self.end = first.date
        cp_by_date = {c.date: c for c in cps}

        occ_by_date = defaultdict(list)
        for item in self.data.items:
            cut = self.suppress.get(item.id)
            for o in occurrences(item, first.date, self.end):
                if cut is None or o.date < cut:
                    occ_by_date[o.date].append(o)
        start_extras = []
        for o in self.extra:
            if o.date == first.date:
                start_extras.append(o)  # never part of an entered balance
            elif first.date < o.date <= self.end:
                occ_by_date[o.date].append(o)

        running = first.balance
        d = first.date
        one = timedelta(days=1)
        while d <= self.end:
            todays = sorted(occ_by_date.get(d, []), key=lambda o: (o.amount < 0, o.item.name.lower()))
            if d == first.date:
                self.entries.append(Entry(d, "start", "Starting balance", 0, running,
                                          checkpoint_id=first.id))
                if not first.includes_today:
                    todays = sorted(todays + start_extras, key=lambda o: (o.amount < 0, o.item.name.lower()))
                    running = self._apply(todays, running)
                else:
                    running = self._apply(start_extras, running)
            else:
                cp = cp_by_date.get(d)
                if cp is not None and not cp.includes_today:
                    running = self._checkin(cp, running)
                    running = self._apply(todays, running)
                elif cp is not None:
                    running = self._apply(todays, running)
                    running = self._checkin(cp, running)
                else:
                    running = self._apply(todays, running)
            self.daily[d] = running
            d += one

    def _apply(self, occs, running: int) -> int:
        for o in occs:
            running += o.amount
            desc = o.item.name
            card = self.data.debt(o.item.paid_with) if o.item.paid_with else None
            if card is not None:
                desc = f"Pay {card.name}: {o.item.name}"
            self.entries.append(Entry(
                o.date, "income" if o.amount >= 0 else "bill", desc, o.amount, running,
                category=o.item.category, item_id=o.item.id or None, scheduled=o.scheduled,
                overridden=o.overridden))
        return running

    def _checkin(self, cp: Checkpoint, running: int) -> int:
        diff = cp.balance - running
        if diff < 0:
            desc = "Check-in: unplanned spending"
        elif diff > 0:
            desc = "Check-in: unplanned income"
        else:
            desc = "Check-in: right on plan"
        if cp.note:
            desc += f" — {cp.note}"
        self.entries.append(Entry(cp.date, "checkin", desc, diff, cp.balance,
                                  checkpoint_id=cp.id, projected=running))
        return cp.balance

    # ---- queries -----------------------------------------------------
    @property
    def empty(self) -> bool:
        return not self.daily

    def balance_on(self, d: date) -> Optional[int]:
        """End-of-day balance on `d` (None if outside the projection)."""
        return self.daily.get(d)

    def balance_before(self, d: date) -> Optional[int]:
        """Balance at the start of day `d`, before that day's items."""
        if self.start is None or d < self.start:
            return None
        if d == self.start:
            return self.data.start.balance
        return self.daily.get(d - timedelta(days=1))

    def entries_between(self, a: date, b: date) -> list:
        return [e for e in self.entries if a <= e.date <= b]

    def lowest(self, a: date, b: date):
        """(date, balance) of the lowest end-of-day balance in [a, b]."""
        best = None
        d = max(a, self.start) if self.start else a
        one = timedelta(days=1)
        while d <= b:
            bal = self.daily.get(d)
            if bal is not None and (best is None or bal < best[1]):
                best = (d, bal)
            d += one
        return best

    def first_below(self, threshold: int, a: date, b: Optional[date] = None):
        for d, bal in self.daily.items():
            if d >= a and (b is None or d <= b) and bal < threshold:
                return d, bal
        return None

    def next_income(self, after: date) -> Optional[Entry]:
        return next((e for e in self.entries if e.kind == "income" and e.date > after), None)

    def safe_to_spend(self, today: date, days: int = 30, cushion: int = 0) -> Optional[int]:
        """How much could be spent today without any day in the next `days`
        dropping below `cushion`. Spending today lowers every future balance,
        so this is simply the lowest future balance minus the cushion."""
        low = self.lowest(today, today + timedelta(days=days))
        if low is None:
            return None
        return low[1] - cushion

    def unplanned_by_month(self) -> dict:
        """(year, month) -> net unplanned amount from check-ins (negative = overspent)."""
        out = defaultdict(int)
        for e in self.entries:
            if e.kind == "checkin":
                out[(e.date.year, e.date.month)] += e.amount
        return dict(out)

    def checkins(self) -> list:
        return [e for e in self.entries if e.kind == "checkin"]


def horizon_end(data: AppData, today: date) -> date:
    """End of the user's chosen 'forecast ahead' window (used for alerts and stats)."""
    return add_months(today, data.settings.forecast_months)


def projection_end(data: AppData, today: date) -> date:
    """How far the forecast is computed: at least a year so every chart range works."""
    return add_months(today, max(12, data.settings.forecast_months))
