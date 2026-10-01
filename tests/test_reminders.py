from datetime import date

from balance_tracker.debts import make_plan
from balance_tracker.forecast import Forecast
from balance_tracker.models import AppData, Checkpoint, Debt, RecurringItem, BILL, INCOME
from balance_tracker.reminders import collect, to_ics

TODAY = date(2026, 10, 1)


def sample():
    d = AppData()
    d.checkpoints.append(Checkpoint(TODAY, 200000))
    visa = Debt("Visa", 100000, 20.0, due_day=21, min_percent=1)
    d.debts.append(visa)
    d.items.append(RecurringItem("Netflix", 1899, BILL, "monthly", date(2026, 10, 12), paid_with=visa.id))
    d.items.append(RecurringItem("Rent", 150000, BILL, "monthly", date(2026, 10, 1)))
    d.items.append(RecurringItem("Pay", 250000, INCOME, "biweekly", date(2026, 10, 9)))
    return d, visa


def test_card_bill_shows_as_card_payment_in_forecast():
    d, _ = sample()
    f = Forecast(d, date(2026, 10, 31))
    e = next(e for e in f.entries if "Netflix" in e.description)
    assert e.description == "Pay Visa: Netflix" and e.amount == -1899


def test_collect_and_ics():
    d, visa = sample()
    plan = make_plan(d, TODAY)
    r = collect(d, plan, TODAY, months=2, bills=True, paydays=True)
    titles = [x.title for x in r]
    assert any(t.startswith("💳 Pay Visa $18.99") for t in titles)
    assert any("Visa payment" in t for t in titles)
    assert any("Rent" in t for t in titles) and any("Pay $2,500.00" in t for t in titles)
    ics = to_ics(r, "08:30")
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "DTSTART:20261012T083000" in ics
    assert "TRIGGER:-P1D" in ics
    for line in ics.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
    # stable ids: same input -> same UIDs
    uids = [l for l in ics.split("\r\n") if l.startswith("UID:")]
    assert len(uids) == len(set(uids)) == len(r)


def test_only_card_reminders_by_default():
    d, _ = sample()
    r = collect(d, None, TODAY, months=1, debt_payments=False)
    assert r and all(x.title.startswith("💳 Pay Visa") for x in r)


def test_paid_with_roundtrip():
    d, visa = sample()
    again = AppData.from_dict(d.to_dict())
    assert again.items[0].paid_with == visa.id
    again.card_paid.append("x|2026-10-12")
    assert AppData.from_dict(again.to_dict()).card_paid == ["x|2026-10-12"]
