"""Cross-checks web/engine.js (iPhone app) against the Python engine on random scenarios."""
import json
import random
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from balance_tracker.debts import full_forecast, make_plan
from balance_tracker.forecast import monthly_equivalent, next_occurrence, projection_end
from balance_tracker.models import (
    AppData, Checkpoint, Debt, FREQUENCIES, RecurringItem, WEEKEND_RULES, BILL, INCOME,
)
from balance_tracker.sync import merge, stamp

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def rand_data(rng: random.Random, today: date) -> AppData:
    d = AppData()
    start = today - timedelta(days=rng.randint(0, 60))
    d.checkpoints.append(Checkpoint(start, rng.randint(-50000, 500000), includes_today=rng.random() < 0.7,
                                    created_at="2026-01-01T00:00:00"))
    for k in range(rng.randint(0, 3)):
        day = start + timedelta(days=rng.randint(1, max(1, (today - start).days + 3)))
        d.add_checkpoint(Checkpoint(day, rng.randint(0, 400000), includes_today=rng.random() < 0.5,
                                    note=rng.choice(["", "groceries"]), created_at=f"2026-01-0{k + 2}T00:00:00"))
    for _ in range(rng.randint(1, 3)):
        d.debts.append(Debt(rng.choice(["Visa", "MC", "LOC", "Amex"]) + str(rng.randint(1, 9)),
                            rng.randint(0, 900000), round(rng.uniform(0, 29.99), 2),
                            kind=rng.choice(["credit_card", "line_of_credit", "loan"]), due_day=rng.randint(1, 31),
                            min_amount=rng.choice([0, 1000, 2500, 15000]), min_percent=rng.choice([0, 1, 2, 3.5]),
                            min_plus_interest=rng.random() < 0.6))
    for n in range(rng.randint(2, 9)):
        kind = INCOME if n == 0 or rng.random() < 0.25 else BILL
        freq = rng.choice(list(FREQUENCIES))
        sd = today + timedelta(days=rng.randint(-400, 40))
        it = RecurringItem(f"Item{n}", rng.randint(500, 300000), kind, freq, sd,
                           end_date=sd + timedelta(days=rng.randint(10, 600)) if rng.random() < 0.2 else None,
                           second_day=rng.choice([15, 28, 31]), weekend_rule=rng.choice(list(WEEKEND_RULES)),
                           active=rng.random() < 0.9, category=rng.choice(["", "Food"]))
        if kind == BILL and rng.random() < 0.3:
            it.paid_with = rng.choice(d.debts).id
        if rng.random() < 0.3:
            occ = today + timedelta(days=rng.randint(0, 60))
            it.overrides[occ.isoformat()] = rng.choice([None, rng.randint(0, 50000)])
        d.items.append(it)
    if rng.random() < 0.3:
        d.debts[0].linked_bill_id = d.items[-1].id
    s = d.settings
    s.low_balance_threshold = rng.choice([0, 10000, 50000])
    s.forecast_months = rng.choice([3, 6, 12, 18])
    s.debt_strategy = rng.choice(["avalanche", "snowball"])
    s.debt_mode = rng.choice(["auto", "fixed"])
    s.debt_fixed_extra = rng.choice([0, 5000, 25000])
    s.debt_in_forecast = rng.random() < 0.6
    return d


def python_result(data: AppData, today: date) -> dict:
    plan = make_plan(data, today) if data.debts else None
    f = full_forecast(data, plan, today, projection_end(data, today))
    res = {
        "daily": [[d.isoformat(), v] for d, v in f.daily.items()],
        "entries": [[e.date.isoformat(), e.kind, e.description, e.amount, e.balance] for e in f.entries],
        "monthly": [monthly_equivalent(i) for i in data.items],
        "next": [(lambda o: o.date.isoformat() if o else None)(next_occurrence(i, today)) for i in data.items],
    }
    if plan:
        res["payments"] = [[p.date.isoformat(), p.debt_id, p.amount, p.extra] for p in plan.payments]
        res["interest"] = plan.total_interest
        res["debt_free"] = plan.debt_free.isoformat() if plan.debt_free else None
        res["rows"] = [[m.isoformat(), per, x] for m, per, x in plan.month_rows(today, 12)]
        for strat in ("avalanche", "snowball"):
            for mode in ("minimum", "fixed", "auto"):
                p = make_plan(data, today, strategy=strat, mode=mode)
                res[f"{strat}-{mode}"] = [p.total_interest, len(p.payments),
                                          p.debt_free.isoformat() if p.debt_free else None]
    return res


def run_node(tmp_path, scenarios):
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps(scenarios))
    out = subprocess.run(["node", str(ROOT / "tests" / "web_runner.mjs"), str(path)],
                         capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_engine_matches_python(tmp_path):
    rng = random.Random(20261001)
    scenarios, expected = [], []
    for k in range(60):
        today = date(2026, 1, 1) + timedelta(days=rng.randint(0, 700))
        data = rand_data(rng, today)
        scenarios.append({"data": data.to_dict(), "today": today.isoformat()})
        expected.append(python_result(data, today))
    got = run_node(tmp_path, scenarios)
    for k, (exp, js) in enumerate(zip(expected, got)):
        for key in exp:
            assert js[key] == exp[key], f"scenario {k}: {key} differs"


def test_merge_matches_python(tmp_path):
    rng = random.Random(7)
    scenarios, expected = [], []
    for k in range(25):
        today = date(2026, 3, 1)
        base = rand_data(rng, today)
        stamp(None, base, "2026-03-01T00:00:00.000Z")
        a, b = AppData.from_dict(base.to_dict()), AppData.from_dict(base.to_dict())
        for side, t in ((a, "2026-03-02T00:00:00.000Z"), (b, "2026-03-0%dT00:00:00.000Z" % rng.randint(1, 3))):
            prev = AppData.from_dict(side.to_dict())
            if side.items and rng.random() < 0.5:
                side.items.pop(rng.randrange(len(side.items)))
            if side.items:
                rng.choice(side.items).amount += 1
            side.items.append(RecurringItem(f"New{rng.randint(0, 999)}", 100, BILL, "monthly", today))
            if rng.random() < 0.5:
                side.settings.low_balance_threshold += 1
            side.add_checkpoint(Checkpoint(today + timedelta(days=rng.randint(0, 3)), rng.randint(0, 9999),
                                           created_at=t))
            stamp(prev, side, t)
        scenarios.append({"merge": [a.to_dict(), b.to_dict()]})
        m = merge(a, b).to_dict()
        m.pop("saved_at")
        expected.append(m)
    got = run_node(tmp_path, scenarios)
    for k, (exp, js) in enumerate(zip(expected, got)):
        back = AppData.from_dict(js["merged"]).to_dict()
        back.pop("saved_at")
        norm = lambda d: json.dumps({**d, "items": sorted(d["items"], key=lambda x: x["id"]),
                                     "debts": sorted(d["debts"], key=lambda x: x["id"]),
                                     "checkpoints": sorted(d["checkpoints"], key=lambda x: x["id"])}, sort_keys=True)
        assert norm(back) == norm(exp), f"merge scenario {k} differs"
