import random
from datetime import date, timedelta

from balance_tracker.forecast import Forecast, Occurrence
from balance_tracker.insights import (
    UNCATEGORIZED,
    bills_by_category,
    monthly_totals,
    payday_outlook,
    previous_months,
    unpaid_card_charges,
    unplanned_summary,
)
from balance_tracker.models import BILL, INCOME, AppData, Checkpoint, Debt, RecurringItem, card_paid_key

TODAY = date(2026, 10, 12)


def item(name, amount, kind=BILL, freq="monthly", start=TODAY, **kw):
    return RecurringItem(name, amount, kind, freq, start, **kw)


def test_monthly_totals_skip_paused_finished_and_one_time_entries():
    items = [
        item("Pay", 260000, INCOME, "biweekly"),
        item("Rent", 150000),
        item("Gym", 5000, active=False),
        item("Old loan", 30000, end_date=TODAY - timedelta(days=1)),
        item("Laptop", 99900, freq="once"),
        item("Insurance", 120000, freq="yearly"),
    ]
    t = monthly_totals(items, TODAY)
    assert (t.income, t.bills, t.net) == (563333, 160000, 403333)


def test_bills_by_category_groups_case_insensitively_and_sorts_biggest_first():
    items = [
        item("Rent", 150000, category="Housing"),
        item("Hydro", 9000, category="utilities"),
        item("Internet", 7000, category="Utilities"),
        item("Netflix", 1899),
        item("Pay", 260000, INCOME, category="Housing"),
    ]
    rows = bills_by_category(items, TODAY)
    assert [(r.category, r.monthly) for r in rows] == [("Housing", 150000), ("utilities", 16000),
                                                        (UNCATEGORIZED, 1899)]
    assert abs(sum(r.share for r in rows) - 1) < 1e-9
    assert bills_by_category([], TODAY) == []


def test_unpaid_card_charges():
    data = AppData()
    visa = Debt("Visa", 0, 20.0)
    data.debts.append(visa)
    netflix = item("Netflix", 1899, start=date(2026, 9, 30), freq="weekly", paid_with=visa.id)
    data.items += [netflix, item("Rent", 150000)]
    charges = unpaid_card_charges(data, TODAY, 14)
    assert [c.occurrence.date for c in charges] == [date(2026, 9, 30), date(2026, 10, 7)]
    assert charges[0].card is visa and charges[0].amount == 1899
    data.card_paid.append(card_paid_key(netflix.id, date(2026, 9, 30)))
    assert [c.occurrence.date for c in unpaid_card_charges(data, TODAY, 14)] == [date(2026, 10, 7)]


def test_previous_months_crosses_the_year():
    assert previous_months(date(2026, 2, 10), 3) == [(2026, 1), (2025, 12), (2025, 11)]


def test_unplanned_summary_averages_only_months_with_checkins():
    data = AppData()
    data.checkpoints.append(Checkpoint(date(2026, 7, 1), 100000))
    data.add_checkpoint(Checkpoint(date(2026, 8, 10), 90000))  # -10,000 in August
    data.add_checkpoint(Checkpoint(date(2026, 9, 10), 70000))  # -20,000 in September
    data.add_checkpoint(Checkpoint(date(2026, 10, 5), 75000))  # +5,000 this month
    s = unplanned_summary(Forecast(data, TODAY), TODAY)
    assert (s.this_month, s.average, s.months_tracked, s.total, s.checkins) == (5000, -15000, 2, -25000, 3)
    empty = unplanned_summary(Forecast(AppData(checkpoints=[Checkpoint(TODAY, 1)]), TODAY), TODAY)
    assert empty.average is None and empty.total == 0


def payday_data():
    data = AppData()
    data.checkpoints.append(Checkpoint(TODAY, 100000))
    data.items.append(item("Pay", 200000, INCOME, "biweekly", date(2026, 10, 16)))
    data.items.append(item("Phone", 6000, start=date(2026, 10, 14)))
    data.items.append(item("Rent", 150000, start=date(2026, 10, 17)))
    return data


def test_payday_outlook_summary():
    data = payday_data()
    f = Forecast(data, TODAY + timedelta(days=60), TODAY)
    o = payday_outlook(f, TODAY, cushion=10000)
    assert o.payday == date(2026, 10, 16) and o.pay == 200000
    assert o.days == 4  # Oct 12-15
    assert (o.bills, o.bill_count) == (6000, 1)
    assert o.lowest == (date(2026, 10, 14), 94000)


def test_payday_outlook_without_income_uses_the_whole_window():
    data = AppData()
    data.checkpoints.append(Checkpoint(TODAY, 31000 + 10000))
    f = Forecast(data, TODAY + timedelta(days=60), TODAY)
    o = payday_outlook(f, TODAY, cushion=10000)
    assert o.payday is None and o.days == 31
    assert o.daily == 1000  # $310 over 31 days
    assert payday_outlook(Forecast(AppData(), TODAY), TODAY, 0) is None


def _keeps_cushion(data, today, cushion, per_day, days, window):
    spend = [Occurrence(today + timedelta(days=k), today + timedelta(days=k), -per_day,
                        RecurringItem("spend", per_day, BILL, "once", today, id="")) for k in range(days)]
    f = Forecast(data, today + timedelta(days=window + 5), today, extra=spend)
    return all(f.balance_on(today + timedelta(days=k)) >= cushion for k in range(window + 1))


def test_daily_allowance_is_the_largest_safe_amount_randomized():
    rng = random.Random(99)
    checked = 0
    for _ in range(80):
        data = AppData()
        today = date(2026, 1, 1) + timedelta(days=rng.randint(0, 400))
        data.checkpoints.append(Checkpoint(today, rng.randint(0, 400000), includes_today=True))
        data.items.append(item("Pay", rng.randint(50000, 300000), INCOME, rng.choice(["weekly", "biweekly", "monthly"]),
                               today + timedelta(days=rng.randint(1, 35))))
        for n in range(rng.randint(0, 4)):
            due = today + timedelta(days=rng.randint(0, 30))
            data.items.append(item(f"Bill{n}", rng.randint(1000, 120000), start=due))
        cushion = rng.choice([0, 10000, 50000])
        f = Forecast(data, today + timedelta(days=60), today)
        o = payday_outlook(f, today, cushion)
        if not _keeps_cushion(data, today, cushion, 0, o.days, 30):
            assert o.daily == 0  # already short of the cushion without spending anything
            continue
        assert _keeps_cushion(data, today, cushion, o.daily, o.days, 30)
        if o.daily > 0 or _keeps_cushion(data, today, cushion, 100, o.days, 30):
            checked += 1
            assert not _keeps_cushion(data, today, cushion, o.daily + 100, o.days, 30), "allowance too small"
    assert checked > 40
