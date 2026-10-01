from datetime import date, timedelta

from balance_tracker.debts import make_plan, simulate, minimum_payment, base_forecast
from balance_tracker.forecast import Forecast
from balance_tracker.models import AppData, Checkpoint, Debt, RecurringItem, INCOME, BILL

TODAY = date(2026, 10, 1)


def card(name, bal, apr, **kw):
    kw.setdefault("due_day", 20)
    kw.setdefault("min_amount", 1000)
    kw.setdefault("min_percent", 1.0)
    return Debt(name=name, balance=bal, apr=apr, **kw)


def test_minimum_payment_rules():
    d = card("Visa", 100000, 24.0, min_percent=3, min_plus_interest=False)
    assert minimum_payment(d, 100000, 2000) == 3000
    d.min_plus_interest = True
    assert minimum_payment(d, 100000, 2000) == 5000
    assert minimum_payment(d, 500, 0) == 500  # never more than owed


def test_minimums_only_pays_off_and_tracks_interest():
    d = card("Visa", 100000, 12.0, min_amount=10000, min_percent=0, min_plus_interest=False)
    plan = simulate([d], TODAY, "avalanche", {})
    assert plan.payoff[d.id] is not None
    paid = sum(p.amount for p in plan.payments)
    assert paid == 100000 + plan.total_interest
    assert 4000 < plan.total_interest < 7000


def test_interest_only_never_pays_off():
    d = card("LOC", 500000, 9.0, min_amount=0, min_percent=0, min_plus_interest=True)
    plan = simulate([d], TODAY, "avalanche", {})
    assert d.id not in plan.payoff and plan.debt_free is None


def test_avalanche_vs_snowball_order():
    a = card("Big high", 300000, 25.0)
    b = card("Small low", 50000, 5.0)
    av = simulate([a, b], TODAY, "avalanche", {m: 50000 for m in range(120)})
    sn = simulate([a, b], TODAY, "snowball", {m: 50000 for m in range(120)})
    assert av.order[0] == a.id and sn.order[0] == b.id
    assert av.total_interest < sn.total_interest
    assert sn.payoff[b.id] < av.payoff[b.id]


def data_with_income(surplus_per_month):
    data = AppData()
    data.checkpoints.append(Checkpoint(TODAY, 100000))
    data.items.append(RecurringItem("Pay", 300000, INCOME, "monthly", date(2026, 10, 15)))
    data.items.append(RecurringItem("Rent", 300000 - surplus_per_month, BILL, "monthly", date(2026, 10, 16)))
    data.settings.low_balance_threshold = 50000
    return data


def test_auto_plan_keeps_cushion():
    data = data_with_income(80000)
    data.debts = [card("Visa", 400000, 20.0, min_percent=2), card("MC", 150000, 12.0, min_percent=2)]
    plan = make_plan(data, TODAY)
    assert plan.debt_free is not None
    assert any(p.extra for p in plan.payments)
    f = Forecast(data, plan.debt_free + timedelta(days=60), TODAY, extra=plan.occurrences(data.debts))
    low = f.lowest(TODAY, f.end)
    assert low[1] >= data.settings.low_balance_threshold
    # the extra goes to the highest rate first
    first_extra = plan.next_extra(TODAY)
    assert data.debt(first_extra.debt_id).name == "Visa"
    # and it beats paying minimums only
    mins = make_plan(data, TODAY, mode="minimum")
    assert plan.total_interest < mins.total_interest


def test_auto_plan_with_no_room_pays_only_minimums():
    data = data_with_income(0)
    data.checkpoints[0].balance = 50000  # sitting right at the cushion
    data.debts = [card("Visa", 100000, 20.0, min_percent=3)]
    plan = make_plan(data, TODAY)
    assert not any(p.extra for p in plan.payments)


def test_fixed_mode_rolls_over_freed_minimums():
    data = data_with_income(0)
    data.settings.debt_mode = "fixed"
    data.settings.debt_fixed_extra = 20000
    data.debts = [card("A", 30000, 20.0), card("B", 300000, 10.0)]
    plan = make_plan(data, TODAY)
    assert plan.debt_free is not None


def test_linked_bill_is_replaced_by_plan():
    data = data_with_income(50000)
    bill = RecurringItem("Visa payment", 5000, BILL, "monthly", date(2026, 10, 20))
    data.items.append(bill)
    data.debts = [card("Visa", 100000, 20.0, linked_bill_id=bill.id)]
    base = base_forecast(data, TODAY)
    assert not any(e.item_id == bill.id for e in base.entries)


def test_debt_roundtrip():
    data = AppData()
    data.debts.append(card("Visa", 12345, 19.99, credit_limit=500000))
    again = AppData.from_dict(data.to_dict())
    assert again.debts[0].to_dict() == data.debts[0].to_dict()
    assert AppData.from_dict({"items": []}).debts == []


def test_schedule_shows_months_when_this_months_due_date_passed():
    t = date(2026, 10, 25)
    plan = simulate([card("Visa", 300000, 20.0, due_day=20)], t, "avalanche", {})
    rows = plan.month_rows(t, 12)
    assert len(rows) == 12
    assert rows[0][1] == {} and rows[1][1]  # nothing left in October, November has the payment
