from datetime import date, timedelta

import pytest

from balance_tracker.forecast import (
    Forecast, occurrences, scheduled_dates, shift_weekend, monthly_equivalent, next_occurrence,
)
from balance_tracker.models import AppData, Checkpoint, RecurringItem, INCOME, BILL
from balance_tracker.storage import Store, export_backup, read_backup, merge_data


def item(**kw):
    kw.setdefault("name", "Thing")
    kw.setdefault("amount", 10000)
    return RecurringItem(**kw)


def dates(it, until):
    return list(scheduled_dates(it, until))


def test_weekly_and_biweekly():
    w = item(frequency="weekly", start_date=date(2026, 1, 2))
    assert dates(w, date(2026, 1, 23)) == [date(2026, 1, d) for d in (2, 9, 16, 23)]
    b = item(frequency="biweekly", start_date=date(2026, 1, 2))
    assert dates(b, date(2026, 2, 1)) == [date(2026, 1, 2), date(2026, 1, 16), date(2026, 1, 30)]


def test_monthly_clamps_to_month_end_and_recovers():
    m = item(frequency="monthly", start_date=date(2026, 1, 31))
    assert dates(m, date(2026, 4, 30)) == [
        date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]


def test_semimonthly_15th_and_last_day():
    s = item(frequency="semimonthly", start_date=date(2026, 2, 15), second_day=31)
    assert dates(s, date(2026, 3, 31)) == [
        date(2026, 2, 15), date(2026, 2, 28), date(2026, 3, 15), date(2026, 3, 31)]


def test_yearly_leap_day():
    y = item(frequency="yearly", start_date=date(2024, 2, 29))
    assert dates(y, date(2026, 3, 1)) == [date(2024, 2, 29), date(2025, 2, 28), date(2026, 2, 28)]


def test_end_date_and_once():
    m = item(frequency="monthly", start_date=date(2026, 1, 5), end_date=date(2026, 3, 4))
    assert dates(m, date(2026, 12, 31)) == [date(2026, 1, 5), date(2026, 2, 5)]
    o = item(frequency="once", start_date=date(2026, 5, 5))
    assert dates(o, date(2026, 12, 31)) == [date(2026, 5, 5)]


def test_weekend_shift():
    sat = date(2026, 10, 3)
    assert shift_weekend(sat, "before") == date(2026, 10, 2)
    assert shift_weekend(sat, "after") == date(2026, 10, 5)
    assert shift_weekend(date(2026, 10, 4), "before") == date(2026, 10, 2)
    assert shift_weekend(sat, "none") == sat


def test_occurrence_window_far_from_start_is_efficient_and_correct():
    w = item(frequency="weekly", start_date=date(2000, 1, 3))
    occ = occurrences(w, date(2026, 10, 1), date(2026, 10, 31))
    assert [o.date for o in occ] == [date(2026, 10, d) for d in (5, 12, 19, 26)]


def test_overrides_skip_and_change():
    m = item(frequency="monthly", start_date=date(2026, 1, 10), kind=BILL,
             overrides={"2026-02-10": None, "2026-03-10": 2500})
    occ = occurrences(m, date(2026, 1, 1), date(2026, 3, 31))
    assert [(o.date.month, o.amount) for o in occ] == [(1, -10000), (3, -2500)]


def test_monthly_equivalent():
    assert monthly_equivalent(item(frequency="biweekly", kind=INCOME, amount=120000)) == 260000
    assert monthly_equivalent(item(frequency="yearly", amount=12000)) == -1000


def build_data():
    d = AppData()
    d.checkpoints.append(Checkpoint(date(2026, 10, 1), 100000, includes_today=True))
    d.items.append(item(name="Pay", kind=INCOME, amount=200000, frequency="biweekly",
                        start_date=date(2026, 10, 9)))
    d.items.append(item(name="Rent", kind=BILL, amount=150000, frequency="monthly",
                        start_date=date(2026, 10, 1)))
    d.items.append(item(name="Phone", kind=BILL, amount=5000, frequency="monthly",
                        start_date=date(2026, 10, 15)))
    return d


def test_forecast_daily_balances():
    f = Forecast(build_data(), date(2026, 11, 2), today=date(2026, 10, 1))
    # Rent on Oct 1 is already included in the starting balance
    assert f.balance_on(date(2026, 10, 1)) == 100000
    assert f.balance_on(date(2026, 10, 9)) == 300000
    assert f.balance_on(date(2026, 10, 15)) == 295000
    assert f.balance_on(date(2026, 10, 23)) == 495000
    assert f.balance_on(date(2026, 11, 1)) == 345000
    assert f.lowest(date(2026, 10, 1), date(2026, 11, 2)) == (date(2026, 10, 1), 100000)
    assert f.safe_to_spend(date(2026, 10, 1), 30, cushion=10000) == 90000
    assert f.next_income(date(2026, 10, 1)).date == date(2026, 10, 9)


def test_start_not_including_today_applies_todays_items():
    d = build_data()
    d.checkpoints[0].includes_today = False
    f = Forecast(d, date(2026, 10, 5))
    assert f.balance_on(date(2026, 10, 1)) == -50000


def test_checkin_records_unplanned_spending():
    d = build_data()
    d.add_checkpoint(Checkpoint(date(2026, 10, 12), 270000, includes_today=True, note="groceries"))
    f = Forecast(d, date(2026, 10, 31))
    ci = f.checkins()
    assert len(ci) == 1
    assert ci[0].projected == 300000
    assert ci[0].amount == -30000
    assert "groceries" in ci[0].description
    assert f.balance_on(date(2026, 10, 12)) == 270000
    assert f.balance_on(date(2026, 10, 15)) == 265000
    assert f.unplanned_by_month() == {(2026, 10): -30000}


def test_checkin_before_todays_items():
    d = build_data()
    d.add_checkpoint(Checkpoint(date(2026, 10, 9), 90000, includes_today=False))
    f = Forecast(d, date(2026, 10, 10))
    assert f.checkins()[0].amount == -10000
    assert f.balance_on(date(2026, 10, 9)) == 290000


def test_add_checkpoint_replaces_same_day():
    d = build_data()
    d.add_checkpoint(Checkpoint(date(2026, 10, 12), 1))
    d.add_checkpoint(Checkpoint(date(2026, 10, 12), 2))
    assert [c.balance for c in d.checkpoints if c.date == date(2026, 10, 12)] == [2]


def test_inactive_items_ignored_and_next_occurrence():
    d = build_data()
    d.items[2].active = False
    f = Forecast(d, date(2026, 10, 20))
    assert f.balance_on(date(2026, 10, 20)) == 300000
    assert next_occurrence(d.items[0], date(2026, 10, 10)).date == date(2026, 10, 23)


def test_roundtrip_and_store(tmp_path):
    d = build_data()
    d.items[1].overrides = {"2026-11-01": None}
    s = Store(tmp_path)
    s.save(d)
    loaded = s.load()
    assert loaded.to_dict()["items"] == d.to_dict()["items"]
    assert s.auto_backups()
    p = tmp_path / "backup.json"
    export_backup(d, p)
    assert read_backup(p).items[0].name == "Pay"


def test_bad_backup_rejected(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"hello": 1}')
    with pytest.raises(ValueError):
        read_backup(p)
    p.write_text("not json")
    with pytest.raises(ValueError):
        read_backup(p)


def test_merge():
    a = build_data()
    b = AppData.from_dict(a.to_dict())
    b.items.append(item(name="Gym"))
    merged = merge_data(a, b)
    assert len(merged.items) == 4 and len(merged.checkpoints) == 1
